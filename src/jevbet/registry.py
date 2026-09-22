"""Re-export registry helpers at package root."""

from .games.registry import GAMES, build_request, load_game_state, register_game

__all__ = ["GAMES", "build_request", "load_game_state", "register_game"]
