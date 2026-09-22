"""Lifecycle, Hi-Lo / Illustrious 18, and bet sizing. No model weights."""

from __future__ import annotations

import pytest

from jevbet.browser.casino import MockCasinoTable
from jevbet.cards import Bankroll, Card
from jevbet.games.blackjack import BlackjackHand, BlackjackState, derive_capabilities
from jevbet.games.registry import load_game_state
from jevbet.play import run_play_loop
from jevbet.policy import RiskPolicy
from jevbet.strategy.betting import recommend_bet
from jevbet.strategy.blackjack import recommend_blackjack
from jevbet.strategy.count import hi_lo_tag, running_count, true_count
from jevbet.strategy.illustrious import (
    FAB_4,
    ILLUSTRIOUS_18,
    all_index_plays,
    should_take_insurance,
)


def _state(**kwargs):
    base = {
        "game": "blackjack",
        "dealer_upcard": Card.parse("KS").model_dump(),
        "hands": [
            {
                "cards": [Card.parse("8H").model_dump(), Card.parse("8D").model_dump()],
                "bet": 10,
            }
        ],
        "active_hand": 0,
        "legal_actions": ["hit", "stand", "split"],
        "bankroll": {"cash": 400, "session_profit": 0},
        "rules": {
            "decks": 6,
            "dealer_hits_soft_17": False,
            "das": True,
            "counting": "off",
        },
    }
    base.update(kwargs)
    return load_game_state(base)


def test_hi_lo_tags_and_true_count():
    assert hi_lo_tag("2") == 1 and hi_lo_tag("6") == 1
    assert hi_lo_tag("7") == 0 and hi_lo_tag("9") == 0
    assert hi_lo_tag("10") == -1 and hi_lo_tag("A") == -1
    assert running_count(["2S", "KH", "7D"]) == 0
    assert true_count(6, 2.0) == pytest.approx(3.0)


def test_insurance_declined_at_tc_0_taken_at_tc_3():
    assert should_take_insurance(0.0, counting=True) is False
    assert should_take_insurance(2.99, counting=True) is False
    assert should_take_insurance(3.0, counting=True) is True
    assert should_take_insurance(10.0, counting=False) is False

    decline = _state(
        dealer_upcard=Card.parse("AS").model_dump(),
        hands=[
            {
                "cards": [Card.parse("KH").model_dump(), Card.parse("QD").model_dump()],
                "bet": 10,
            }
        ],
        legal_actions=["insurance", "decline"],
        phase="insurance",
        rules={
            "decks": 6,
            "dealer_hits_soft_17": False,
            "counting": "hi-lo",
            "das": True,
        },
        true_count=0.0,
        running_count=0,
        can_insurance=True,
    )
    assert recommend_blackjack(decline).action == "decline"
    take = decline.model_copy(update={"true_count": 3.0})
    assert recommend_blackjack(take).action == "insurance"


@pytest.mark.parametrize(
    "hand,up,index,action",
    [(h, u, i, a) for h, u, i, a in ILLUSTRIOUS_18 if h != "INS"],
)
def test_illustrious_18_threshold(hand, up, index, action):
    """At/above index → listed action; just below → hit (Illustrious rule)."""
    if hand.startswith("P"):
        rank = hand[1:]
        token = "10" if rank == "10" else rank
        cards = [f"{token}H", f"{token}D"]
    else:
        total = int(hand[1:])
        if hand.startswith("S"):
            cards = ["AH", f"{total - 11}D"]
        elif total == 16:
            cards = ["10H", "6D"]
        elif total == 15:
            cards = ["10H", "5D"]
        elif total == 13:
            cards = ["10H", "3D"]
        elif total == 12:
            cards = ["10H", "2D"]
        elif total == 11:
            cards = ["9H", "2D"]
        elif total == 10:
            cards = ["5H", "5D"]
        elif total == 9:
            cards = ["4H", "5D"]
        else:
            raise AssertionError(hand)
    legal = ["hit", "stand", "double", "split", "surrender"]
    above = _bj_count(cards, up, legal, true_count=float(index))
    below = _bj_count(cards, up, legal, true_count=index - 0.01)
    assert recommend_blackjack(above).action == action
    below_action = recommend_blackjack(below).action
    # Below the index the Illustrious rule is hit (may still match basic).
    if action != "hit":
        assert below_action == "hit" or "illustrious18" not in recommend_blackjack(below).reason
    assert recommend_blackjack(below).action in legal


