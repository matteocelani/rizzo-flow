"""Browser mock driver tests — no network, no Playwright required."""

from jevbet.browser import MockTableDriver
from jevbet.games import build_request
from rizzo_flow.schema import Request


def test_mock_blackjack_fixture_roundtrip():
    driver = MockTableDriver.from_fixture("blackjack.html")
    assert driver.legal_actions() == ["hit", "stand", "double"]
    state = driver.read_state()
    assert state["game"] == "blackjack"
    assert state["dealer_upcard"]["rank"] == "K"
    assert state["hands"][0]["cards"][0]["rank"] == "A"
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
