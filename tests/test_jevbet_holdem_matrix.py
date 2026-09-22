"""All 169 Hold'em starting hands, plus one board for every postflop class.

Groups are the Sklansky–Malmuth table (groups 1–8 listed, group 9 = the rest).
The action oracle below duplicates the documented price thresholds so a cutoff
change fails this file. This is a complete preflop matrix, not a GTO solution.
"""

from __future__ import annotations

from jevbet.cards import Card
from jevbet.games.registry import load_game_state
from jevbet.policy import RiskPolicy
from jevbet.strategy import recommend
from jevbet.strategy.holdem import MAX_CONTINUE_PRICE, RAISE_PRICE
from jevbet.strategy.poker import (
    FRENCH_VALUE,
    all_starting_hands,
    french_deck,
    postflop_flags,
    preflop_group,
)

# Published hands. Anything absent is group 9.
_LISTED = {
    1: {"AA", "AKs", "KK", "QQ", "JJ"},
    2: {"AKo", "AQs", "AJs", "KQs", "TT"},
    3: {"AQo", "ATs", "KJs", "QJs", "JTs", "99"},
    4: {"AJo", "KQo", "KTs", "QTs", "J9s", "T9s", "98s", "88"},
    5: {
        "A9s",
        "A8s",
        "A7s",
        "A6s",
        "A5s",
        "A4s",
        "A3s",
        "A2s",
        "KJo",
        "QJo",
        "JTo",
        "Q9s",
        "T8s",
        "97s",
        "87s",
        "77",
        "76s",
        "66",
    },
    6: {"ATo", "KTo", "QTo", "J8s", "86s", "75s", "65s", "55", "54s"},
    7: {
        "K9s",
        "K8s",
        "K7s",
        "K6s",
        "K5s",
        "K4s",
        "K3s",
        "K2s",
        "J9o",
        "T9o",
        "98o",
        "64s",
        "53s",
        "44",
        "43s",
        "33",
        "22",
    },
    8: {
        "A9o",
        "K9o",
        "Q9o",
        "J8o",
        "J7s",
        "T8o",
        "96s",
        "87o",
        "85s",
        "76o",
        "74s",
        "65o",
        "54o",
        "42s",
        "32s",
    },
}
_GOLD = {hand: group for group, hands in _LISTED.items() for hand in hands}
_OPEN = {1, 2, 3, 4}
_LATE_OPEN = {5, 6}
# Duplicated thresholds. Must stay equal to the module constants.
_MAX = {1: 1.0, 2: 0.45, 3: 0.35, 4: 0.28, 5: 0.22, 6: 0.16, 7: 0.12, 8: 0.08, 9: 0.0}
_RAISE = {1: 0.40, 2: 0.25, 3: 0.15}


def _token(char: str) -> str:
    return "10" if char == "T" else char


def _hole(key: str) -> list[str]:
    if len(key) == 2:
        return [f"{_token(key[0])}S", f"{_token(key[1])}D"]
    high, low, flag = key[0], key[1], key[2]
    suit = "S" if flag == "s" else "D"
    return [f"{_token(high)}S", f"{_token(low)}{suit}"]


def _state(key: str, *, to_call: float, pot: float, position: str, legal: list[str]):
    return load_game_state(
        {
            "game": "holdem",
            "street": "preflop",
            "hole_cards": [Card.parse(card).model_dump() for card in _hole(key)],
            "community": [],
            "pot": pot,
            "to_call": to_call,
            "stack": 500,
            "position": position,
            "num_players": 6,
            "legal_actions": legal,
            "min_raise": 20,
            "raise_suggestions": [20, 40],
            "bankroll": {"cash": 2000, "session_profit": 0},
        }
    )


def _expected_group(key: str) -> int:
    return _GOLD.get(key, 9)


def _expected_action(group: int, *, to_call: float, pot: float, position: str) -> str:
    price = 0.0 if to_call <= 0 else to_call / (pot + to_call)
    if to_call <= 0:
        late = position == "BTN"
        if group in _OPEN or (group in _LATE_OPEN and late):
            return "raise"
        return "check"
    if group in _RAISE and price <= _RAISE[group]:
        return "raise"
    if price <= _MAX[group] + 1e-12:
        return "call"
    return "fold"


def test_documented_thresholds_match_the_module():
    assert MAX_CONTINUE_PRICE == _MAX
    assert RAISE_PRICE == _RAISE


def test_every_starting_hand_has_one_group():
    hands = all_starting_hands()
    assert len(hands) == 169
    assert len(set(hands)) == 169
    counts = {group: 0 for group in range(1, 10)}
    for key in hands:
        high = FRENCH_VALUE["10" if key[0] == "T" else key[0]]
        low = FRENCH_VALUE["10" if key[1] == "T" else key[1]]
        suited = len(key) == 3 and key[2] == "s"
        assert preflop_group((high, low), suited) == _expected_group(key)
        # Suited flag must not change a pair.
        if len(key) == 2:
            assert preflop_group((high, low), True) == preflop_group((high, low), False)
        counts[_expected_group(key)] += 1
    assert counts == {1: 5, 2: 5, 3: 6, 4: 8, 5: 18, 6: 9, 7: 17, 8: 15, 9: 86}
    assert sum(counts.values()) == 169


