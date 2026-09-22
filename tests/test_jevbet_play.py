"""Play loop, mock-casino adapter, and adapter config. No Playwright, no weights."""

import json
from pathlib import Path

import pytest

from jevbet.browser.adapters import MockCasinoAdapter, load_adapter_config
from jevbet.browser.casino import MockCasinoTable
from jevbet.cards import Bankroll
from jevbet.cli import _stub_response, main
from jevbet.play import run_play_loop
from jevbet.policy import RiskPolicy
from rizzo_flow.schema import Request

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "mock-casino" / "adapter.example.json"


def test_blackjack_fake_loop_stands_three_rounds():
    adapter = MockCasinoAdapter("blackjack", seed=7, cash=500)
    driver = adapter.open()
    try:
        outcome = run_play_loop(
            driver,
            game="blackjack",
            rounds=3,
            policy=RiskPolicy(),
            decide=_stub_response,
        )
    finally:
        adapter.close()
    assert outcome["stopped"] is False
    assert [row["choice"] for row in outcome["hands"]] == ["stand", "stand", "stand"]
    assert all(row["applied"] for row in outcome["hands"])
    assert [item["action"] for item in driver.history] == ["stand", "stand", "stand"]


def test_holdem_fake_loop_calls():
    table = MockCasinoTable("holdem", seed=3, cash=400)
    outcome = run_play_loop(
        table,
        game="holdem",
        rounds=2,
        policy=RiskPolicy(),
        decide=_stub_response,
    )
    assert [row["choice"] for row in outcome["hands"]] == ["call", "call"]
    assert all(row["applied"] and row["amount"] is None for row in outcome["hands"])
    assert [item["action"] for item in table.history] == ["call", "call"]


def test_stop_loss_does_not_deal_or_hit():
    table = MockCasinoTable("blackjack", seed=1, cash=200, stop_loss=50)
    table.session_profit = -100
    seen = []

    def decide(request):
        seen.append([option.id for option in request.questions["action"].options])
        response = _stub_response(request)
        response["answers"]["action"]["choice"] = "hit"
        return response

    outcome = run_play_loop(
        table,
        game="blackjack",
        rounds=4,
        policy=RiskPolicy(),
        decide=decide,
    )
    assert outcome["stopped"] is True
    assert outcome["stop_reason"] == "policy"
    assert len(outcome["hands"]) == 1
    assert seen == [["stand", "hold_policy"]]
    assert outcome["hands"][0]["choice"] == "stand"
    assert [item["action"] for item in table.history] == ["stand"]

    idle = MockCasinoTable("blackjack", seed=1, cash=200, stop_loss=50)
    idle.phase = "between"
    idle.session_profit = -100

    def explode(_request):
        raise AssertionError("decide must not run when the session is already stopped")

    idle_outcome = run_play_loop(
        idle,
        game="blackjack",
        rounds=3,
        policy=RiskPolicy(),
        decide=explode,
    )
    assert idle_outcome["hands"] == []
    assert idle_outcome["stop_reason"] == "policy"
    assert idle.history == []


def test_table_minimum_stops_before_a_new_bet():
    table = MockCasinoTable("blackjack", seed=1, cash=500, base_bet=25)
    table.phase = "between"
    table.cash = 10

    def explode(_request):
        raise AssertionError("must not deal below the table minimum")

    outcome = run_play_loop(
        table,
        game="blackjack",
        rounds=2,
        policy=RiskPolicy(),
        decide=explode,
    )
    assert outcome["stop_reason"] == "table_minimum"
    assert outcome["hands"] == []


def test_schema_only_does_not_act():
    table = MockCasinoTable("holdem", seed=1, cash=500)
    outcome = run_play_loop(
        table,
        game="holdem",
        rounds=3,
        policy=RiskPolicy(),
        decide=None,
        schema_only=True,
    )
    Request.model_validate(outcome["request"])
    assert outcome["request"]["questions"]["action"]["type"] == "choice"
    assert table.history == []


def test_blackjack_settlement_and_split():
    table = MockCasinoTable("blackjack", seed=1, cash=100, base_bet=10)
    table.cash = 100
    table.session_profit = 0
    table.phase = "between"
    table._shoe = ["9H", "KS", "8D", "8S"]
    state = table.read_state()
    assert state["hands"][0]["cards"][0]["rank"] == "8"
    assert "split" in state["legal_actions"]
    table.act("stand")
    assert table.phase == "between"
    assert table.cash == 90
    assert table.session_profit == -10

    table.cash = 100
    table.session_profit = 0
    table.phase = "between"
    table._shoe = ["4C", "5D", "9H", "KS", "8D", "8S"]
    table.read_state()
    table.act("split")
    assert len(table.hands) == 2
    assert table.phase == "playing"
    assert table.cash == 80


