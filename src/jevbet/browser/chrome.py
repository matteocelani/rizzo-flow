"""Chromium / Playwright table driver.

The built-in ``read_state`` understands the local mock casino only (the
``data-*`` contract in ``browser/fixtures``). Real-site adapters subclass this
driver and override ``read_state``. No casino URL is hard-coded. Credentials
do not belong in this module or in an adapter config.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Self
from urllib.parse import urlparse

from .driver import TableDriver
from .parse import (
    ROLE_ATTRS,
    TABLE_ATTRS,
    bankroll_from_attrs,
    parse_observed_table,
    read_element_attrs,
)

# Same shape as a Rizzo option id. Rejects quotes, brackets, and selector metacharacters.
_ACTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
NAVIGATION_TIMEOUT_MS = 30_000

# Loopback only. A site adapter widens this explicitly; it is never implied.
DEFAULT_LOCAL_PREFIXES = (
    "http://127.0.0.1",
    "http://localhost",
    "https://127.0.0.1",
    "https://localhost",
)

_MOCK_GAMES = frozenset({"blackjack", "holdem", "texas_holdem"})


def url_is_allowed(url: str, prefixes: tuple[str, ...]) -> bool:
    """True when ``url`` matches a scheme+host prefix (and optional path).

    The host must be equal to the prefix host. ``http://127.0.0.1.evil.com``
    and userinfo tricks such as ``http://127.0.0.1:9@evil.com`` are rejected.
    A prefix with a port constrains the port; a prefix without one allows any.
    """
    if not isinstance(url, str) or not url or url != url.strip():
        return False
    if any(ch in url for ch in "\r\n\t "):
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not parsed.netloc:
        return False
    if parsed.username or parsed.password or "@" in parsed.netloc:
        return False
    host = parsed.hostname.lower()
    for prefix in prefixes:
        if not isinstance(prefix, str) or not prefix.strip():
            continue
        pref = urlparse(prefix.strip())
        if pref.scheme not in {"http", "https"} or not pref.hostname:
            continue
        if parsed.scheme != pref.scheme or host != pref.hostname.lower():
            continue
        if pref.port is not None and parsed.port != pref.port:
            continue
        pref_path = pref.path or ""
        if pref_path not in {"", "/"}:
            path = parsed.path or "/"
            base = pref_path.rstrip("/")
            if path != base and not path.startswith(base + "/"):
                continue
        return True
    return False


def format_stake(amount: float) -> str:
    """Decimal text for a stake input. Never interpolated into a selector."""
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise TypeError("amount must be a number")
    value = float(amount)
    if not math.isfinite(value) or value < 0:
        raise ValueError("amount must be a finite non-negative number")
    return f"{value:.2f}"


def discard_browser(browser: Any, playwright: Any) -> None:
    """Close a Chromium launch. ``stop`` still runs if ``close`` fails."""
    try:
        if browser is not None:
            browser.close()
    finally:
        if playwright is not None:
            playwright.stop()


def launch_chromium(headless: bool) -> tuple[Any, Any, Any]:
    """Start Playwright Chromium. Returns ``(playwright, browser, page)``."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ImportError(
            "Playwright is optional. Install with: uv sync --extra browser && "
            "uv run playwright install chromium"
        ) from exc
    playwright = sync_playwright().start()
    browser = None
    try:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
    except Exception:
        discard_browser(browser, playwright)
        raise
    return playwright, browser, page


@dataclass
class SelectorMap:
    """CSS / Playwright selectors for one site adapter.

    The defaults match the local mock casino. Load a different map from a
    local JSON file (see ``load_adapter_config``). Keep secrets out of it.
    """

    table_root: str = "#table"
    bankroll: str = "[data-bankroll]"
    action_buttons: str = "button[data-action]"
    amount_input: str = "input[data-amount]"
    # Blackjack
    player_cards: str = "[data-role=player][data-cards]"
    dealer_upcard: str = "[data-role=dealer][data-upcard]"
    # Hold'em
    hole_cards: str = "[data-role=hero][data-cards]"
    community: str = "[data-role=board][data-cards]"
    pot: str = "[data-pot]"
    extra: dict[str, str] = field(default_factory=dict)


