"""Abstract table driver: observe DOM/state → act on the table."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TableDriver(ABC):
    """Site-agnostic interface for reading a table and applying a chosen action.

    Implementations must never scrape credentials or bypass site terms of service.
    Prefer user-owned sessions and explicit selector maps.
    """

    @abstractmethod
    def read_state(self) -> dict[str, Any]:
        """Return a JSON-serializable game state dict (includes ``game``)."""

    @abstractmethod
    def legal_actions(self) -> list[str]:
        """Return currently clickable / legal action ids."""

    @abstractmethod
    def act(self, action: str, *, amount: float | None = None) -> None:
        """Apply ``action`` (and optional stake/raise ``amount``) on the table."""

    def close(self) -> None:
        """Release resources; default no-op."""
