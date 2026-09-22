"""Hi-Lo running count and true count.

Tags (standard Hi-Lo): 2–6 = +1, 7–9 = 0, 10/J/Q/K/A = −1.

True count = running_count / decks_remaining. Decks remaining are estimated
from ``cards_seen`` and ``rules.decks`` (52 cards per deck), or from an
explicit ``shoe_penetration`` / ``decks_remaining`` on the state when present.

Counting is meaningful only when the shoe is continuous and the table adapter
feeds every observed card (player + dealer + discards). An RNG that reshuffles
every hand resets the count; deviations then do nothing useful.
"""

from __future__ import annotations

from ..cards import Card

_TENS = frozenset({"10", "J", "Q", "K"})
_PLUS = frozenset({"2", "3", "4", "5", "6"})
_MINUS = frozenset({"10", "J", "Q", "K", "A"})


def hi_lo_tag(rank: str) -> int:
    if rank in _PLUS:
        return 1
    if rank in _MINUS:
        return -1
    return 0


def tag_card(card: Card | str) -> int:
    if isinstance(card, Card):
        return hi_lo_tag(card.rank)
    raw = str(card).strip().upper()
    if not raw:
        return 0
    rank = raw[:-1] if raw[-1] in "SHDC" and len(raw) > 1 else raw
    if rank == "T":
        rank = "10"
    return hi_lo_tag(rank)


def running_count(cards: list[Card | str]) -> int:
    return sum(tag_card(card) for card in cards)


def decks_remaining(
    *,
    decks: int,
    cards_seen: int | None = None,
    shoe_penetration: float | None = None,
    decks_remaining_hint: float | None = None,
) -> float:
    """Estimate unfinished decks in the shoe. Never returns below 0.25."""
    if decks_remaining_hint is not None and decks_remaining_hint > 0:
        return max(0.25, float(decks_remaining_hint))
    total = max(1, int(decks)) * 52
    if shoe_penetration is not None:
        left = total * (1.0 - float(shoe_penetration))
        return max(0.25, left / 52.0)
    seen = max(0, int(cards_seen or 0))
    left = max(0, total - seen)
    return max(0.25, left / 52.0)


def true_count(running: int, decks_left: float) -> float:
    if decks_left <= 0:
        return float(running)
    return float(running) / float(decks_left)


def counting_enabled(rules: dict) -> bool:
    raw = rules.get("counting", "off")
    if raw is True:
        return True
    if raw is False or raw is None:
        return False
    text = str(raw).strip().lower().replace("_", "-")
    return text in {"hi-lo", "hilo", "hi lo", "on", "true"}


def count_from_state(
    *,
    rules: dict,
    cards_seen: int | None,
    shoe_penetration: float | None,
    running: int | None,
    observed: list[Card | str] | None = None,
    decks_remaining_hint: float | None = None,
) -> tuple[int, float, float]:
    """Return ``(running, true_count, decks_remaining)``.

    Prefer an explicit ``running`` on the state; otherwise sum ``observed``.
    """
    decks = int(rules.get("decks") or 6)
    if observed:
        rc = running_count(observed)
    elif running is not None:
        rc = int(running)
    else:
        rc = 0
    left = decks_remaining(
        decks=decks,
        cards_seen=cards_seen,
        shoe_penetration=shoe_penetration,
        decks_remaining_hint=decks_remaining_hint,
    )
    return rc, true_count(rc, left), left