def test_cli_play_fake_and_schema_only(tmp_path):
    out = tmp_path / "play.json"
    code = main(
        [
            "play",
            "--adapter",
            "mock-casino",
            "--game",
            "blackjack",
            "--rounds",
            "3",
            "--fake",
            "--output",
            str(out),
        ]
    )
    assert code == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["adapter"] == "mock-casino"
    assert body["driver"] == "in-process"
    assert len(body["hands"]) == 3
    assert body["hands"][0]["choice"] == "stand"

    schema = tmp_path / "schema.json"
    code = main(
        [
            "play",
            "--adapter",
            "mock-casino",
            "--game",
            "holdem",
            "--rounds",
            "2",
            "--schema-only",
            "--output",
            str(schema),
        ]
    )
    assert code == 0
    request = json.loads(schema.read_text(encoding="utf-8"))
    Request.model_validate(request)
    assert main(["play", "--adapter", "mock-casino", "--game", "blackjack", "--rounds", "1"]) == 2


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "Password",
        "secret",
        "api_key",
        "API_KEY",
        "apiKey",
        "token",
        "access_token",
        "cookie",
        "authorization",
        "Authorization",
        "username",
        "user",
    ],
)
def test_nested_credential_keys_are_rejected(tmp_path, key):
    """L7: credential-shaped keys are rejected anywhere, not only at the root."""
    payload = {
        "game": "blackjack",
        "base_url": "http://127.0.0.1/blackjack.html",
        "selectors": {"extra": {key: "nope"}},
    }
    path = tmp_path / "nested.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="credentials") as exc:
        load_adapter_config(path)
    assert f"selectors.extra.{key}" in str(exc.value)


def test_credential_key_inside_a_nested_list_is_rejected(tmp_path):
    payload = {
        "game": "blackjack",
        "base_url": "http://127.0.0.1/blackjack.html",
        "hooks": [{"authorization": "Bearer x"}],
    }
    path = tmp_path / "listed.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="credentials") as exc:
        load_adapter_config(path)
    assert "hooks[0].authorization" in str(exc.value)


def test_nested_non_secret_selector_extra_is_kept(tmp_path):
    payload = {
        "game": "blackjack",
        "base_url": "http://127.0.0.1/blackjack.html",
        "selectors": {"extra": {"seat_label": "hero"}},
    }
    path = tmp_path / "ok.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_adapter_config(path)
    assert loaded.selectors.extra["seat_label"] == "hero"


def test_adapter_example_is_loopback_and_rejects_secrets(tmp_path):
    config = load_adapter_config(EXAMPLE)
    assert config.game == "blackjack"
    assert config.base_url.startswith("http://127.0.0.1")
    assert config.selectors.amount_input == "input[data-amount]"

    remote = {
        "game": "blackjack",
        "base_url": "https://example.com/table",
    }
    path = tmp_path / "remote.json"
    path.write_text(json.dumps(remote), encoding="utf-8")
    with pytest.raises(ValueError, match="allowed_url_prefixes|outside"):
        load_adapter_config(path)

    secret = {
        "game": "blackjack",
        "base_url": "http://127.0.0.1/blackjack.html",
        "password": "nope",
    }
    path.write_text(json.dumps(secret), encoding="utf-8")
    with pytest.raises(ValueError, match="credentials"):
        load_adapter_config(path)

    yaml_path = tmp_path / "adapter.yaml"
    yaml_path.write_text(
        "game: blackjack\nbase_url: http://127.0.0.1/blackjack.html\n",
        encoding="utf-8",
    )
    try:
        import yaml  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError, match="JSON"):
            load_adapter_config(yaml_path)
    else:
        loaded = load_adapter_config(yaml_path)
        assert loaded.base_url.startswith("http://127.0.0.1")


def test_raise_amount_is_applied_on_the_mock_table():
    table = MockCasinoTable("holdem", seed=1, cash=200)
    assert "raise" in table.legal_actions()
    before = table.cash
    table.act("raise", amount=20)
    assert table.history[-1] == {"action": "raise", "amount": 20}
    assert table.phase == "between"
    assert table.cash != before
    bankroll = Bankroll.model_validate(table.peek()["bankroll"])
    assert bankroll.cash == table.cash