class ChromeTableDriver(TableDriver):
    """Launch Chromium via Playwright and map the mock-casino DOM to state.

    Requires the optional extra: ``uv sync --extra browser``, then
    ``uv run playwright install chromium`` once on the machine.

    ``base_url`` must fall under ``allowed_url_prefixes`` (loopback by default)
    before a browser process is started.
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
        allowed_url_prefixes: tuple[str, ...] | None = None,
        _launcher: Callable[[], tuple[Any, Any, Any]] | None = None,
    ):
        if not base_url:
            raise ValueError("base_url is required (no default casino URL)")
        prefixes = tuple(allowed_url_prefixes or DEFAULT_LOCAL_PREFIXES)
        if not url_is_allowed(base_url, prefixes):
            raise ValueError(
                f"base_url {base_url!r} is not under the allowlist {list(prefixes)}. "
                "The default allowlist is localhost / 127.0.0.1. Widen "
                "allowed_url_prefixes explicitly for a site adapter you control; "
                "never commit credentials."
            )
        self.base_url = base_url
        self.game = game
        self.selectors = selectors or SelectorMap()
        self.headless = headless
        self.allowed_url_prefixes = prefixes
        self._browser = browser
        self._page = page
        self._playwright = None
        self._owned = False
        self._launcher = _launcher

    def start(self) -> ChromeTableDriver:
        """Open Chromium and navigate to ``base_url``.

        If navigation fails, the browser process is closed before the error
        propagates.
        """
        if self._page is not None:
            return self
        if not url_is_allowed(self.base_url, self.allowed_url_prefixes):
            raise ValueError(f"base_url {self.base_url!r} is not under the allowlist")
        playwright = None
        browser = None
        try:
            if self._launcher is not None:
                playwright, browser, page = self._launcher()
            else:
                playwright, browser, page = launch_chromium(self.headless)
            page.set_default_timeout(NAVIGATION_TIMEOUT_MS)
            page.goto(
                self.base_url,
                timeout=NAVIGATION_TIMEOUT_MS,
                wait_until="domcontentloaded",
            )
        except Exception:
            discard_browser(browser, playwright)
            raise
        self._playwright = playwright
        self._browser = browser
        self._page = page
        self._owned = True
        return self

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def peek(self) -> dict[str, Any]:
        """Read bankroll and phase without clicking Deal."""
        self._ensure_page()
        attrs = self._root_attrs()
        table_min = attrs.get("data-table-min")
        if table_min is None:
            table_min = attrs.get("data-bet", "0")
        return {
            "phase": attrs.get("data-phase", "playing"),
            "bankroll": bankroll_from_attrs(attrs),
            "table_min_bet": float(table_min or 0),
        }

    def read_state(self) -> dict[str, Any]:
        """Read the local mock casino.

        Between hands, click the mock's Deal control first so the returned
        state is a playable hand. Other DOMs raise ``NotImplementedError``:
        subclass this driver for a real site.
        """
        self._ensure_page()
        self._ensure_playing()
        attrs = self._root_attrs()
        game = (attrs.get("data-game") or self.game or "").strip().lower()
        if game not in _MOCK_GAMES:
            raise NotImplementedError(
                "ChromeTableDriver.read_state reads the local mock casino only "
                f"(blackjack, holdem). Game {game!r} needs a site-adapter subclass "
                "that overrides read_state. See docs/jevbet.md."
            )
        roles: dict[str, dict[str, str]] = {}
        for key, selector in (
            ("player", self.selectors.player_cards),
            ("dealer", self.selectors.dealer_upcard),
            ("hero", self.selectors.hole_cards),
            ("board", self.selectors.community),
        ):
            element = self._page.query_selector(selector)
            if element is None:
                continue
            roles[key] = read_element_attrs(element, ROLE_ATTRS)
            roles[key].setdefault("data-role", key)
        return parse_observed_table(
            game=game,
            table_attrs=attrs,
            roles=roles,
            actions=self.legal_actions(),
        )

    def legal_actions(self) -> list[str]:
        self._ensure_page()
        actions = []
        for button in self._page.query_selector_all(self.selectors.action_buttons):
            value = button.get_attribute("data-action")
            if value and value != "deal":
                actions.append(value)
        return actions

    def act(self, action: str, *, amount: float | None = None) -> None:
        self._ensure_page()
        self._click(action, amount=amount)

    def close(self) -> None:
        if not self._owned:
            return
        browser = self._browser
        playwright = self._playwright
        self._browser = None
        self._page = None
        self._playwright = None
        self._owned = False
        try:
            discard_browser(browser, None)
        finally:
            discard_browser(None, playwright)

    def _ensure_page(self) -> None:
        if self._page is None:
            raise RuntimeError("Call start() before using ChromeTableDriver")

    def _root_attrs(self) -> dict[str, str]:
        element = self._page.query_selector(self.selectors.table_root)
        if element is None:
            raise ValueError(f"Mock table root not found: {self.selectors.table_root}")
        return read_element_attrs(element, TABLE_ATTRS)

    def _ensure_playing(self) -> None:
        attrs = self._root_attrs()
        if attrs.get("data-phase", "playing") != "between":
            return
        self._click("deal", amount=None)
        attrs = self._root_attrs()
        if attrs.get("data-phase") == "between":
            raise RuntimeError("Mock table stayed between hands after deal")

    def _click(self, action: str, *, amount: float | None) -> None:
        if not _ACTION_ID.fullmatch(action):
            raise ValueError(f"Refusing action id that is not a safe token: {action!r}")
        if amount is not None:
            self._fill_amount(amount)
        # Match data-action by equality. Do not interpolate ``action`` into a selector.
        for button in self._page.query_selector_all(self.selectors.action_buttons):
            if button.get_attribute("data-action") == action:
                button.click()
                return
        raise ValueError(f"No clickable control for action {action!r}")

    def _fill_amount(self, amount: float) -> None:
        selector = self.selectors.amount_input
        if not selector:
            raise ValueError("amount given but selectors.amount_input is empty")
        field_el = self._page.query_selector(selector)
        if field_el is None:
            raise ValueError(f"Stake input not found for selector {selector!r}")
        field_el.fill(format_stake(amount))
