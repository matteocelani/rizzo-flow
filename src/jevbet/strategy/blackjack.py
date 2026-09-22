"""Blackjack strategy: basic charts + optional Hi-Lo Illustrious 18.

Default path is total-dependent basic strategy. Chart selection:

* H17 → Blackjack Apprenticeship multi-deck tables
* S17 + ``decks == 1`` → blackjacksimulator.net single-deck table
* S17 + ``decks >= 2`` → blackjacksimulator.net multi-deck table

When ``rules.counting`` is ``hi-lo``, Illustrious 18 / Fab 4 deviations override
the chart at their true-count thresholds (action must still be legal). Insurance
is taken only with counting on and TC ≥ +3 (otherwise declined; EV ≈ −7%).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..cards import Card
from ..games.blackjack import BlackjackState, actions_after_policy, derive_capabilities
from ..policy import RiskPolicy
from .advice import StrategyAdvice
from .charts import (
    DEALER_UPCARDS,
    HARD_H17,
    HARD_S17,
    HARD_S17_1D,
    HARD_S17_MULTI,
    PAIRS_H17_DAS,
    PAIRS_H17_NDAS,
    PAIRS_S17_1D_DAS,
    PAIRS_S17_1D_NDAS,
    PAIRS_S17_DAS,
    PAIRS_S17_MULTI_DAS,
    PAIRS_S17_MULTI_NDAS,
    PAIRS_S17_NDAS,
    SOFT_H17,
    SOFT_S17,
    SOFT_S17_1D,
    SOFT_S17_MULTI,
    das_enabled,
    hits_soft_17,
    select_tables,
    surrender_enabled,
    validate_charts,
)
from .count import count_from_state, counting_enabled
from .illustrious import deviation_for, should_take_insurance

# Re-export chart tables for tests and docs.
__all__ = [
    "DEALER_UPCARDS",
    "HARD_H17",
    "HARD_S17",
    "HARD_S17_1D",
    "HARD_S17_MULTI",
    "PAIRS_H17_DAS",
    "PAIRS_H17_NDAS",
    "PAIRS_S17_1D_DAS",
    "PAIRS_S17_1D_NDAS",
    "PAIRS_S17_DAS",
    "PAIRS_S17_MULTI_DAS",
    "PAIRS_S17_MULTI_NDAS",
    "PAIRS_S17_NDAS",
    "SOFT_H17",
    "SOFT_S17",
    "SOFT_S17_1D",
    "SOFT_S17_MULTI",
    "HandFacts",
    "chart_preferences",
    "hand_facts",
    "lookup",
    "recommend_bet_for_state",
    "recommend_blackjack",
    "validate_charts",
]

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
_TWO_CARD_ONLY = frozenset({"double", "split", "surrender", "insurance"})
_TENS = frozenset({"10", "J", "Q", "K"})
_HARD_KEYS = tuple(range(5, 22))
_SOFT_KEYS = tuple(range(13, 22))


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
    """Hard/soft total from the cards. Aces start at 1; one ace is 11 if it fits."""
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


def _upcard(card: Card) -> str:
    if card.rank in _TENS:
        return "10"
    return card.rank


def _column(up: str) -> int:
    return DEALER_UPCARDS.index(up)


def _expand(code: str, *, surrender: bool) -> tuple[str, ...]:
    actions = _CODE[code]
    if surrender:
        return actions
    return tuple(action for action in actions if action != "surrender")


def _total_code(facts: HandFacts, up: str, hard: dict[int, str], soft: dict[int, str]) -> str:
    if facts.total > 21:
        return "S"
    if facts.soft:
        if facts.total not in _SOFT_KEYS:
            return "H" if facts.total < 13 else "S"
        return soft[facts.total][_column(up)]
    if facts.total not in _HARD_KEYS:
        return "H" if facts.total < 5 else "S"
    return hard[facts.total][_column(up)]


def _unfiltered_prefs(facts: HandFacts, up: str, rules: dict) -> tuple[str, ...]:
    hard, soft, pairs, _label = select_tables(rules)
    surrender = surrender_enabled(rules)
    prefs: list[str] = []
    if facts.pair and facts.n_cards == 2:
        code = pairs[facts.pair][_column(up)]
        if code != ".":
            prefs.extend(_expand(code, surrender=surrender))
    for action in _expand(_total_code(facts, up, hard, soft), surrender=surrender):
        if action not in prefs:
            prefs.append(action)
    return tuple(prefs)


def _apply_shape(prefs: tuple[str, ...], facts: HandFacts) -> tuple[str, ...]:
    if facts.n_cards == 2:
        return prefs
    return tuple(action for action in prefs if action not in _TWO_CARD_ONLY)


def lookup(facts: HandFacts, up: str, rules: dict) -> tuple[str, ...]:
    """Ordered chart actions for this hand, upcard, and rule dict."""
    return _apply_shape(_unfiltered_prefs(facts, up, rules), facts)


def chart_preferences(
    facts: HandFacts, up: str, *, h17: bool, das: bool, surrender: bool, decks: int = 6
) -> tuple[str, ...]:
    """Ordered chart actions. Same result as :func:`lookup` for these rules."""
    return lookup(
        facts,
        up,
        {
            "dealer_hits_soft_17": h17,
            "das": das,
            "surrender": surrender,
            "decks": decks,
        },
    )


def _bad_payout(rules: dict) -> bool:
    payout = rules.get("blackjack_payout")
    if payout is None:
        return False
    if isinstance(payout, str):
        return payout.strip().lower() in {"6:5", "6/5", "1.2", "1.2:1"}
    return float(payout) < 1.4


def _shape_ok(action: str, facts: HandFacts, prefs: tuple[str, ...], caps: dict[str, bool]) -> bool:
    if action == "insurance":
        return bool(caps.get("can_insurance"))
    if action == "double" and not caps.get("can_double", True):
        return False
    if action == "split":
        if facts.pair is None or facts.n_cards != 2:
            return False
        return bool(caps.get("can_split") or caps.get("can_resplit"))
    if action == "surrender" and not caps.get("can_surrender", True):
        return False
    if action == "hit" and not caps.get("can_hit", True):
        return False
    return not (action in _TWO_CARD_ONLY and facts.n_cards != 2)


def _resolve_count(state: BlackjackState) -> tuple[bool, int, float]:
    rules = dict(state.rules)
    enabled = counting_enabled(rules)
    if not enabled:
        return False, 0, 0.0
    observed: list[Card] = []
    for hand in state.hands:
        observed.extend(hand.cards)
    observed.append(state.dealer_upcard)
    if state.dealer_hole is not None:
        observed.append(state.dealer_hole)
    observed.extend(state.discarded)
    if state.running_count is not None and state.true_count is not None:
        return True, int(state.running_count), float(state.true_count)
    rc, tc, _left = count_from_state(
        rules=rules,
        cards_seen=state.cards_seen,
        shoe_penetration=state.shoe_penetration,
        running=state.running_count,
        observed=None if state.running_count is not None else observed,
        decks_remaining_hint=state.decks_remaining,
    )
    if state.true_count is not None:
        tc = float(state.true_count)
    return True, rc, tc


def recommend_bet_for_state(state: BlackjackState, policy: RiskPolicy | None = None):
    """Bet advice before a round. Thin wrapper used by the CLI/play loop."""
    from .betting import recommend_bet

    policy = policy or RiskPolicy()
    _enabled, _rc, tc = _resolve_count(state)
    return recommend_bet(
        state.bankroll,
        true_count=tc if counting_enabled(dict(state.rules)) else None,
        rules=dict(state.rules),
        policy=policy,
        last_result=state.last_round_result,
        step=state.martingale_step,
    )


def recommend_blackjack(state: BlackjackState, policy: RiskPolicy | None = None) -> StrategyAdvice:
    """Basic-strategy (plus optional count deviations) still legal after ``policy``."""
    policy = policy or RiskPolicy()
    hand = state.hands[state.active_hand]
    facts = hand_facts(hand.cards, caller_soft=hand.is_soft)
    rules = dict(state.rules)
    h17 = hits_soft_17(rules)
    das = das_enabled(rules)
    up = _upcard(state.dealer_upcard)
    caps = derive_capabilities(state)
    legal = actions_after_policy(state, policy)
    counting, _rc, tc = _resolve_count(state)
    _hard, _soft, _pairs, chart_label = select_tables(rules)

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

    # Insurance is its own decision only in the insurance phase (or when the
    # table offers insurance/decline without ordinary hit/double/split moves).
    play_actions = {"hit", "double", "split", "surrender"}
    insurance_spot = state.phase == "insurance" or (
        "insurance" in legal and not (play_actions & set(legal))
    )
    if insurance_spot:
        take = should_take_insurance(tc, counting=counting)
        if take and "insurance" in legal and caps.get("can_insurance", True):
            return StrategyAdvice(
                action="insurance",
                reason=f"insurance taken (Hi-Lo TC {tc:.2f} ≥ +3, Illustrious #1)",
                confidence=0.95,
                alternatives=(("decline", "Illustrious insurance only at TC ≥ +3"),),
                game="blackjack",
            )
        decline = (
            "decline"
            if "decline" in legal
            else next((a for a in ("stand", "hit", "pass") if a in legal), legal[0])
        )
        why = (
            f"insurance declined (EV ≈ −7% without counting; TC {tc:.2f})"
            if counting
            else "insurance declined (EV ≈ −7%; counting off)"
        )
        return StrategyAdvice(
            action=decline,
            reason=why,
            confidence=0.99,
            alternatives=(),
            game="blackjack",
        )

    raw = _unfiltered_prefs(facts, up, rules)
    prefs = list(_apply_shape(raw, facts))

    # Illustrious 18 / Fab 4 override when counting is on.
    if counting:
        play = deviation_for(
            total=facts.total,
            soft=facts.soft,
            pair=facts.pair,
            n_cards=facts.n_cards,
            up=up,
            true_count=tc,
            surrender=surrender_enabled(rules),
        )
        if (
            play is not None
            and play.action in legal
            and _shape_ok(play.action, facts, tuple(prefs), caps)
        ):
            # Only publish as a deviation when it differs from the chart head,
            # or when the Illustrious row forces hit below a stand index.
            chart_head = prefs[0] if prefs else None
            if play.action != chart_head:
                return StrategyAdvice(
                    action=play.action,
                    reason=(
                        f"{play.hand_key} vs {up}: {play.action} "
                        f"({play.family} index {play.index:+d}, TC {tc:.2f}; "
                        f"overrides {chart_label})"
                    ),
                    confidence=0.96,
                    alternatives=tuple((a, "basic chart") for a in prefs[:2] if a != play.action),
                    game="blackjack",
                )

    chosen = next(
        (
            action
            for action in prefs
            if action in legal and _shape_ok(action, facts, tuple(prefs), caps)
        ),
        None,
    )
    forced = chosen is None
    if forced:
        free = [
            action
            for action in legal
            if action not in {"insurance"} and _shape_ok(action, facts, tuple(prefs), caps)
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
        if passed and action in legal and _shape_ok(action, facts, tuple(prefs), caps):
            alternatives.append((action, f"next chart action if {chosen} is declined"))
    kind = "soft" if facts.soft else "hard"
    if facts.pair and facts.n_cards == 2 and prefs and prefs[0] in {"split", "surrender"}:
        label = f"pair of {facts.pair}s"
    else:
        label = f"{kind} {facts.total}"
    rule = "H17" if h17 else "S17"
    das_label = "DAS" if das else "no DAS"
    bits = [f"{label} vs {up}: {chosen} ({rule}, {das_label}, {chart_label})"]
    if counting:
        bits.append(f"Hi-Lo TC {tc:.2f}")
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
    if _bad_payout(rules):
        bits.append("6:5 blackjack payout is not offset by this chart")
    if "insurance" in state.legal_actions and chosen != "insurance":
        bits.append("insurance declined")
    confidence = 0.99
    if not h17:
        confidence = 0.97
    if chart_label.startswith("S17 single"):
        confidence = min(confidence, 0.95)
    return StrategyAdvice(
        action=chosen,
        reason="; ".join(bits),
        confidence=confidence,
        alternatives=tuple(alternatives[:3]),
        game="blackjack",
    )


validate_charts()
