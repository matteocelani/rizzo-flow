"""Deterministic strategy for Jevbet games.

Rizzo/Spark stays an optional advisor. ``recommend`` is the default decide path:
a confident, still-legal action is not overridden unless the caller asks for the model.
"""

from .advice import CONFIDENT_AT, StrategyAdvice
from .betting import recommend_bet
from .blackjack import hand_facts, recommend_bet_for_state, recommend_blackjack
from .dispatch import recommend
from .select import compose_response, should_use_model

__all__ = [
    "CONFIDENT_AT",
    "StrategyAdvice",
    "compose_response",
    "hand_facts",
    "recommend",
    "recommend_bet",
    "recommend_bet_for_state",
    "recommend_blackjack",
    "should_use_model",
]
