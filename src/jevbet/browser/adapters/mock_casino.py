"""Local mock-casino adapter.

``browser=False`` (the default) uses the in-process table so ``--fake`` does
not need Playwright. ``browser=True`` serves the HTML fixtures on 127.0.0.1
and drives them with Chromium.
"""

from __future__ import annotations

from jevbet.browser.casino import MockCasinoTable
from jevbet.browser.chrome import DEFAULT_LOCAL_PREFIXES, ChromeTableDriver, SelectorMap
from jevbet.browser.driver import TableDriver
from jevbet.browser.server import MockCasinoServer

from .config import AdapterConfig


class MockCasinoAdapter:
    """Built-in adapter. There is no real-casino counterpart in this package."""

    name = "mock-casino"

    def __init__(
        self,
        game: str,
        *,
        browser: bool = False,
        seed: int = 7,
        cash: float = 500.0,
        stop_loss: float | None = None,
        port: int = 0,
        headless: bool = True,
        allowed_url_prefixes: tuple[str, ...] = DEFAULT_LOCAL_PREFIXES,
        rules: dict | None = None,
    ):
        if game not in {"blackjack", "holdem"}:
            raise ValueError(
                f"mock-casino supports blackjack and holdem, not {game!r}. "
                "Other games stay on `jevbet decide` until you add an adapter."
            )
        self.game = game
        self.browser = browser
        self.seed = seed
        self.cash = cash
        self.stop_loss = stop_loss
        self.port = port
        self.headless = headless
        self.allowed_url_prefixes = tuple(allowed_url_prefixes)
        self.rules = rules
        self._server: MockCasinoServer | None = None
        self._driver: TableDriver | None = None

    def open(self) -> TableDriver:
        if self._driver is not None:
            return self._driver
        if not self.browser:
            self._driver = MockCasinoTable(
                self.game,
                seed=self.seed,
                cash=self.cash,
                stop_loss=self.stop_loss,
                rules=self.rules,
            )
            return self._driver
        server = MockCasinoServer(port=self.port)
        self._server = server
        try:
            server.start()
            query = {"seed": str(self.seed), "bankroll": str(self.cash)}
            if self.stop_loss is not None:
                query["stop_loss"] = str(self.stop_loss)
            url = server.url_for(f"{self.game}.html", query)
            config = AdapterConfig(
                game=self.game,
                base_url=url,
                selectors=SelectorMap(),
                allowed_url_prefixes=self.allowed_url_prefixes,
                headless=self.headless,
                name=self.name,
            )
            self._driver = ChromeTableDriver(
                base_url=config.base_url,
                game=config.game,
                selectors=config.selectors,
                headless=config.headless,
                allowed_url_prefixes=config.allowed_url_prefixes,
            ).start()
        except Exception:
            self.close()
            raise
        return self._driver

    def close(self) -> None:
        driver = self._driver
        server = self._server
        self._driver = None
        self._server = None
        try:
            if driver is not None:
                driver.close()
        finally:
            if server is not None:
                server.close()
