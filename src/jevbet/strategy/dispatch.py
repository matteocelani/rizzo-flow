"""Pick the strategy engine for a typed game state."""

from __future__ import annotations

from ..policy import RiskPolicy
from .advice import StrategyAdvice
from .blackjack import recommend_blackjack
from .holdem import recommend_holdem
from .italian_poker import recommend_italian_poker
from .roulette import recommend_roulette
from .scopa import recommend_scopa
from .tre_sette import recommend_tre_sette


def recommend(state, policy: RiskPolicy | None = None) -> StrategyAdvice:
    """Strategy advice for a validated game state. Unknown games are not confident."""
    game = getattr(state, "game", None)
    if game in {"scopa", "tre_sette"} and policy is None:
        policy = RiskPolicy(min_bet=0.0)
    if game == "blackjack":
        return recommend_blackjack(state, policy)
    if game == "holdem":
        return recommend_holdem(state, policy)
    if game == "roulette":
        return recommend_roulette(state, policy)
    if game == "scopa":
        return recommend_scopa(state, policy)
    if game == "tre_sette":
        return recommend_tre_sette(state, policy)
    if game == "italian_poker":
        return recommend_italian_poker(state, policy)
    return StrategyAdvice(
        action=None,
        reason=f"no strategy engine for game {game!r}",
        confidence=0.0,
        game=str(game or ""),
    )
