"""Chromium / Playwright table driver skeleton.

Site-specific selectors live in a configurable map. No real casino URLs are
hard-coded; pass ``base_url`` yourself. Do not store credentials in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .driver import TableDriver


@dataclass
class SelectorMap:
    """CSS / Playwright selectors for one site adapter.

    TODO: fill these per site. Keep them outside source control secrets; load from
    a local YAML/JSON the user maintains.
    """

    table_root: str = "#table"
    bankroll: str = "[data-bankroll]"
    action_buttons: str = "button[data-action]"
    # Blackjack
    player_cards: str = "[data-role=player][data-cards]"
    dealer_upcard: str = "[data-role=dealer][data-upcard]"
    # Hold'em
    hole_cards: str = "[data-role=hero][data-cards]"
    community: str = "[data-role=board][data-cards]"
    pot: str = "[data-pot]"
    extra: dict[str, str] = field(default_factory=dict)


class ChromeTableDriver(TableDriver):
    """Launch Chromium via Playwright and map DOM → game state.

    Requires optional extra: ``uv sync --extra browser`` (installs playwright).
    After install, run ``playwright install chromium`` once on the machine.
    """

    def __init__(
        self,
        *,
        base_url: str,
        game: str,
        selectors: SelectorMap | None = None,
        headless: bool = True,
        browser: Any = None,
        page: Any = None,
    ):
        if not base_url:
            raise ValueError("base_url is required (no default casino URL)")
        self.base_url = base_url
        self.game = game
        self.selectors = selectors or SelectorMap()
        self.headless = headless
        self._browser = browser
        self._page = page
        self._owned = False

    def start(self) -> ChromeTableDriver:
        """Open Chromium and navigate to ``base_url``."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ImportError(
                "Playwright is optional. Install with: uv sync --extra browser && "
                "uv run playwright install chromium"
            ) from exc
        if self._page is not None:
            return self
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        self._page.goto(self.base_url)
        self._owned = True
        return self

    def read_state(self) -> dict[str, Any]:
        self._ensure_page()
        # TODO: site-specific parsing using self.selectors.
        # Prefer reading structured data-* attributes when the page exposes them;
        # otherwise map visible text → Card.parse / ItalianCard.parse.
        raise NotImplementedError(
            "ChromeTableDriver.read_state needs a site-specific selector map. "
            "Use MockTableDriver for local tests, or subclass and implement DOM reads."
        )

    def legal_actions(self) -> list[str]:
        self._ensure_page()
        buttons = self._page.query_selector_all(self.selectors.action_buttons)
        actions = []
        for button in buttons:
            value = button.get_attribute("data-action")
            if value:
                actions.append(value)
        return actions

    def act(self, action: str, *, amount: float | None = None) -> None:
        self._ensure_page()
        locator = self._page.locator(f"{self.selectors.action_buttons}[data-action='{action}']")
        if locator.count() == 0:
            raise ValueError(f"No clickable control for action {action!r}")
        # TODO: if amount is set, fill the stake/raise input before clicking.
        del amount
        locator.first.click()

    def close(self) -> None:
        if not self._owned:
            return
        if self._browser is not None:
            self._browser.close()
        if getattr(self, "_playwright", None) is not None:
            self._playwright.stop()
        self._browser = None
        self._page = None
        self._owned = False

    def _ensure_page(self) -> None:
        if self._page is None:
            raise RuntimeError("Call start() before using ChromeTableDriver")
