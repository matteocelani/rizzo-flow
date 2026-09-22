"""Every multi-deck basic-strategy cell, against published chart strings.

Hard 5–21, soft 13–21, and pairs A/2–10, each against dealer 2–A, for H17+DAS,
S17+DAS, H17 no-DAS, and S17 no-DAS. The strings below are the contract: if a
cell in ``jevbet.strategy.blackjack`` drifts, these tests fail. Actions come
from ``lookup`` / ``recommend_blackjack``, not from re-reading the module tables
alone.

Source of the H17+DAS strings: Blackjack Apprenticeship H17 chart (2024),
total-dependent 4–8 deck basic strategy. S17 and no-DAS strings are the full
tables after the published cell changes (not a runtime patch).
"""

from __future__ import annotations

import pytest

from jevbet.cards import Bankroll, Card
from jevbet.games.blackjack import BlackjackHand, BlackjackState
from jevbet.strategy.blackjack import (
    DEALER_UPCARDS,
    HARD_H17,
    HARD_S17,
    HARD_S17_1D,
    PAIRS_H17_DAS,
    PAIRS_H17_NDAS,
    PAIRS_S17_1D_DAS,
    PAIRS_S17_1D_NDAS,
    PAIRS_S17_DAS,
    PAIRS_S17_NDAS,
    SOFT_H17,
    SOFT_S17,
    SOFT_S17_1D,
    hand_facts,
    lookup,
    recommend_blackjack,
    validate_charts,
)

