"""Multi-deck blackjack basic strategy.

Default chart: 4–8 decks, dealer hits soft 17 (H17), double after split (DAS),
late surrender when that action is legal. Source: Blackjack Apprenticeship H17
basic-strategy chart (2024 PDF) plus their published hard-total phrases
("11 always doubles" on H17). It is total-dependent, not composition-dependent,
and it is not a card-counting index chart.

Deviations applied when ``state.rules`` say so
------------------------------------------------
S17 (``dealer_hits_soft_17`` false, or ``dealer_stands_soft_17`` true):

- hard 11 vs A → hit, not double
- soft 18 (A,7) vs 2 → stand, not double
- soft 19 (A,8) vs 6 → stand, not double
- hard 15 vs A → hit, not surrender
- hard 17 vs A → stand, not surrender
- pair of 8s vs A → split, not surrender

No DAS (``das`` false): 2,2 and 3,3 vs 2–3 hit; 4,4 vs 5–6 hit; 6,6 vs 2 hit.

``surrender`` false skips surrender cells even if the table listed the action.
Missing ``surrender`` means "use it when it is legal".

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

_UPS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "A")

# One character per dealer upcard, left to right 2…A.
# H hit, S stand, D double else hit, U double else stand,
# R surrender else hit, W surrender else stand,
# Y split, Z surrender else split, "." play the total instead of splitting.
_HARD_H17 = {
    9: "HDDDDHHHHH",
    10: "DDDDDDDDHH",
    11: "DDDDDDDDDD",
    12: "HHSSSHHHHH",
    13: "SSSSSHHHHH",
    14: "SSSSSHHHHH",
    15: "SSSSSHHHRR",
    16: "SSSSSHHRRR",
    17: "SSSSSSSSSW",
}
_SOFT_H17 = {
    13: "HHHDDHHHHH",
    14: "HHHDDHHHHH",
    15: "HHDDDHHHHH",
    16: "HHDDDHHHHH",
    17: "HDDDDHHHHH",
    18: "UUUUUSSHHH",
    19: "SSSSUSSSSS",
    20: "SSSSSSSSSS",
}
_PAIRS_H17_DAS = {
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
_TENS = frozenset({"10", "J", "Q", "K"})


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


def _pair_code(rank: str, up: str, *, h17: bool, das: bool) -> str:
    code = _PAIRS_H17_DAS[rank][_UPS.index(up)]
    if not das:
        if rank in {"2", "3"} and up in {"2", "3"}:
            return "."
        if rank == "4" and up in {"5", "6"}:
            return "."
        if rank == "6" and up == "2":
            return "."
    if not h17 and rank == "8" and up == "A" and code == "Z":
        return "Y"
    return code


def _total_code(facts: HandFacts, up: str, *, h17: bool) -> str:
    if facts.total > 21 or facts.total == 21:
        return "S"
    if facts.soft and facts.total <= 12:
        return "H"
    if facts.soft:
        code = _SOFT_H17[facts.total][_UPS.index(up)]
        if not h17 and facts.total == 18 and up == "2":
            return "S"
        if not h17 and facts.total == 19 and up == "6":
            return "S"
        return code
    if facts.total >= 18:
        return "S"
    if facts.total <= 8:
        return "H"
    code = _HARD_H17[facts.total][_UPS.index(up)]
    if not h17 and facts.total == 11 and up == "A":
        return "H"
    if not h17 and facts.total == 15 and up == "A":
        return "H"
    if not h17 and facts.total == 17 and up == "A":
        return "S"
    return code


def chart_preferences(
    facts: HandFacts, up: str, *, h17: bool, das: bool, surrender: bool
) -> tuple[str, ...]:
    """Ordered chart actions. Earlier entries win when they are legal."""
    prefs: list[str] = []
    if facts.pair and facts.n_cards == 2:
        code = _pair_code(facts.pair, up, h17=h17, das=das)
        if code != ".":
            prefs.extend(_CODE[code])
    for action in _CODE[_total_code(facts, up, h17=h17)]:
        if action not in prefs:
            prefs.append(action)
    if not surrender:
        prefs = [action for action in prefs if action != "surrender"]
    return tuple(prefs)


def _bad_payout(rules: dict) -> bool:
    payout = rules.get("blackjack_payout")
    if payout is None:
        return False
    if isinstance(payout, str):
        return payout.strip().lower() in {"6:5", "6/5", "1.2", "1.2:1"}
    return float(payout) < 1.4


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
    surrender = _surrender_enabled(rules)
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
    prefs = chart_preferences(facts, up, h17=h17, das=das, surrender=surrender)
    chosen = next((action for action in prefs if action in legal), None)
    forced = chosen is None
    if forced:
        chosen = "stand" if "stand" in legal else legal[0]

    alternatives: list[tuple[str, str]] = []
    passed = False
    for action in prefs:
        if action == chosen:
            passed = True
            continue
        if passed and action in legal:
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
