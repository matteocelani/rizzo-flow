"""Roulette has no winning strategy. The recommendation is to pass.

European single-zero house edge is 1/37 ≈ 2.70%. American double-zero is
2/38 ≈ 5.26%. Even-money bets carry the same edge as a straight-up on a fair
wheel: the zero (and double-zero) is why. Past spins (``last_results``) do not
change the next spin. This module never reads them.

If ``pass`` is legal it is always the action. If the table forces a bet, the
least-bad legal type is an even-money bet (red/black/even/odd/low/high), at the
minimum chip that survives policy. Inside bets are recommended only when
nothing else is legal, and then with low confidence.
"""

from __future__ import annotations

from ..games.roulette import RouletteState, offers_after_policy
from ..policy import RiskPolicy
from .advice import StrategyAdvice

# Fixed preference. Independent of recent numbers. ``pass`` is always first.
BET_PREFERENCE = (
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
_EVEN = frozenset({"red", "black", "even", "odd", "low", "high"})


def _edge(wheel: str) -> str:
    if wheel == "american":
        return "American double-zero house edge is about 5.26% (2/38)"
    return "European single-zero house edge is about 2.70% (1/37)"


def recommend_roulette(state: RouletteState, policy: RiskPolicy | None = None) -> StrategyAdvice:
    policy = policy or RiskPolicy(min_bet=state.min_bet)
    types, chips = offers_after_policy(state, policy)
    legal = set(types)
    chosen = next((name for name in BET_PREFERENCE if name in legal), types[0])
    edge = _edge(state.wheel)
    size = float(chips[0]) if chips and chosen != "pass" else None
    if chosen == "pass":
        reason = f"pass; {edge}. Last results are ignored — they do not change the next spin"
        confidence = 0.99
    elif chosen in _EVEN:
        reason = (
            f"pass is not legal; minimum even-money {chosen} is the least-bad forced bet. "
            f"{edge}. Still negative EV; last results ignored"
        )
        confidence = 0.88
    else:
        reason = (
            f"no pass and no even-money bet is legal; {chosen} is still negative EV. "
            f"{edge}. Last results ignored"
        )
        confidence = 0.55
    alternatives = tuple(
        (name, "also negative EV") for name in BET_PREFERENCE if name in legal and name != chosen
    )[:3]
    return StrategyAdvice(
        action=chosen,
        reason=reason,
        confidence=confidence,
        alternatives=alternatives,
        game="roulette",
        size=size,
    )
