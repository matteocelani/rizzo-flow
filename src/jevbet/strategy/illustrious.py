"""Illustrious 18 + Fab 4 Hi-Lo index deviations (Don Schlesinger).

Indices are for multi-deck Hi-Lo true count. When counting is enabled and the
true count is at or above the index, prefer the deviation action over the
basic-strategy cell — but only if that action is still legal for the hand.

Insurance is listed here for documentation; the insurance decision is handled
separately (take only when counting is on and TC ≥ +3).

Reference ranking (Wizard of Odds / Blackjack Attack). Independent encoding;
not affiliated with blackjacksimulator.net.
"""

from __future__ import annotations

from dataclasses import dataclass

# (hand_key, dealer_up, index, action_when_tc_ge_index)
ILLUSTRIOUS_18: tuple[tuple[str, str, int, str], ...] = (
    ("INS", "A", 3, "insurance"),
    ("H16", "10", 0, "stand"),
    ("H15", "10", 4, "stand"),
    ("P10", "5", 5, "split"),
    ("P10", "6", 4, "split"),
    ("H10", "10", 4, "double"),
    ("H12", "3", 2, "stand"),
    ("H12", "2", 3, "stand"),
    ("H11", "A", 1, "double"),
    ("H9", "2", 1, "double"),
    ("H10", "A", 4, "double"),
    ("H9", "7", 3, "double"),
    ("H16", "9", 5, "stand"),
    ("H13", "2", -1, "stand"),
    ("H12", "4", 0, "stand"),
    ("H12", "5", -2, "stand"),
    ("H12", "6", -1, "stand"),
    ("H13", "3", -2, "stand"),
)

# Late surrender Fab 4. Prefer surrender when TC ≥ index.
FAB_4: tuple[tuple[str, str, int, str], ...] = (
    ("H14", "10", 3, "surrender"),
    ("H15", "9", 2, "surrender"),
    ("H15", "10", 0, "surrender"),
    ("H15", "A", 1, "surrender"),
)

INSURANCE_INDEX = 3


@dataclass(frozen=True)
class IndexPlay:
    hand_key: str
    up: str
    index: int
    action: str
    family: str  # "illustrious18" | "fab4"


def _hand_keys(*, total: int, soft: bool, pair: str | None, n_cards: int) -> tuple[str, ...]:
    keys: list[str] = []
    if pair and n_cards == 2:
        keys.append(f"P{pair}")
    if soft:
        keys.append(f"S{total}")
    else:
        keys.append(f"H{total}")
    return tuple(keys)


def all_index_plays() -> tuple[IndexPlay, ...]:
    rows = [
        IndexPlay(hand, up, index, action, "illustrious18")
        for hand, up, index, action in ILLUSTRIOUS_18
        if hand != "INS"
    ]
    rows.extend(IndexPlay(hand, up, index, action, "fab4") for hand, up, index, action in FAB_4)
    return tuple(rows)


def deviation_for(
    *,
    total: int,
    soft: bool,
    pair: str | None,
    n_cards: int,
    up: str,
    true_count: float,
    surrender: bool,
) -> IndexPlay | None:
    """Matching Illustrious 18 / Fab 4 row for this spot.

    Prefer Illustrious stand/double/split when TC ≥ that index (e.g. 15 vs 10
    stands at +4 rather than Fab 4 surrender). Fab 4 applies when TC ≥ its
    surrender index and the Illustrious stand index is not yet reached.
    Below an Illustrious index the rule is hit.
    """
    keys = set(_hand_keys(total=total, soft=soft, pair=pair, n_cards=n_cards))
    if not keys:
        return None
    matched_i18: tuple[str, str, int, str] | None = None
    for hand, dealer, index, action in ILLUSTRIOUS_18:
        if hand == "INS":
            continue
        if hand in keys and dealer == up:
            matched_i18 = (hand, dealer, index, action)
            if true_count >= index:
                return IndexPlay(hand, dealer, index, action, "illustrious18")
            break
    if surrender:
        for hand, dealer, index, action in FAB_4:
            if hand in keys and dealer == up and true_count >= index:
                return IndexPlay(hand, dealer, index, action, "fab4")
    if matched_i18 is not None:
        hand, dealer, index, _action = matched_i18
        return IndexPlay(hand, dealer, index, "hit", "illustrious18")
    return None


def should_take_insurance(true_count: float, *, counting: bool) -> bool:
    """Illustrious #1. Without counting, EV ≈ −7%: always decline."""
    return bool(counting and true_count >= INSURANCE_INDEX)
