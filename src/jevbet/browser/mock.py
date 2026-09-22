"""Mock table driver backed by local HTML fixtures (no network)."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .driver import TableDriver

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class _TableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.table_attrs: dict[str, str] = {}
        self.roles: list[dict[str, str]] = []
        self.actions: list[str] = []

    def handle_starttag(self, tag, attrs):
        data = {k: v for k, v in attrs if v is not None}
        if tag == "div" and data.get("id") == "table":
            self.table_attrs = data
        if "data-role" in data:
            self.roles.append(dict(data))
        if tag in {"button", "a"} and data.get("data-action"):
            self.actions.append(data["data-action"])


def _rank(token: str) -> str:
    body = token[:-1]
    if body in {"1", "A"}:
        return "A"
    if body in {"T", "10"}:
        return "10"
    return body


def _split_cards(raw: str | None) -> list[dict[str, str]]:
    if not raw:
        return []
    out = []
    for token in re.split(r"[,\s]+", raw.strip()):
        if not token:
            continue
        token = token.upper()
        out.append({"rank": _rank(token), "suit": token[-1]})
    return out


class MockTableDriver(TableDriver):
    """Parses a static HTML fixture and records acts for assertions."""

    def __init__(self, html: str | Path, *, game: str | None = None):
        if isinstance(html, Path) or (isinstance(html, str) and Path(html).expanduser().is_file()):
            path = Path(html)
            self.source = path.read_text(encoding="utf-8")
            self.path = path
        else:
            self.source = str(html)
            self.path = None
        parser = _TableHTMLParser()
        parser.feed(self.source)
        self._attrs = parser.table_attrs
        self._roles = parser.roles
        self._actions = list(parser.actions)
        self._game = game or self._attrs.get("data-game", "blackjack")
        self.history: list[dict[str, Any]] = []

    @classmethod
    def from_fixture(cls, name: str) -> MockTableDriver:
        root = FIXTURES_DIR.resolve()
        path = (root / name).resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"Fixture path escapes the fixtures directory: {name!r}")
        if not path.is_file():
            raise FileNotFoundError(path)
        return cls(path)

    def read_state(self) -> dict[str, Any]:
        game = self._game
        bankroll = float(self._attrs.get("data-bankroll", "1000"))
        bet = float(self._attrs.get("data-bet", "10"))
        by_role = {r.get("data-role"): r for r in self._roles}
        if game == "blackjack":
            player = by_role.get("player", {})
            dealer = by_role.get("dealer", {})
            up = _split_cards(dealer.get("data-upcard") or dealer.get("data-cards"))
            if not up:
                raise ValueError("blackjack fixture missing dealer upcard")
            return {
                "game": "blackjack",
                "dealer_upcard": up[0],
                "hands": [
                    {
                        "cards": _split_cards(player.get("data-cards")),
                        "bet": bet,
                        "is_soft": player.get("data-soft", "false").lower() == "true",
                    }
                ],
                "legal_actions": list(self._actions),
                "bankroll": {"cash": bankroll, "currency": "EUR"},
                "rules": {"decks": int(self._attrs.get("data-decks", "6"))},
            }
        if game in {"holdem", "texas_holdem"}:
            hero = by_role.get("hero", {})
            board = by_role.get("board", {})
            suggestions = [
                float(x)
                for x in self._attrs.get("data-raise-suggestions", "").split(",")
                if x.strip()
            ]
            return {
                "game": "holdem",
                "street": self._attrs.get("data-street", "flop"),
                "hole_cards": _split_cards(hero.get("data-cards")),
                "community": _split_cards(board.get("data-cards")),
                "pot": float(self._attrs.get("data-pot", "0")),
                "to_call": float(self._attrs.get("data-to-call", "0")),
                "stack": float(self._attrs.get("data-stack", str(bankroll))),
                "position": self._attrs.get("data-position", "BTN"),
                "num_players": int(self._attrs.get("data-players", "6")),
                "legal_actions": list(self._actions),
                "min_raise": float(self._attrs.get("data-min-raise", "0")),
                "raise_suggestions": suggestions,
                "bankroll": {"cash": bankroll, "currency": "EUR"},
                "rules": {"small_blind": 1, "big_blind": 2},
            }
        raise ValueError(f"MockTableDriver has no reader for game {game!r}")

    def legal_actions(self) -> list[str]:
        return list(self._actions)

    def act(self, action: str, *, amount: float | None = None) -> None:
        if action not in self._actions:
            raise ValueError(f"Action {action!r} is not legal: {self._actions}")
        self.history.append({"action": action, "amount": amount})
