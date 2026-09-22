"""Jevbet — card/betting game decisions on top of Rizzo Flow.

Builds typed ``/v1/decisions`` requests from game state. Does not retrain Spark
weights and does not fork the inference path: it uses ``rizzo_flow.schema.Request``
and (optionally) a running Rizzo Engine or HTTP server.
"""

from .games.registry import GAMES, build_request, load_game_state, register_game

__all__ = ["GAMES", "build_request", "load_game_state", "register_game"]
__version__ = "0.1.0"
