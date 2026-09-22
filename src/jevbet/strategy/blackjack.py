"""Multi-deck blackjack basic strategy.

Default chart: 4–8 decks, dealer hits soft 17 (H17), double after split (DAS),
late surrender when that action is legal. Source: Blackjack Apprenticeship H17
basic-strategy chart (2024 PDF) plus their published hard-total phrases
("11 always doubles" on H17). Cells are **total-dependent multi-deck** plays,
not composition-dependent indices and not a card-counting chart.

``HARD_H17`` / ``SOFT_H17`` / ``PAIRS_H17_DAS`` are that chart in full, including
the hard totals that are always hit (5–8) or always stand (18–21) and soft 21.
S17 and no-DAS are complete strings too (``HARD_S17``, ``SOFT_S17``,
``PAIRS_S17_DAS``, ``PAIRS_H17_NDAS``, ``PAIRS_S17_NDAS``), not a patch applied
at lookup time. The only cells that differ from H17+DAS are the published ones:

S17 (``dealer_hits_soft_17`` false, or ``dealer_stands_soft_17`` true):

- hard 11 vs A → hit, not double
- soft 18 (A,7) vs 2 → stand, not double
- soft 19 (A,8) vs 6 → stand, not double
- hard 15 vs A → hit, not surrender
- hard 17 vs A → stand, not surrender
- pair of 8s vs A → split, not surrender

No DAS (``das`` false): 2,2 and 3,3 vs 2–3 hit; 4,4 vs 5–6 hit; 6,6 vs 2 hit.
Hard and soft totals do not change with DAS; only the pair tables do.

``surrender`` false skips surrender cells even if the table listed the action.
Missing ``surrender`` means "use it when it is legal".

Shape gate: ``double``, ``split``, ``surrender``, and ``insurance`` are offered
only from a two-card hand. ``split`` is offered only when ``facts.pair`` is set
and the pair chart's cell is split or surrender-else-split. A 3-card soft 18
vs 6 is ``U`` (double else stand) with double removed, so the action is stand
even if the caller still lists ``double``.

Not applied (documented, still the multi-deck chart): 1- and 2-deck cell
changes, European no-hole-card, early surrender, 6:5 payout (the chart does
not get the edge back). Insurance is never taken.

Soft 18 vs 9 is a hit on this H17 chart (and on the S17 chart too). Soft 19
vs 6 is double-else-stand (``U`` on the dealer-6 column: ``SSSSUSSSSS``).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..cards import Card
from ..games.blackjack import BlackjackState, actions_after_policy
from ..policy import RiskPolicy
from .advice import StrategyAdvice

# Column order of every chart string. Length is always 10.
DEALER_UPCARDS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "A")

# One character per dealer upcard, left to right 2…A.
# H hit, S stand, D double else hit, U double else stand,
# R surrender else hit, W surrender else stand,
# Y split, Z surrender else split, "." play the total instead of splitting.
HARD_H17 = {
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
HARD_S17 = {
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
    15: "SSSSSHHHHH",
    16: "SSSSSHHRRR",
    17: "SSSSSSSSSS",
    18: "SSSSSSSSSS",
    19: "SSSSSSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
SOFT_H17 = {
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
SOFT_S17 = {
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
PAIRS_H17_DAS = {
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
PAIRS_S17_DAS = {
    "A": "YYYYYYYYYY",
    "10": "SSSSSSSSSS",
    "9": "YYYYYSYYSS",
    "8": "YYYYYYYYYY",
    "7": "YYYYYY....",
    "6": "YYYYY.....",
    "5": "..........",
    "4": "...YY.....",
    "3": "YYYYYY....",
    "2": "YYYYYY....",
}
PAIRS_H17_NDAS = {
    "A": "YYYYYYYYYY",
    "10": "SSSSSSSSSS",
    "9": "YYYYYSYYSS",
    "8": "YYYYYYYYYZ",
    "7": "YYYYYY....",
    "6": ".YYYY.....",
    "5": "..........",
    "4": "..........",
    "3": "..YYYY....",
    "2": "..YYYY....",
}
PAIRS_S17_NDAS = {
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
_HARD_CODES = frozenset("HSDRW")
_SOFT_CODES = frozenset("HSDU")
_PAIR_CODES = frozenset("YSZ.")
_TWO_CARD_ONLY = frozenset({"double", "split", "surrender", "insurance"})
_TENS = frozenset({"10", "J", "Q", "K"})
_HARD_KEYS = tuple(range(5, 22))
_SOFT_KEYS = tuple(range(13, 22))
_PAIR_KEYS = ("A", "10", "9", "8", "7", "6", "5", "4", "3", "2")


def validate_charts() -> None:
    """Every published string is 10 characters and the key sets are complete.

    Called at import. A drifted cell length or a missing total fails before
    any hand is scored.
    """
    hard = {"HARD_H17": HARD_H17, "HARD_S17": HARD_S17}
    soft = {"SOFT_H17": SOFT_H17, "SOFT_S17": SOFT_S17}
    pairs = {
        "PAIRS_H17_DAS": PAIRS_H17_DAS,
        "PAIRS_S17_DAS": PAIRS_S17_DAS,
        "PAIRS_H17_NDAS": PAIRS_H17_NDAS,
        "PAIRS_S17_NDAS": PAIRS_S17_NDAS,
    }
    for name, table in hard.items():
        _check_table(name, table, _HARD_KEYS, _HARD_CODES)
    for name, table in soft.items():
        _check_table(name, table, _SOFT_KEYS, _SOFT_CODES)
    for name, table in pairs.items():
        _check_table(name, table, _PAIR_KEYS, _PAIR_CODES)


def _check_table(name: str, table: dict, keys: tuple, alphabet: frozenset[str]) -> None:
    found = tuple(table)
    if found != keys:
        raise RuntimeError(f"{name} keys {found} != {keys}")
    for key in keys:
        row = table[key]
        if len(row) != len(DEALER_UPCARDS):
            raise RuntimeError(f"{name}[{key!r}] length {len(row)} != 10")
        bad = set(row) - alphabet
        if bad:
            raise RuntimeError(f"{name}[{key!r}] has codes {sorted(bad)}")


@dataclass(frozen=True)
class HandFacts:
    """Recomputed total. ``caller_soft`` is only kept so a disagreement is visible."""

    total: int
    soft: bool
    pair: str | None
    n_cards: int
    caller_soft: bool | None
    soft_disagrees: bool


def hand_facts(cards: list[Card], *, caller_soft: bool | None = None) -> HandFacts:
    """Hard/soft total from the cards. Aces start at 1; one ace is 11 if it fits.

    A pair is two cards of the same rank, or any two 10-value cards (10/J/Q/K),
    which the chart plays as a pair of tens (never split).
    """
    total = 0
    aces = 0
    for card in cards:
        if card.rank == "A":
            aces += 1
            total += 1
        elif card.rank in _TENS:
            total += 10
        else:
            total += int(card.rank)
    soft = bool(aces and total + 10 <= 21)
    if soft:
        total += 10
    pair = None
    if len(cards) == 2:
        left, right = cards[0].rank, cards[1].rank
        if left == right or (left in _TENS and right in _TENS):
            pair = "10" if left in _TENS else left
    disagrees = caller_soft is not None and bool(caller_soft) != soft
    return HandFacts(
        total=total,
        soft=soft,
        pair=pair,
        n_cards=len(cards),
        caller_soft=caller_soft,
        soft_disagrees=disagrees,
    )


def _hits_soft_17(rules: dict) -> bool:
    if "dealer_hits_soft_17" in rules:
        return bool(rules["dealer_hits_soft_17"])
    if "dealer_stands_soft_17" in rules:
        return not bool(rules["dealer_stands_soft_17"])
    return True


def _das(rules: dict) -> bool:
    if "das" not in rules:
        return True
    return bool(rules["das"])


def _surrender_enabled(rules: dict) -> bool:
    if "surrender" not in rules:
        return True
    raw = rules["surrender"]
    if isinstance(raw, str):
        return raw.strip().lower() in {"late", "ls", "true", "yes", "1"}
    return bool(raw)


def _upcard(card: Card) -> str:
    if card.rank in _TENS:
        return "10"
    return card.rank


def _column(up: str) -> int:
    return DEALER_UPCARDS.index(up)


def _hard_table(*, h17: bool) -> dict[int, str]:
    return HARD_H17 if h17 else HARD_S17


def _soft_table(*, h17: bool) -> dict[int, str]:
    return SOFT_H17 if h17 else SOFT_S17


def _pair_table(*, h17: bool, das: bool) -> dict[str, str]:
    if h17 and das:
        return PAIRS_H17_DAS
    if h17:
        return PAIRS_H17_NDAS
    if das:
        return PAIRS_S17_DAS
    return PAIRS_S17_NDAS


def _expand(code: str, *, surrender: bool) -> tuple[str, ...]:
    actions = _CODE[code]
    if surrender:
        return actions
    return tuple(action for action in actions if action != "surrender")


def _total_code(facts: HandFacts, up: str, *, h17: bool) -> str:
    if facts.total > 21:
        return "S"
    if facts.soft:
        if facts.total not in _SOFT_KEYS:
            return "H" if facts.total < 13 else "S"
        return _soft_table(h17=h17)[facts.total][_column(up)]
    if facts.total not in _HARD_KEYS:
        return "H" if facts.total < 5 else "S"
    return _hard_table(h17=h17)[facts.total][_column(up)]


def _unfiltered_prefs(facts: HandFacts, up: str, rules: dict) -> tuple[str, ...]:
    """Chart order before the two-card shape gate. Insurance is never listed."""
    h17 = _hits_soft_17(rules)
    das = _das(rules)
    surrender = _surrender_enabled(rules)
    prefs: list[str] = []
    if facts.pair and facts.n_cards == 2:
        code = _pair_table(h17=h17, das=das)[facts.pair][_column(up)]
        if code != ".":
            prefs.extend(_expand(code, surrender=surrender))
    for action in _expand(_total_code(facts, up, h17=h17), surrender=surrender):
        if action not in prefs:
            prefs.append(action)
    return tuple(prefs)


def _apply_shape(prefs: tuple[str, ...], facts: HandFacts) -> tuple[str, ...]:
    if facts.n_cards == 2:
        return prefs
    return tuple(action for action in prefs if action not in _TWO_CARD_ONLY)


def lookup(facts: HandFacts, up: str, rules: dict) -> tuple[str, ...]:
    """Ordered chart actions for this hand, upcard, and rule dict.

    Earlier entries win when they are still legal *and* legal for the shape
    of the hand. ``double`` / ``split`` / ``surrender`` / ``insurance`` are
    removed unless the hand has exactly two cards. ``split`` is present only
    when the pair table says so.
    """
    return _apply_shape(_unfiltered_prefs(facts, up, rules), facts)


def chart_preferences(
    facts: HandFacts, up: str, *, h17: bool, das: bool, surrender: bool
) -> tuple[str, ...]:
    """Ordered chart actions. Same result as :func:`lookup` for these three rules."""
    return lookup(
        facts,
        up,
        {"dealer_hits_soft_17": h17, "das": das, "surrender": surrender},
    )


def _bad_payout(rules: dict) -> bool:
    payout = rules.get("blackjack_payout")
    if payout is None:
        return False
    if isinstance(payout, str):
        return payout.strip().lower() in {"6:5", "6/5", "1.2", "1.2:1"}
    return float(payout) < 1.4


def _shape_ok(action: str, facts: HandFacts, prefs: tuple[str, ...]) -> bool:
    """Chart action that this hand is allowed to take.

    Insurance is never taken. Split requires a two-card pair whose chart cell
    actually lists split (it is then already in ``prefs``).
    """
    if action == "insurance":
        return False
    if action in _TWO_CARD_ONLY and facts.n_cards != 2:
        return False
    return not (action == "split" and (facts.pair is None or "split" not in prefs))


def recommend_blackjack(state: BlackjackState, policy: RiskPolicy | None = None) -> StrategyAdvice:
    """Basic-strategy action that is still legal after ``policy``.

    ``state.hands[i].is_soft`` is not trusted: the total is recomputed from the
    cards and a disagreement is written into ``reason``.
    """
    policy = policy or RiskPolicy()
    hand = state.hands[state.active_hand]
    facts = hand_facts(hand.cards, caller_soft=hand.is_soft)
    rules = dict(state.rules)
    h17 = _hits_soft_17(rules)
    das = _das(rules)
    up = _upcard(state.dealer_upcard)
    legal = actions_after_policy(state, policy)
    # Policy emptied the free set: builders offer pass + hold_policy. Chart cells
    # must not resurrect a filtered hit/double/split/surrender.
    if legal == ["pass"]:
        return StrategyAdvice(
            action="pass",
            reason=(
                "risk policy left no free blackjack action; pass "
                "(do not resurrect a costly legal_actions entry)"
            ),
            confidence=0.99,
            alternatives=(),
            game="blackjack",
        )
    raw = _unfiltered_prefs(facts, up, rules)
    prefs = _apply_shape(raw, facts)
    chosen = next(
        (action for action in prefs if action in legal and _shape_ok(action, facts, prefs)),
        None,
    )
    forced = chosen is None
    if forced:
        free = [
            action for action in legal if action != "insurance" and _shape_ok(action, facts, prefs)
        ]
        if "stand" in free:
            chosen = "stand"
        elif free:
            chosen = free[0]
        else:
            chosen = "stand" if "stand" in legal else legal[0]

    alternatives: list[tuple[str, str]] = []
    passed = False
    for action in prefs:
        if action == chosen:
            passed = True
            continue
        if passed and action in legal and _shape_ok(action, facts, prefs):
            alternatives.append((action, f"next chart action if {chosen} is declined"))
    kind = "soft" if facts.soft else "hard"
    if facts.pair and facts.n_cards == 2 and prefs and prefs[0] in {"split", "surrender"}:
        label = f"pair of {facts.pair}s"
    else:
        label = f"{kind} {facts.total}"
    rule = "H17" if h17 else "S17"
    das_label = "DAS" if das else "no DAS"
    bits = [f"{label} vs {up}: {chosen} ({rule}, {das_label}, 4–8 deck chart)"]
    if facts.soft_disagrees:
        bits.append(
            f"recomputed is_soft={facts.soft} (caller said {facts.caller_soft}); using the cards"
        )
    dropped = [action for action in raw if action not in prefs]
    if dropped:
        bits.append(
            f"{facts.n_cards} cards; not offering {', '.join(dropped)} (need exactly 2 cards)"
        )
    if "surrender" in prefs and "surrender" not in legal and chosen != "surrender":
        bits.append("surrender not legal, using the next chart action")
    if forced:
        bits.append("chart action is not legal after risk policy; fail-closed")
    decks = rules.get("decks")
    if isinstance(decks, (int, float)) and int(decks) in {1, 2}:
        bits.append(f"{int(decks)}-deck deviations are not applied")
    if _bad_payout(rules):
        bits.append("6:5 blackjack payout is not offset by this chart")
    if "insurance" in legal and chosen != "insurance":
        bits.append("insurance declined")
    confidence = 0.99
    if not h17:
        confidence = 0.97
    if isinstance(decks, (int, float)) and int(decks) in {1, 2}:
        confidence = min(confidence, 0.90)
    return StrategyAdvice(
        action=chosen,
        reason="; ".join(bits),
        confidence=confidence,
        alternatives=tuple(alternatives[:3]),
        game="blackjack",
    )


validate_charts()
