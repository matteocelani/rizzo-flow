"""Browser mock driver tests — no network, no Playwright required in the default path."""

import pytest

from jevbet.browser import MockTableDriver
from jevbet.games import build_request
from rizzo_flow.schema import Request


def test_mock_blackjack_fixture_roundtrip():
    driver = MockTableDriver.from_fixture("blackjack.html")
    assert driver.legal_actions() == ["hit", "stand", "double", "split"]
    state = driver.read_state()
    assert state["game"] == "blackjack"
    assert state["dealer_upcard"]["rank"] == "K"
    assert state["hands"][0]["cards"][0]["rank"] == "8"
    assert state["hands"][0]["is_soft"] is False
    assert state["bankroll"]["session_profit"] == 0
    request = Request.model_validate(build_request(state).model_dump())
    assert "action" in request.questions
    driver.act("stand")
    assert driver.history == [{"action": "stand", "amount": None}]


def test_mock_holdem_fixture_roundtrip():
    driver = MockTableDriver.from_fixture("holdem.html")
    state = driver.read_state()
    assert state["street"] == "flop"
    assert len(state["community"]) == 3
    request = Request.model_validate(build_request(state).model_dump())
    assert request.questions["action"].options
    assert "raise_amount" in request.questions
    driver.act("call", amount=20)
    assert driver.history[-1]["amount"] == 20


def test_mock_rejects_illegal_act():
    driver = MockTableDriver.from_fixture("blackjack.html")
    try:
        driver.act("surrender")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "not legal" in str(exc)


def test_chrome_driver_requires_base_url():
    from jevbet.browser import ChromeTableDriver

    try:
        ChromeTableDriver(base_url="", game="blackjack")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_from_fixture_rejects_path_escape():
    import pytest

    for name in ("../chrome.py", "/etc/passwd", "blackjack.html/../../chrome.py"):
        with pytest.raises(ValueError, match="escapes"):
            MockTableDriver.from_fixture(name)


def test_chrome_act_rejects_selector_injection():
    from jevbet.browser import ChromeTableDriver

    driver = ChromeTableDriver(base_url="http://127.0.0.1:9/mock", game="blackjack", page=object())
    try:
        driver.act("hit'] , button[data-action='fold")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "safe token" in str(exc)


def test_url_allowlist_is_loopback_by_default():
    from jevbet.browser.chrome import DEFAULT_LOCAL_PREFIXES, url_is_allowed

    assert url_is_allowed("http://127.0.0.1:8765/blackjack.html", DEFAULT_LOCAL_PREFIXES)
    assert url_is_allowed("http://localhost/holdem.html", DEFAULT_LOCAL_PREFIXES)
    assert url_is_allowed("https://127.0.0.1/", DEFAULT_LOCAL_PREFIXES)
    assert not url_is_allowed("http://127.0.0.1.evil.com/table", DEFAULT_LOCAL_PREFIXES)
    assert not url_is_allowed("http://localhost.evil.com/table", DEFAULT_LOCAL_PREFIXES)
    assert not url_is_allowed("https://example.com/table", DEFAULT_LOCAL_PREFIXES)
    assert not url_is_allowed("http://127.0.0.1:9@evil.com/path", DEFAULT_LOCAL_PREFIXES)
    widened = DEFAULT_LOCAL_PREFIXES + ("https://play.example.com/room",)
    assert url_is_allowed("https://play.example.com/room/table", widened)
    assert not url_is_allowed("https://play.example.com/room-evil", widened)
    assert not url_is_allowed("https://play.example.com.evil/room", widened)


def test_chrome_rejects_non_loopback_before_launch():
    from jevbet.browser import ChromeTableDriver

    calls = []

    def launcher():
        calls.append("launched")
        raise AssertionError("browser must not start")

    try:
        ChromeTableDriver(
            base_url="https://example.com/table",
            game="blackjack",
            _launcher=launcher,
        )
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "allowlist" in str(exc)
    assert calls == []


def test_chrome_start_closes_browser_when_navigation_fails():
    from jevbet.browser import ChromeTableDriver

    closed = []

    class Browser:
        def close(self):
            closed.append("browser")

    class Playwright:
        def stop(self):
            closed.append("playwright")

    class Page:
        def set_default_timeout(self, _timeout):
            return None

        def goto(self, *_args, **_kwargs):
            raise RuntimeError("navigation failed")

    def launcher():
        return Playwright(), Browser(), Page()

    driver = ChromeTableDriver(
        base_url="http://127.0.0.1:9/mock",
        game="blackjack",
        _launcher=launcher,
    )
    try:
        driver.start()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "navigation failed" in str(exc)
    assert closed == ["browser", "playwright"]
    assert driver._page is None
    assert driver._owned is False