@pytest.mark.parametrize("hand,up,index,action", list(FAB_4))
def test_fab4_surrender_threshold(hand, up, index, action):
    total = int(hand[1:])
    if total == 14:
        cards = ["9H", "5D"]
    else:
        cards = ["10H", "5D"]
    legal = ["hit", "stand", "surrender"]
    above = _bj_count(cards, up, legal, true_count=float(index))
    advice = recommend_blackjack(above)
    assert advice.action == "surrender"
    # When basic strategy already surrenders (15 vs 10 on the S17 multi chart),
    # the published action matches without an override note.
    if hand == "H15" and up == "10":
        assert advice.action == "surrender"
    else:
        assert "fab4" in advice.reason


def _bj_count(cards, up, legal, *, true_count):
    dealer = "10S" if up == "10" else f"{up}S"
    return load_game_state(
        {
            "game": "blackjack",
            "dealer_upcard": Card.parse(dealer).model_dump(),
            "hands": [
                {
                    "cards": [Card.parse(c).model_dump() for c in cards],
                    "bet": 10,
                }
            ],
            "legal_actions": legal,
            "bankroll": {"cash": 500, "session_profit": 0},
            "rules": {
                "decks": 6,
                "dealer_hits_soft_17": False,
                "das": True,
                "surrender": "late",
                "counting": "hi-lo",
            },
            "true_count": true_count,
            "running_count": int(true_count * 3),
            "cards_seen": 100,
        }
    )


def test_counting_off_keeps_basic_chart():
    state = _bj_count(["10H", "6D"], "10", ["hit", "stand", "surrender"], true_count=5.0)
    off = state.model_copy(update={"rules": {**dict(state.rules), "counting": "off"}})
    # H17 would surrender 16 vs 10; S17 multi also surrenders (R). Counting off.
    assert recommend_blackjack(off).action == "surrender"
    assert "illustrious" not in recommend_blackjack(off).reason


def test_split_eights_then_play_both_hands():
    table = MockCasinoTable("blackjack", seed=1, cash=200, base_bet=10)
    table.phase = "between"
    table._shoe = ["9H", "5D", "2C", "7S", "8D", "8S"]
    # Deal order: player, player, dealer up, dealer hole — then split draws.
    table._shoe = ["4C", "9D", "KS", "2H", "8D", "8S"]
    # Actually deal pops from end: last two are player cards.
    table._shoe = ["9C", "5D", "KS", "2H", "8D", "8S"]
    state = table.read_state()
    assert [c["rank"] for c in state["hands"][0]["cards"]] == ["8", "8"]
    table.act("split")
    assert len(table.hands) == 2
    assert table.active == 0
    table.act("stand")
    assert table.active == 1
    table.act("stand")
    assert table.phase == "between"


def test_split_aces_one_card_each_no_further_hit():
    table = MockCasinoTable(
        "blackjack",
        seed=1,
        cash=200,
        base_bet=10,
        rules={"hit_split_aces": False, "resplit_aces": False},
    )
    table.phase = "between"
    # player AS AD, dealer 6, hole 9; split draws 10, 9
    table._shoe = ["9C", "10H", "9D", "6S", "AD", "AS"]
    table.read_state()
    assert "split" in table.legal_actions()
    table.act("split")
    assert len(table.hands) == 2
    assert all(len(hand) == 2 for hand in table.hands)
    assert table.phase == "between"  # auto-finished both split-ace hands


