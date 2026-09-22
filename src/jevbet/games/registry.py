"""Game registry and shared loaders — extension point for more card games."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import TypeAdapter

from rizzo_flow.schema import Request

from ..policy import RiskPolicy
from .blackjack import BlackjackState, build_blackjack_request
from .holdem import HoldemState, build_holdem_request
from .italian_poker import ItalianPokerState, build_italian_poker_request
from .roulette import RouletteState, build_roulette_request
from .scopa import ScopaState, build_scopa_request
from .tre_sette import TreSetteState, build_tre_sette_request

Builder = Callable[[Any, RiskPolicy | None], Request]

# Canonical name -> (state class, builder). Aliases point at the same tuple.
_CANONICAL: dict[str, tuple[type, Builder]] = {
    "blackjack": (BlackjackState, build_blackjack_request),
    "holdem": (HoldemState, build_holdem_request),
    "italian_poker": (ItalianPokerState, build_italian_poker_request),
    "tre_sette": (TreSetteState, build_tre_sette_request),
    "scopa": (ScopaState, build_scopa_request),
    "roulette": (RouletteState, build_roulette_request),
}

_ALIASES = {
    "texas_holdem": "holdem",
    "poker_italiano": "italian_poker",
    "tresette": "tre_sette",
}

GAMES: dict[str, tuple[type, Builder]] = {
    **_CANONICAL,
    **{alias: _CANONICAL[target] for alias, target in _ALIASES.items()},
}


def register_game(name: str, state_cls: type, builder: Builder) -> None:
    """Extension point: register another card/betting game without touching Rizzo core."""
    key = name.strip().lower().replace(" ", "_")
    if not key:
        raise ValueError("game name must be non-empty")
    GAMES[key] = (state_cls, builder)
    _CANONICAL[key] = (state_cls, builder)


def resolve_game_name(name: str) -> str:
    key = name.strip().lower().replace(" ", "_")
    if key in _ALIASES:
        return _ALIASES[key]
    if key in _CANONICAL:
        return key
    known = ", ".join(sorted(_CANONICAL))
    raise ValueError(f"Unknown game {name!r}. Known: {known}")


def list_games() -> list[str]:
    """Canonical game ids (no aliases)."""
    return sorted(_CANONICAL)


def load_game_state(payload: dict[str, Any], game: str | None = None):
    """Validate a JSON object into a typed game state.

    Accepts either ``{"game": "...", ...fields}`` or a bare state plus ``game=``.
    """
    data = dict(payload)
    raw = (game or data.get("game") or "").strip()
    if not raw:
        raise ValueError("Missing game id; pass game= or a 'game' field in the JSON")
    canonical = resolve_game_name(raw)
    state_cls, _ = _CANONICAL[canonical]
    data["game"] = state_cls.model_fields["game"].default
    return TypeAdapter(state_cls).validate_python(data)


def build_request(
    payload: dict[str, Any], *, game: str | None = None, policy: RiskPolicy | None = None
) -> Request:
    state = load_game_state(payload, game=game)
    canonical = resolve_game_name(state.game)
    _, builder = _CANONICAL[canonical]
    return builder(state, policy)