def test_every_starting_hand_has_a_deterministic_action_path():
    """Open, late open, a wide price, and a cheap price. All 169 hands."""
    spots = (
        ("open-utg", 0, 30, "UTG", ["check", "raise"]),
        ("open-btn", 0, 30, "BTN", ["check", "raise"]),
        ("wide", 50, 50, "UTG", ["fold", "call", "raise"]),
        ("cheap", 5, 95, "CO", ["fold", "call", "raise"]),
    )
    mismatches: list[str] = []
    policy = RiskPolicy(max_bet_fraction=0.05)
    for key in all_starting_hands():
        group = _expected_group(key)
        for name, to_call, pot, position, legal in spots:
            expected = _expected_action(group, to_call=to_call, pot=pot, position=position)
            action = recommend(
                _state(key, to_call=to_call, pot=pot, position=position, legal=legal),
                policy,
            ).action
            if action != expected:
                mismatches.append(f"{key} g{group} {name}: {action} != {expected}")
    assert mismatches == []


def _cards(labels: list[str]) -> list[tuple[int, str]]:
    return [(FRENCH_VALUE[card[:-1]], card[-1]) for card in labels]


def _flags(hole: list[str], board: list[str]) -> dict:
    return postflop_flags(_cards(hole), _cards(board), french_deck())


def test_postflop_flag_classes():
    overpair = _flags(["AH", "AD"], ["KS", "7C", "2D"])
    assert overpair["overpair"] and overpair["high_pair"]
    assert not overpair["top_pair"] and not overpair["set"] and not overpair["two_pair_plus"]

    top = _flags(["AH", "KD"], ["AS", "9C", "2D"])
    assert top["top_pair"] and top["high_pair"] and top["pair"]
    assert not top["overpair"] and not top["overcards"] and not top["set"]

    overcards = _flags(["AH", "KD"], ["9S", "7C", "2D"])
    assert overcards["overcards"]
    assert not overcards["pair"] and not overcards["oesd"] and not overcards["gutshot"]
    assert not overcards["flush_draw"] and not overcards["high_pair"]

    oesd = _flags(["9H", "8D"], ["7C", "6S", "2H"])
    assert oesd["oesd"] and not oesd["gutshot"] and not oesd["flush_draw"]

    gutshot = _flags(["JH", "9D"], ["QC", "8S", "2H"])
    assert gutshot["gutshot"] and not gutshot["oesd"] and not gutshot["overcards"]
    assert not gutshot["flush_draw"] and not gutshot["pair"]

    flush = _flags(["9H", "8H"], ["7H", "2H", "KC"])
    assert flush["flush_draw"] and not flush["oesd"] and not flush["gutshot"]
    assert not flush["overcards"] and not flush["pair"]

    two_pair = _flags(["AH", "KD"], ["AS", "KC", "2D"])
    assert two_pair["two_pair_plus"] and two_pair["kind"] == 2
    assert not two_pair["set"] and not two_pair["top_pair"] and not two_pair["nuts"]

    set_ = _flags(["8H", "8D"], ["8S", "KC", "KD"])
    assert set_["set"] and set_["two_pair_plus"] and set_["kind"] >= 3
    assert not set_["nuts"] and not set_["top_pair"]

    nuts = _flags(["AH", "KH"], ["QH", "JH", "10H", "2C", "3D"])
    assert nuts["nuts"] and nuts["two_pair_plus"]

    weak = _flags(["7H", "4D"], ["KS", "7C", "2D"])
    assert weak["pair"] and not weak["high_pair"] and not weak["two_pair_plus"]


def test_set_does_not_fold_when_a_draw_would():
    """A set is two pair or better, so a wide price is a call or a raise, not a fold."""
    state = load_game_state(
        {
            "game": "holdem",
            "street": "flop",
            "hole_cards": [Card.parse("8H").model_dump(), Card.parse("8D").model_dump()],
            "community": [Card.parse(card).model_dump() for card in ("8S", "KC", "KD")],
            "pot": 100,
            "to_call": 80,
            "stack": 500,
            "position": "BTN",
            "num_players": 2,
            "legal_actions": ["fold", "call", "raise"],
            "min_raise": 40,
            "raise_suggestions": [40, 80],
            "bankroll": {"cash": 2000, "session_profit": 0},
        }
    )
    advice = recommend(state, RiskPolicy(max_bet_fraction=0.2))
    assert advice.action in {"raise", "call"}
    assert advice.action != "fold"
    assert "set" in advice.reason
