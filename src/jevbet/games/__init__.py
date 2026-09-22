"""Primary game models and builders."""

from .blackjack import BlackjackState, build_blackjack_request
from .holdem import HoldemState, build_holdem_request
from .italian_poker import ItalianPokerState, build_italian_poker_request
from .registry import (
    GAMES,
    build_request,
    list_games,
    load_game_state,
    register_game,
    resolve_game_name,
    unregister_game,
)
from .roulette import RouletteState, build_roulette_request
from .scopa import ScopaState, build_scopa_request
from .tre_sette import TreSetteState, build_tre_sette_request

__all__ = [
    "GAMES",
    "BlackjackState",
    "HoldemState",
    "ItalianPokerState",
    "RouletteState",
    "ScopaState",
    "TreSetteState",
    "build_blackjack_request",
    "build_holdem_request",
    "build_italian_poker_request",
    "build_request",
    "build_roulette_request",
    "build_scopa_request",
    "build_tre_sette_request",
    "list_games",
    "load_game_state",
    "register_game",
    "resolve_game_name",
    "unregister_game",
]
