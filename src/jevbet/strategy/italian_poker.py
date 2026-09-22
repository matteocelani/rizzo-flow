"""Poker italiano heuristic: the Hold'em rules, on 40-card ranks.

Asso is high (value 14, above Re). Straights use those numeric ranks, so asso
does not connect to Re (the 11–13 slots of a French deck are absent). The same
pot-odds and made-hand flags apply. This is not a solved Italian-deck game.
"""

from __future__ import annotations

from ..games.italian_poker import ItalianPokerState, actions_after_policy
from ..policy import RiskPolicy
from .advice import StrategyAdvice
from .holdem import _fallback, _postflop, _preflop
from .poker import ITALIAN_VALUE, italian_deck, pot_odds


def _cards(cards) -> list[tuple[int, str]]:
    return [(ITALIAN_VALUE[card.rank], card.suit) for card in cards]


def _sizes(state: ItalianPokerState, policy: RiskPolicy, legal: list[str]) -> list[float]:
    """Only ``min_raise`` when it survives the bankroll cap and the stack."""
    if "raise" not in legal or state.min_raise <= 0:
        return []
    kept = policy.filter_bet_sizes(state.bankroll, [float(state.min_raise)])
    return [size for size in kept if size <= state.stack + 1e-9]


def recommend_italian_poker(
    state: ItalianPokerState, policy: RiskPolicy | None = None
) -> StrategyAdvice:
    policy = policy or RiskPolicy()
    legal = actions_after_policy(state, policy)
    if legal == ["pass"] and "pass" not in state.legal_actions:
        return StrategyAdvice(
            action="pass",
            reason=(
                "risk policy left no free italian poker action; pass "
                "(do not resurrect a costly legal_actions entry)"
            ),
            confidence=0.99,
            game="italian_poker",
        )
    sizes = _sizes(state, policy, legal)
    price = pot_odds(state.pot, state.to_call)
    if len(state.hole_cards) < 2:
        return StrategyAdvice(
            action=_fallback(legal),
            reason="need two hole cards; taking a free or folding action",
            confidence=0.4,
            game="italian_poker",
        )
    hole = _cards(state.hole_cards[:2])
    if state.street == "preflop" or not state.community:
        advice = _preflop(state, hole, legal, sizes, price)
    else:
        advice = _postflop(
            state, hole, _cards(state.community), legal, sizes, price, italian_deck()
        )
    return StrategyAdvice(
        action=advice.action,
        reason=advice.reason,
        confidence=advice.confidence,
        alternatives=advice.alternatives,
        game="italian_poker",
        size=advice.size,
    )