def test_no_double_after_three_cards():
    state = BlackjackState(
        dealer_upcard=Card.parse("6S"),
        hands=[
            BlackjackHand(
                cards=[Card.parse("AS"), Card.parse("2D"), Card.parse("5C")],
                bet=10,
            )
        ],
        legal_actions=["hit", "stand", "double"],
        bankroll=Bankroll(cash=400),
        rules={"decks": 6, "dealer_hits_soft_17": True, "das": True},
    )
    caps = derive_capabilities(state)
    assert caps["can_double"] is False
    advice = recommend_blackjack(state)
    assert advice.action == "stand"
    assert advice.action != "double"


def test_resplit_limit_max_four_hands():
    table = MockCasinoTable(
        "blackjack",
        seed=2,
        cash=500,
        base_bet=10,
        rules={"resplit": 4, "das": True},
    )
    table.phase = "between"
    # Force pair of 8s and keep drawing 8s on splits.
    table._shoe = ["2C"] * 4 + ["8H", "8D", "8C", "8S", "8H", "8D", "KS", "9D", "8C", "8S"]
    # Simpler: manually set hands after deal.
    table.read_state()
    table.hands = [["8H", "8D"]]
    table.bets = [10.0]
    table.from_split = [False]
    table.split_aces = [False]
    table.doubled = [False]
    table.dealer = ["KS", "9D"]
    table.phase = "playing"
    table.active = 0
    table.cash = 500
    while "split" in table.legal_actions() and len(table.hands) < 4:
        # Ensure next draw keeps a pair opportunity when possible.
        table._shoe.append("8S")
        table._shoe.append("8C")
        table.act("split")
    assert len(table.hands) == 4
    assert "split" not in table.legal_actions()


def test_bet_flat_ignores_true_count_stop_loss_zero_ramp_grows():
    bankroll = Bankroll(cash=1000, session_profit=0)
    policy = RiskPolicy(max_bet_fraction=0.5, min_bet=10)
    flat = recommend_bet(
        bankroll, true_count=8, rules={"bet_system": "flat", "bet_unit": 10}, policy=policy
    )
    assert flat.amount == 10
    stopped = Bankroll(cash=1000, session_profit=-80, stop_loss=50)
    assert (
        recommend_bet(stopped, true_count=5, rules={"bet_system": "ramp"}, policy=policy).amount
        == 0
    )
    ramp_low = recommend_bet(
        bankroll, true_count=0, rules={"bet_system": "ramp", "bet_unit": 10}, policy=policy
    )
    ramp_high = recommend_bet(
        bankroll, true_count=6, rules={"bet_system": "ramp", "bet_unit": 10}, policy=policy
    )
    assert ramp_low.amount == 10
    assert ramp_high.amount > ramp_low.amount


def test_martingale_and_kelly_exist_with_honest_reason():
    bankroll = Bankroll(cash=1000, session_profit=0)
    policy = RiskPolicy(max_bet_fraction=0.5, min_bet=10)
    mart = recommend_bet(
        bankroll,
        rules={"bet_system": "martingale", "bet_unit": 10},
        policy=policy,
        last_result="loss",
        step=1,
    )
    assert mart.amount == 40
    assert "house edge" in mart.reason
    kelly = recommend_bet(
        bankroll,
        true_count=5,
        rules={"bet_system": "kelly", "bet_unit": 10, "kelly_fraction": 0.25},
        policy=policy,
    )
    assert kelly.amount >= 10


def test_play_loop_handles_insurance_and_strategy_only():
    table = MockCasinoTable(
        "blackjack",
        seed=7,
        cash=500,
        rules={"counting": "hi-lo", "bet_system": "flat"},
    )
    outcome = run_play_loop(
        table,
        game="blackjack",
        rounds=5,
        policy=RiskPolicy(),
        decide=None,
        advisor="strategy_only",
    )
    assert outcome["hands"]
    assert all(row["decision_source"] == "strategy" for row in outcome["hands"])
    actions = {row["choice"] for row in outcome["hands"]}
    assert actions <= {"hit", "stand", "double", "split", "surrender", "insurance", "decline"}


def test_all_index_plays_enumerated():
    plays = all_index_plays()
    assert len(plays) == 17 + 4  # I18 without insurance + Fab 4