# Published tables. Kept in the test on purpose so a module edit cannot silently
# update the oracle.
GOLD_HARD_H17 = {
    5: "HHHHHHHHHH",
    6: "HHHHHHHHHH",
    7: "HHHHHHHHHH",
    8: "HHHHHHHHHH",
    9: "HDDDDHHHHH",
    10: "DDDDDDDDHH",
    11: "DDDDDDDDDD",
    12: "HHSSSHHHHH",
    13: "SSSSSHHHHH",
    14: "SSSSSHHHHH",
    15: "SSSSSHHHRR",
    16: "SSSSSHHRRR",
    17: "SSSSSSSSSW",
    18: "SSSSSSSSSS",
    19: "SSSSSSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
# blackjacksimulator.net multi-deck S17 ("più mazzi")
GOLD_HARD_S17 = {
    5: "HHHHHHHHHH",
    6: "HHHHHHHHHH",
    7: "HHHHHHHHHH",
    8: "HHHHHHHHHH",
    9: "HDDDDHHHHH",
    10: "DDDDDDDDHH",
    11: "DDDDDDDDDH",
    12: "HHSSSHHHHH",
    13: "SSSSSHHHHH",
    14: "SSSSSHHHHH",
    15: "SSSSSHHHRH",
    16: "SSSSSHHRRR",
    17: "SSSSSSSSSS",
    18: "SSSSSSSSSS",
    19: "SSSSSSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
GOLD_SOFT_H17 = {
    13: "HHHDDHHHHH",
    14: "HHHDDHHHHH",
    15: "HHDDDHHHHH",
    16: "HHDDDHHHHH",
    17: "HDDDDHHHHH",
    18: "UUUUUSSHHH",
    19: "SSSSUSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
GOLD_SOFT_S17 = {
    13: "HHHDDHHHHH",
    14: "HHHDDHHHHH",
    15: "HHDDDHHHHH",
    16: "HHDDDHHHHH",
    17: "HDDDDHHHHH",
    18: "SUUUUSSHHH",
    19: "SSSSSSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
GOLD_PAIRS_H17_DAS = {
    "A": "YYYYYYYYYY",
    "10": "SSSSSSSSSS",
    "9": "YYYYYSYYSS",
    "8": "YYYYYYYYYZ",
    "7": "YYYYYY....",
    "6": "YYYYY.....",
    "5": "..........",
    "4": "...YY.....",
    "3": "YYYYYY....",
    "2": "YYYYYY....",
}
GOLD_PAIRS_S17_DAS = {
    "A": "YYYYYYYYYY",
    "10": "SSSSSSSSSS",
    "9": "YYYYYSYYSS",
    "8": "YYYYYYYYYY",
    "7": "YYYYYY....",
    "6": ".YYYY.....",
    "5": "..........",
    "4": "..........",
    "3": "..YYYY....",
    "2": "..YYYY....",
}
GOLD_PAIRS_H17_NDAS = {
    **GOLD_PAIRS_H17_DAS,
    "6": ".YYYY.....",
    "4": "..........",
    "3": "..YYYY....",
    "2": "..YYYY....",
}
GOLD_PAIRS_S17_NDAS = dict(GOLD_PAIRS_S17_DAS)

# blackjacksimulator.net single-deck S17 ("un mazzo")
GOLD_HARD_S17_1D = {
    5: "HHHHHHHHHH",
    6: "HHHHHHHHHH",
    7: "HHHHHHHHHH",
    8: "HHHDDHHHHH",
    9: "DDDDDHHHHH",
    10: "DDDDDDDDHH",
    11: "DDDDDDDDDD",
    12: "HHSSSHHHHH",
    13: "SSSSSHHHHH",
    14: "SSSSSHHHHH",
    15: "SSSSSHHHHH",
    16: "SSSSSHHHRR",
    17: "SSSSSSSSSS",
    18: "SSSSSSSSSS",
    19: "SSSSSSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
GOLD_SOFT_S17_1D = {
    13: "HHHDDHHHHH",
    14: "HHHDDHHHHH",
    15: "HHDDDHHHHH",
    16: "HHDDDHHHHH",
    17: "DDDDDHHHHH",
    18: "SUUUUSSHHS",
    19: "SSSSUSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
GOLD_PAIRS_S17_1D_DAS = {
    "A": "YYYYYYYYYY",
    "10": "SSSSSSSSSS",
    "9": "YYYYYSYYSS",
    "8": "YYYYYYYYYY",
    "7": "YYYYYYHHWH",
    "6": "YYYYY.....",
    "5": "..........",
    "4": "..........",
    "3": "HHYYYY....",
    "2": "HYYYYY....",
}
GOLD_PAIRS_S17_1D_NDAS = {
    **GOLD_PAIRS_S17_1D_DAS,
    "6": ".YYYY.....",
}

_CODE = {
    "H": ("hit",),
    "S": ("stand",),
    "D": ("double", "hit"),
    "U": ("double", "stand"),
    "R": ("surrender", "hit"),
    "W": ("surrender", "stand"),
    "Y": ("split",),
    "Z": ("surrender", "split"),
}
_TWO_CARD = frozenset({"double", "split", "surrender", "insurance"})
_FALLBACK = {"H": "hit", "S": "stand", "D": "hit", "U": "stand", "R": "hit", "W": "stand"}
_UPS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "A")
_LEGAL = ["hit", "stand", "double", "split", "surrender", "insurance"]

# (name, h17, das, hard, soft, pairs)
_VARIANTS = (
    ("H17+DAS", True, True, GOLD_HARD_H17, GOLD_SOFT_H17, GOLD_PAIRS_H17_DAS),
    ("S17+DAS", False, True, GOLD_HARD_S17, GOLD_SOFT_S17, GOLD_PAIRS_S17_DAS),
    ("H17+no-DAS", True, False, GOLD_HARD_H17, GOLD_SOFT_H17, GOLD_PAIRS_H17_NDAS),
    ("S17+no-DAS", False, False, GOLD_HARD_S17, GOLD_SOFT_S17, GOLD_PAIRS_S17_NDAS),
)


def _expand(code: str, *, surrender: bool) -> tuple[str, ...]:
    actions = _CODE[code]
    if surrender:
        return actions
    return tuple(action for action in actions if action != "surrender")


def _total_code(total: int, soft: bool, up: str, hard: dict, soft_table: dict) -> str:
    column = _UPS.index(up)
    if total > 21:
        return "S"
    if soft:
        if total not in soft_table:
            return "H" if total < 13 else "S"
        return soft_table[total][column]
    if total not in hard:
        return "H" if total < 5 else "S"
    return hard[total][column]


def _expected_prefs(
    *,
    total: int,
    soft: bool,
    pair: str | None,
    n_cards: int,
    up: str,
    hard: dict,
    soft_table: dict,
    pairs: dict,
    surrender: bool,
) -> tuple[str, ...]:
    prefs: list[str] = []
    if pair and n_cards == 2:
        code = pairs[pair][_UPS.index(up)]
        if code != ".":
            prefs.extend(_expand(code, surrender=surrender))
    for action in _expand(_total_code(total, soft, up, hard, soft_table), surrender=surrender):
        if action not in prefs:
            prefs.append(action)
    if n_cards != 2:
        prefs = [action for action in prefs if action not in _TWO_CARD]
    return tuple(prefs)


def _token(rank: int) -> str:
    if rank == 10:
        return "10"
    return str(rank)


def _hard_cards(total: int) -> list[str]:
    """Non-pair hard cards. Two cards when a non-pair exists, else three."""
    for low in range(2, 11):
        high = total - low
        if low < high <= 10:
            return [f"{_token(high)}H", f"{_token(low)}D"]
    for left in range(2, 11):
        for mid in range(left, 11):
            right = total - left - mid
            if mid <= right <= 10:
                return [f"{_token(left)}H", f"{_token(mid)}D", f"{_token(right)}C"]
    raise AssertionError(f"no hard cards for {total}")


def _hard_three(total: int) -> list[str] | None:
    for left in range(2, 11):
        for mid in range(left, 11):
            right = total - left - mid
            if mid <= right <= 10:
                return [f"{_token(left)}H", f"{_token(mid)}D", f"{_token(right)}C"]
    return None


def _soft_cards(total: int) -> list[str]:
    return ["AH", f"{_token(total - 11)}D"]


def _soft_three(total: int) -> list[str]:
    kick = total - 12
    if kick == 1:
        return ["AH", "AD", "AC"]
    return ["AH", "AD", f"{_token(kick)}C"]


def _pair_cards(rank: str) -> list[str]:
    token = "10" if rank == "10" else rank
    return [f"{token}H", f"{token}D"]


def _dealer(up: str) -> str:
    return "10S" if up == "10" else f"{up}S"


def _rules(*, h17: bool, das: bool, surrender: bool | str = "late") -> dict:
    return {
        "decks": 6,
        "dealer_hits_soft_17": h17,
        "das": das,
        "surrender": surrender,
    }


def _state(cards: list[str], up: str, rules: dict) -> BlackjackState:
    return BlackjackState(
        dealer_upcard=Card.parse(_dealer(up)),
        hands=[BlackjackHand(cards=[Card.parse(card) for card in cards], bet=10.0)],
        legal_actions=list(_LEGAL),
        bankroll=Bankroll(cash=400),
        rules=rules,
    )


def test_chart_strings_are_complete_at_import():
    validate_charts()
    assert DEALER_UPCARDS == _UPS
    tables = {
        "HARD_H17": (HARD_H17, GOLD_HARD_H17, list(range(5, 22))),
        "HARD_S17": (HARD_S17, GOLD_HARD_S17, list(range(5, 22))),
        "HARD_S17_1D": (HARD_S17_1D, GOLD_HARD_S17_1D, list(range(5, 22))),
        "SOFT_H17": (SOFT_H17, GOLD_SOFT_H17, list(range(13, 22))),
        "SOFT_S17": (SOFT_S17, GOLD_SOFT_S17, list(range(13, 22))),
        "SOFT_S17_1D": (SOFT_S17_1D, GOLD_SOFT_S17_1D, list(range(13, 22))),
        "PAIRS_H17_DAS": (PAIRS_H17_DAS, GOLD_PAIRS_H17_DAS, list(GOLD_PAIRS_H17_DAS)),
        "PAIRS_S17_DAS": (PAIRS_S17_DAS, GOLD_PAIRS_S17_DAS, list(GOLD_PAIRS_S17_DAS)),
        "PAIRS_H17_NDAS": (PAIRS_H17_NDAS, GOLD_PAIRS_H17_NDAS, list(GOLD_PAIRS_H17_NDAS)),
        "PAIRS_S17_NDAS": (PAIRS_S17_NDAS, GOLD_PAIRS_S17_NDAS, list(GOLD_PAIRS_S17_NDAS)),
        "PAIRS_S17_1D_DAS": (
            PAIRS_S17_1D_DAS,
            GOLD_PAIRS_S17_1D_DAS,
            list(GOLD_PAIRS_S17_1D_DAS),
        ),
        "PAIRS_S17_1D_NDAS": (
            PAIRS_S17_1D_NDAS,
            GOLD_PAIRS_S17_1D_NDAS,
            list(GOLD_PAIRS_S17_1D_NDAS),
        ),
    }
    for name, (module, gold, keys) in tables.items():
        assert list(module) == keys, name
        assert module == gold, name
        for key, row in module.items():
            assert len(row) == 10, f"{name}[{key}]"
            assert len(gold[key]) == 10


def test_single_deck_s17_matrix_covers_every_cell():
    """360 cells for the blackjacksimulator.net single-deck S17 table."""
    mismatches: list[str] = []
    seen = 0
    rules = {
        "decks": 1,
        "dealer_hits_soft_17": False,
        "das": True,
        "surrender": "late",
    }
    hard, soft, pairs = GOLD_HARD_S17_1D, GOLD_SOFT_S17_1D, GOLD_PAIRS_S17_1D_DAS
    for total in range(5, 22):
        cards = _hard_cards(total)
        for up in _UPS:
            seen += 1
            _check(
                mismatches,
                label=f"1D S17 hard {total} vs {up}",
                cards=cards,
                up=up,
                rules=rules,
                hard=hard,
                soft=soft,
                pairs=pairs,
                surrender=True,
            )
    for total in range(13, 22):
        cards = _soft_cards(total)
        for up in _UPS:
            seen += 1
            _check(
                mismatches,
                label=f"1D S17 soft {total} vs {up}",
                cards=cards,
                up=up,
                rules=rules,
                hard=hard,
                soft=soft,
                pairs=pairs,
                surrender=True,
            )
    for rank in ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10"):
        cards = _pair_cards(rank)
        for up in _UPS:
            seen += 1
            _check(
                mismatches,
                label=f"1D S17 pair {rank} vs {up}",
                cards=cards,
                up=up,
                rules=rules,
                hard=hard,
                soft=soft,
                pairs=pairs,
                surrender=True,
            )
    assert seen == 360
    assert mismatches == []


def test_matrix_covers_every_cell_for_every_ruleset():
    """170 hard + 90 soft + 100 pair = 360 cells, times 4 rule tables."""
    mismatches: list[str] = []
    seen = 0
    for name, h17, das, hard, soft, pairs in _VARIANTS:
        rules = _rules(h17=h17, das=das)
        for total in range(5, 22):
            cards = _hard_cards(total)
            for up in _UPS:
                seen += 1
                _check(
                    mismatches,
                    label=f"{name} hard {total} vs {up}",
                    cards=cards,
                    up=up,
                    rules=rules,
                    hard=hard,
                    soft=soft,
                    pairs=pairs,
                    surrender=True,
                )
        for total in range(13, 22):
            cards = _soft_cards(total)
            for up in _UPS:
                seen += 1
                _check(
                    mismatches,
                    label=f"{name} soft {total} vs {up}",
                    cards=cards,
                    up=up,
                    rules=rules,
                    hard=hard,
                    soft=soft,
                    pairs=pairs,
                    surrender=True,
                )
        for rank in ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10"):
            cards = _pair_cards(rank)
            for up in _UPS:
                seen += 1
                _check(
                    mismatches,
                    label=f"{name} pair {rank} vs {up}",
                    cards=cards,
                    up=up,
                    rules=rules,
                    hard=hard,
                    soft=soft,
                    pairs=pairs,
                    surrender=True,
                )
    assert seen == 360 * 4
    assert mismatches == []


def test_surrender_off_uses_the_fallback_on_every_h17_cell():
    mismatches: list[str] = []
    rules = _rules(h17=True, das=True, surrender=False)
    for total in range(5, 22):
        cards = _hard_cards(total)
        for up in _UPS:
            _check(
                mismatches,
                label=f"no-surrender hard {total} vs {up}",
                cards=cards,
                up=up,
                rules=rules,
                hard=GOLD_HARD_H17,
                soft=GOLD_SOFT_H17,
                pairs=GOLD_PAIRS_H17_DAS,
                surrender=False,
            )
    for total in range(13, 22):
        cards = _soft_cards(total)
        for up in _UPS:
            _check(
                mismatches,
                label=f"no-surrender soft {total} vs {up}",
                cards=cards,
                up=up,
                rules=rules,
                hard=GOLD_HARD_H17,
                soft=GOLD_SOFT_H17,
                pairs=GOLD_PAIRS_H17_DAS,
                surrender=False,
            )
    for rank in ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10"):
        cards = _pair_cards(rank)
        for up in _UPS:
            _check(
                mismatches,
                label=f"no-surrender pair {rank} vs {up}",
                cards=cards,
                up=up,
                rules=rules,
                hard=GOLD_HARD_H17,
                soft=GOLD_SOFT_H17,
                pairs=GOLD_PAIRS_H17_DAS,
                surrender=False,
            )
    assert mismatches == []


def test_three_card_hands_never_double_split_or_surrender():
    """Shape gate: D/U/R/W become the non-two-card fallback, including soft 18 vs 6."""
    mismatches: list[str] = []
    for name, h17, das, hard, soft, _pairs in _VARIANTS:
        rules = _rules(h17=h17, das=das)
        for total in range(6, 22):
            cards = _hard_three(total)
            assert cards is not None
            for up in _UPS:
                code = hard[total][_UPS.index(up)]
                _check_shape(
                    mismatches,
                    label=f"{name} 3-card hard {total} vs {up}",
                    cards=cards,
                    up=up,
                    rules=rules,
                    code=code,
                )
        for total in range(13, 22):
            cards = _soft_three(total)
            for up in _UPS:
                code = soft[total][_UPS.index(up)]
                _check_shape(
                    mismatches,
                    label=f"{name} 3-card soft {total} vs {up}",
                    cards=cards,
                    up=up,
                    rules=rules,
                    code=code,
                )
    assert mismatches == []


def test_three_card_soft_18_vs_6_stands_even_if_double_is_listed():
    rules = _rules(h17=True, das=True)
    state = _state(["AS", "2D", "5C"], "6", rules)
    facts = hand_facts(state.hands[0].cards)
    assert facts.total == 18 and facts.soft and facts.n_cards == 3 and facts.pair is None
    assert lookup(facts, "6", rules) == ("stand",)
    advice = recommend_blackjack(state)
    assert advice.action == "stand"
    assert advice.action != "double"
    assert "need exactly 2 cards" in advice.reason


@pytest.mark.parametrize("up", _UPS)
def test_natural_hard_20_and_hard_21_stand(up: str):
    rules = _rules(h17=True, das=True)
    natural = _state(["AS", "KD"], up, rules)
    assert hand_facts(natural.hands[0].cards).total == 21
    assert recommend_blackjack(natural).action == "stand"
    hard_20 = _state(["10H", "8D", "2C"], up, rules)
    assert hand_facts(hard_20.hands[0].cards).total == 20
    assert not hand_facts(hard_20.hands[0].cards).soft
    assert recommend_blackjack(hard_20).action == "stand"
    hard_21 = _state(["9H", "8D", "4C"], up, rules)
    assert hand_facts(hard_21.hands[0].cards).total == 21
    assert not hand_facts(hard_21.hands[0].cards).soft
    assert recommend_blackjack(hard_21).action == "stand"


def test_ten_value_upcards_share_the_ten_column_and_jack_queen_are_tens():
    rules = _rules(h17=True, das=True)
    sixteen = ["10H", "6D"]
    actions = [
        recommend_blackjack(
            BlackjackState(
                dealer_upcard=Card.parse(up),
                hands=[BlackjackHand(cards=[Card.parse(c) for c in sixteen], bet=10.0)],
                legal_actions=list(_LEGAL),
                bankroll=Bankroll(cash=400),
                rules=rules,
            )
        ).action
        for up in ("10S", "JH", "QD", "KC")
    ]
    assert actions == ["surrender", "surrender", "surrender", "surrender"]
    tens = _state(["JH", "QD"], "6", rules)
    facts = hand_facts(tens.hands[0].cards)
    assert facts.pair == "10" and facts.total == 20
    assert recommend_blackjack(tens).action == "stand"


def test_insurance_is_never_the_chart_action():
    rules = _rules(h17=True, das=True)
    for cards in (["AS", "KD"], ["10H", "6D"], ["AS", "2D", "5C"], ["8H", "8D"]):
        advice = recommend_blackjack(_state(cards, "A", rules))
        assert advice.action != "insurance"
        assert "insurance declined" in advice.reason


def _check(
    mismatches: list[str],
    *,
    label: str,
    cards: list[str],
    up: str,
    rules: dict,
    hard: dict,
    soft: dict,
    pairs: dict,
    surrender: bool,
) -> None:
    state = _state(cards, up, rules)
    facts = hand_facts(state.hands[0].cards)
    expected = _expected_prefs(
        total=facts.total,
        soft=facts.soft,
        pair=facts.pair,
        n_cards=facts.n_cards,
        up=up,
        hard=hard,
        soft_table=soft,
        pairs=pairs,
        surrender=surrender,
    )
    got = lookup(facts, up, dict(state.rules))
    action = recommend_blackjack(state).action
    if got != expected or action != expected[0] or action in _TWO_CARD and facts.n_cards != 2:
        mismatches.append(f"{label}: lookup {got} recommend {action} expected {expected}")


def _check_shape(
    mismatches: list[str],
    *,
    label: str,
    cards: list[str],
    up: str,
    rules: dict,
    code: str,
) -> None:
    state = _state(cards, up, rules)
    facts = hand_facts(state.hands[0].cards)
    assert facts.n_cards == 3 and facts.pair is None, label
    action = recommend_blackjack(state).action
    expected = _FALLBACK[code]
    if action != expected or action in _TWO_CARD:
        mismatches.append(f"{label}: {action} expected {expected} (chart {code})")
