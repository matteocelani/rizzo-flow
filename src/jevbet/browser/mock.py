"""Mock table driver backed by local HTML fixtures (no network)."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .driver import TableDriver
from .parse import parse_observed_table

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
        roles: dict[str, dict[str, str]] = {}
        for role in self._roles:
            key = role.get("data-role")
            if key:
                roles[key] = role
        return parse_observed_table(
            game=self._game,
            table_attrs=self._attrs,
            roles=roles,
            actions=list(self._actions),
        )

    def legal_actions(self) -> list[str]:
        return list(self._actions)

    def act(self, action: str, *, amount: float | None = None) -> None:
        if action not in self._actions:
            raise ValueError(f"Action {action!r} is not legal: {self._actions}")
        self.history.append({"action": action, "amount": amount})
