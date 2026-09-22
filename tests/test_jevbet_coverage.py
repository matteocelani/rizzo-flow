"""Scopa priority branches, tre sette rank matrix, roulette order and history."""

from __future__ import annotations

import random

import pytest

from jevbet.games.registry import load_game_state
from jevbet.policy import RiskPolicy
from jevbet.strategy import recommend
from jevbet.strategy.roulette import BET_PREFERENCE

# Low to high. Asso (1) wins a trick; 2 is the cheapest pip.
_ORDER = ["2", "4", "5", "6", "7", "Fante", "Cavallo", "Re", "3", "1"]
_BET_TYPES = (
    "pass",
    "red",
    "black",
    "even",
    "odd",
    "low",
    "high",
    "dozen",
    "column",
    "sixline",
    "corner",
    "street",
    "split",
    "straight_up",
)


def _play(rank, suit, captured=(), scopa=False):
    return {
        "hand_card": {"rank": rank, "suit": suit},
        "table_cards": [{"rank": r, "suit": s} for r, s in captured],
        "is_scopa": scopa,
    }


def _scopa(plays):
    hand = []
    seen = set()
    for play in plays:
        label = f"{play['hand_card']['rank']}-{play['hand_card']['suit']}"
        if label not in seen:
            hand.append(play["hand_card"])
            seen.add(label)
    return load_game_state(
        {
            "game": "scopa",
            "hand": hand,
            "table": [],
            "legal_plays": plays,
            "bankroll": {"cash": 0, "currency": "EUR"},
        }
    )


def _tressette(*, trick, legal, trump="denari"):
    return load_game_state(
        {
            "game": "tre_sette",
            "hand": list(legal),
            "trump_suit": trump,
            "lead_suit": trick[0]["suit"] if trick else None,
            "trick": trick,
            "legal_cards": legal,
            "bankroll": {"cash": 0, "currency": "EUR"},
        }
    )


def test_scopa_scores_every_priority_branch():
    policy = RiskPolicy(min_bet=0)
    scopa = recommend(
        _scopa(
            [
                _play("7", "denari", [("3", "coppe"), ("4", "bastoni"), ("Re", "spade")]),
                _play("2", "spade", [("5", "bastoni")], scopa=True),
            ]
        ),
        policy,
    )
    assert scopa.action == "p1"
    assert "scopa" in scopa.reason

    count = recommend(
        _scopa(
            [
                _play("7", "denari", [("7", "bastoni")]),
                _play("5", "coppe", [("2", "bastoni"), ("3", "spade")]),
            ]
        ),
        policy,
    )
    assert count.action == "p1"

    sevens = recommend(
        _scopa(
            [
                _play("2", "spade", [("5", "coppe"), ("7", "denari")]),
                _play("2", "coppe", [("7", "spade"), ("7", "bastoni")]),
            ]
        ),
        policy,
    )
    assert sevens.action == "p1"
    assert "sevens" in sevens.reason or "2 sevens" in sevens.reason

    bello = recommend(
        _scopa(
            [
                _play("2", "denari", [("5", "coppe"), ("7", "spade")]),
                _play("3", "coppe", [("4", "spade"), ("7", "denari")]),
            ]
        ),
        policy,
    )
    assert bello.action == "p1"
    assert "sette bello" in bello.reason

    denari = recommend(
        _scopa(
            [
                _play("3", "coppe", [("3", "spade")]),
                _play("2", "denari", [("2", "bastoni")]),
            ]
        ),
        policy,
    )
    assert denari.action == "p1"
    assert "denari" in denari.reason

    trail = recommend(
        _scopa([_play("Re", "coppe"), _play("Fante", "spade"), _play("2", "denari")]),
        policy,
    )
    assert trail.action == "p2"
    assert "lowest" in trail.reason


@pytest.mark.parametrize("rank", _ORDER)
def test_tre_sette_lead_spends_a_non_trump(rank: str):
    policy = RiskPolicy(min_bet=0)
    legal = [
        {"rank": "1", "suit": "denari"},
        {"rank": rank, "suit": "coppe"},
    ]
    advice = recommend(_tressette(trick=[], legal=legal), policy)
    assert advice.action == f"c1_{rank}_coppe"
    assert "leading" in advice.reason


def test_tre_sette_lead_picks_the_lowest_rank():
    policy = RiskPolicy(min_bet=0)
    legal = [{"rank": rank, "suit": "coppe"} for rank in reversed(_ORDER)]
    advice = recommend(_tressette(trick=[], legal=legal), policy)
    assert advice.action == f"c{len(legal) - 1}_2_coppe"