class _El:
    def __init__(self, attrs):
        self.attrs = attrs
        self.filled = None
        self.clicked = False

    def get_attribute(self, name):
        return self.attrs.get(name)

    def fill(self, value):
        self.filled = value

    def click(self):
        self.clicked = True


class _Page:
    def __init__(self, found):
        self.found = found

    def query_selector(self, selector):
        return self.found.get(selector)

    def query_selector_all(self, selector):
        found = self.found.get(selector, [])
        return found if isinstance(found, list) else [found]


def test_chrome_read_state_parses_mock_blackjack_dom():
    from jevbet.browser import ChromeTableDriver, SelectorMap
    from jevbet.games import build_request
    from rizzo_flow.schema import Request

    selectors = SelectorMap()
    table = _El(
        {
            "data-game": "blackjack",
            "data-bankroll": "500",
            "data-currency": "EUR",
            "data-session-profit": "0",
            "data-bet": "25",
            "data-decks": "6",
            "data-phase": "playing",
            "data-table-min": "25",
        }
    )
    player = _El({"data-role": "player", "data-cards": "8S,8D", "data-soft": "false"})
    dealer = _El({"data-role": "dealer", "data-upcard": "KH"})
    buttons = [
        _El({"data-action": "hit"}),
        _El({"data-action": "stand"}),
        _El({"data-action": "double"}),
        _El({"data-action": "split"}),
    ]
    page = _Page(
        {
            selectors.table_root: table,
            selectors.player_cards: player,
            selectors.dealer_upcard: dealer,
            selectors.action_buttons: buttons,
        }
    )
    driver = ChromeTableDriver(
        base_url="http://127.0.0.1:9/blackjack.html", game="blackjack", page=page
    )
    state = driver.read_state()
    assert state["dealer_upcard"] == {"rank": "K", "suit": "H"}
    assert state["legal_actions"] == ["hit", "stand", "double", "split"]
    request = Request.model_validate(build_request(state).model_dump())
    assert "hit" in {option.id for option in request.questions["action"].options}
    peeked = driver.peek()
    assert peeked["phase"] == "playing"
    assert peeked["bankroll"]["cash"] == 500


def test_chrome_act_fills_stake_then_clicks():
    from jevbet.browser import ChromeTableDriver, SelectorMap

    selectors = SelectorMap()
    amount = _El({})
    fold = _El({"data-action": "fold"})
    raised = _El({"data-action": "raise"})
    page = _Page(
        {
            selectors.amount_input: amount,
            selectors.action_buttons: [fold, raised],
        }
    )
    driver = ChromeTableDriver(base_url="http://127.0.0.1:9/holdem.html", game="holdem", page=page)
    driver.act("raise", amount=30)
    assert amount.filled == "30.00"
    assert raised.clicked is True
    assert fold.clicked is False


def test_mock_server_serves_loopback_fixtures():
    import urllib.request

    import pytest

    from jevbet.browser.server import MockCasinoServer

    server = MockCasinoServer()
    server.start()
    try:
        assert server._httpd.server_address[0] == "127.0.0.1"
        url = server.url_for("blackjack.html", {"seed": "7"})
        assert url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert 'data-game="blackjack"' in body
        assert 'data-action="split"' in body
        with urllib.request.urlopen(server.url_for("holdem.html"), timeout=5) as resp:
            holdem = resp.read().decode("utf-8")
        assert "data-amount" in holdem
        with urllib.request.urlopen(server.url_for("casino.js"), timeout=5) as resp:
            assert b"mock casino" in resp.read()
        with pytest.raises(ValueError, match="Unknown"):
            server.url_for("../chrome.py")
    finally:
        server.close()


@pytest.mark.browser
def test_playwright_mock_blackjack_stand_and_redeal():
    """Opt-in: real Chromium against the loopback mock. Skips without Playwright."""
    pytest.importorskip("playwright.sync_api")
    from jevbet.browser import ChromeTableDriver
    from jevbet.browser.server import MockCasinoServer

    server = MockCasinoServer()
    server.start()
    driver = None
    try:
        driver = ChromeTableDriver(
            base_url=server.url_for("blackjack.html"),
            game="blackjack",
            headless=True,
        )
        try:
            driver.start()
        except Exception as exc:
            message = str(exc)
            if (
                "Executable doesn't exist" in message
                or "BrowserType.launch" in message
                or "playwright install" in message
            ):
                pytest.skip(message)
            raise
        state = driver.read_state()
        assert state["game"] == "blackjack"
        assert "stand" in driver.legal_actions()
        driver.act("stand")
        peeked = driver.peek()
        assert peeked["phase"] == "between"
        nxt = driver.read_state()
        assert nxt["hands"][0]["cards"]
        assert driver.peek()["phase"] == "playing"
    finally:
        if driver is not None:
            driver.close()
        server.close()