@pytest.mark.parametrize("index", range(len(_ORDER)))
def test_tre_sette_follow_wins_with_the_lowest_sufficient_rank(index: int):
    policy = RiskPolicy(min_bet=0)
    legal = [{"rank": rank, "suit": "coppe"} for rank in _ORDER]
    advice = recommend(
        _tressette(trick=[{"rank": _ORDER[index], "suit": "coppe"}], legal=legal),
        policy,
    )
    if index + 1 < len(_ORDER):
        winner = _ORDER[index + 1]
        assert advice.action == f"c{index + 1}_{winner}_coppe"
        assert "win the trick" in advice.reason
    else:
        assert advice.action == "c0_2_coppe"
        assert "cannot win" in advice.reason


@pytest.mark.parametrize("index", range(1, len(_ORDER)))
def test_tre_sette_dumps_the_lowest_card_when_nothing_wins(index: int):
    policy = RiskPolicy(min_bet=0)
    weaker = list(reversed(_ORDER[:index]))
    advice = recommend(
        _tressette(
            trick=[{"rank": _ORDER[index], "suit": "coppe"}],
            legal=[{"rank": rank, "suit": "coppe"} for rank in weaker],
        ),
        policy,
    )
    assert advice.action == f"c{weaker.index('2')}_2_coppe"
    assert "cannot win" in advice.reason


def test_tre_sette_prefers_a_winning_non_trump_and_otherwise_the_lowest_trump():
    policy = RiskPolicy(min_bet=0)
    both_win = recommend(
        _tressette(
            trick=[{"rank": "7", "suit": "coppe"}],
            legal=[
                {"rank": "2", "suit": "coppe"},
                {"rank": "Re", "suit": "coppe"},
                {"rank": "2", "suit": "denari"},
            ],
        ),
        policy,
    )
    assert both_win.action == "c1_Re_coppe"

    only_trump = recommend(
        _tressette(
            trick=[{"rank": "1", "suit": "coppe"}],
            legal=[
                {"rank": "7", "suit": "coppe"},
                {"rank": "Re", "suit": "denari"},
                {"rank": "2", "suit": "denari"},
            ],
        ),
        policy,
    )
    assert only_trump.action == "c2_2_denari"

    save_trump = recommend(
        _tressette(
            trick=[{"rank": "1", "suit": "denari"}],
            legal=[
                {"rank": "2", "suit": "denari"},
                {"rank": "4", "suit": "coppe"},
                {"rank": "Re", "suit": "denari"},
            ],
        ),
        policy,
    )
    assert save_trump.action == "c1_4_coppe"
    assert "cannot win" in save_trump.reason


def _roulette(types: list[str], history: list[int], wheel: str = "european"):
    return load_game_state(
        {
            "game": "roulette",
            "wheel": wheel,
            "last_results": history,
            "legal_bet_types": types,
            "chip_values": [1, 5],
            "min_bet": 1,
            "bankroll": {"cash": 200, "currency": "EUR", "session_profit": 0},
            "rules": {},
        }
    )


def _histories(rng: random.Random) -> list[list[int]]:
    base = [rng.randrange(38) for _ in range(20)]
    rotated = [((number + 3) % 37) for number in base]
    if rotated == base:
        rotated = [1, 2, 3]
    return [[], [0], [1, 3, 5, 7, 9], [2, 4, 6, 8, 10], base, rotated]


def test_roulette_orders_every_bet_type_and_ignores_history():
    assert BET_PREFERENCE == _BET_TYPES
    assert len(set(BET_PREFERENCE)) == 14
    policy = RiskPolicy(min_bet=1)
    rng = random.Random(0)
    histories = _histories(rng)
    for index, better in enumerate(_BET_TYPES):
        for worse in _BET_TYPES[index + 1 :]:
            for wheel in ("european", "american"):
                reasons = []
                sizes = []
                for history in histories:
                    advice = recommend(_roulette([worse, better], history, wheel), policy)
                    assert advice.action == better
                    reasons.append(advice.reason)
                    sizes.append(advice.size)
                assert len(set(reasons)) == 1
                assert len(set(sizes)) == 1
    for _ in range(200):
        count = rng.randint(1, len(_BET_TYPES))
        subset = rng.sample(list(_BET_TYPES), count)
        expected = next(name for name in _BET_TYPES if name in subset)
        left = rng.sample(range(38), rng.randint(0, 20))
        right = [((number + 5) % 37) for number in left] or [4, 5]
        if right == left:
            right = [7]
        first = recommend(_roulette(subset, left), policy)
        second = recommend(_roulette(subset, right), policy)
        assert first.action == second.action == expected
        assert first.reason == second.reason
        assert first.size == second.size
        assert "last" not in first.reason.lower() or "ignored" in first.reason.lower()
