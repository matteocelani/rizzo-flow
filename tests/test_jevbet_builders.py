"""Unit tests for Jevbet state → Rizzo request builders and risk policy."""

import json
from pathlib import Path

import pytest

from jevbet.cards import Bankroll, Card, ItalianCard
from jevbet.choices import HOLD_POLICY
from jevbet.games import build_request, list_games, load_game_state, register_game, unregister_game
from jevbet.policy import RiskPolicy
from rizzo_flow.schema import Request


@pytest.fixture(autouse=True)
def unregister_extra_games():
    """Restore the game registry after every test (L1). Built-ins stay put."""
    from jevbet.games import registry as reg

    canonical = dict(reg._CANONICAL)
    games = dict(reg.GAMES)
    yield
    reg._CANONICAL.clear()
    reg._CANONICAL.update(canonical)
    reg.GAMES.clear()
    reg.GAMES.update(games)


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "games"


@pytest.mark.parametrize(
    "name",
    ["blackjack", "holdem", "italian_poker", "tre_sette", "scopa", "roulette"],
)
def test_examples_build_valid_requests(name):
    payload = json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))
    request = build_request(payload)
    validated = Request.model_validate(request.model_dump())
    assert validated.questions
    assert validated.state["game"] in {
        "blackjack",
        "texas_holdem",
        "italian_poker",
        "tre_sette",
        "scopa",
        "roulette",
    }


def test_blackjack_choice_ids_match_legal_actions():
    payload = json.loads((EXAMPLES / "blackjack.json").read_text(encoding="utf-8"))
    request = build_request(payload)
    ids = {o.id for o in request.questions["action"].options}
    assert {"hit", "stand", "double"} <= ids


def test_risk_policy_filters_bets_and_stop_loss():
    policy = RiskPolicy(max_bet_fraction=0.1, min_bet=5, max_bet_absolute=50)
    bankroll = Bankroll(cash=200, session_profit=0)
    assert policy.max_allowed_bet(bankroll) == 20.0
    assert policy.filter_bet_sizes(bankroll, [1, 5, 10, 25, 100]) == [5.0, 10.0]
    stopped = Bankroll(cash=200, session_profit=-80, stop_loss=50)
    assert policy.should_stop(stopped)
    assert policy.filter_actions(stopped, ["hit", "stand", "double"], costly={"hit", "double"}) == [
        "stand"
    ]


def test_card_parsing():
    assert Card.parse("as").label() == "AS"
    assert Card.parse("10h").label() == "10H"
    assert ItalianCard.parse("7-denari").label() == "7-denari"
    assert ItalianCard.parse("Re/spade").rank == "Re"


def test_register_game_extension_point():
    from typing import Literal

    from rizzo_flow.schema import ChoiceQuestion, Option, Request, Strict

    class ToyState(Strict):
        game: Literal["toy"] = "toy"
        legal_actions: list[str]
        bankroll: Bankroll

    def build_toy(state: ToyState, policy=None):
        del policy
        return Request(
            state={"game": "toy"},
            questions={
                "action": ChoiceQuestion(
                    type="choice",
                    instructions="Pick.",
                    options=[Option(id=a, description=a) for a in state.legal_actions[:2]]
                    or [
                        Option(id="a", description="a"),
                        Option(id="b", description="b"),
                    ],
                    policy={"allow_abstain": False},
                )
            },
        )

    register_game("toy", ToyState, build_toy)
    assert "toy" in list_games()
    req = build_request(
        {"game": "toy", "legal_actions": ["x", "y"], "bankroll": {"cash": 10}},
    )
    assert req.questions["action"].options[0].id == "x"
    unregister_game("toy")
    assert "toy" not in list_games()
    with pytest.raises(ValueError, match="built-in"):
        unregister_game("blackjack")
    with pytest.raises(ValueError, match="Unknown game"):
        build_request({"game": "toy", "legal_actions": ["x", "y"], "bankroll": {"cash": 10}})


def test_load_game_state_requires_game_id():
    with pytest.raises(ValueError, match="Missing game"):
        load_game_state({"legal_actions": ["hit", "stand"]})


def test_stop_loss_never_reintroduces_filtered_actions():
    """A single remaining action is paired with a sentinel, never a dropped move."""
    from jevbet.choices import HOLD_POLICY, fail_close_answers, resolve_choice
    from jevbet.cli import _stub_response

    blackjack = json.loads((EXAMPLES / "blackjack.json").read_text(encoding="utf-8"))
    blackjack["bankroll"]["session_profit"] = -80
    blackjack["bankroll"]["stop_loss"] = 50
    request = build_request(blackjack, policy=RiskPolicy())
    ids = [option.id for option in request.questions["action"].options]
    assert ids == ["stand", HOLD_POLICY]
    assert "hit" not in ids and "double" not in ids
    stub = _stub_response(request)
    assert stub["answers"]["action"]["choice"] == "stand"
    # Model (or a bad stub) picking the sentinel still publishes the legal action.
    stub["answers"]["action"]["choice"] = HOLD_POLICY
    fail_close_answers(request.questions, stub["answers"])
    assert stub["answers"]["action"]["choice"] == "stand"
    assert resolve_choice("hit", ["stand"]) == "stand"

    holdem = json.loads((EXAMPLES / "holdem.json").read_text(encoding="utf-8"))
    holdem["bankroll"]["session_profit"] = -80
    holdem["bankroll"]["stop_loss"] = 50
    request = build_request(holdem, policy=RiskPolicy())
    ids = [option.id for option in request.questions["action"].options]
    assert ids[0] == "fold"
    assert HOLD_POLICY in ids
    assert "call" not in ids and "raise" not in ids
    assert _stub_response(request)["answers"]["action"]["choice"] == "fold"


def test_roulette_stop_loss_passes_instead_of_a_costly_bet():
    """L6: a stopped session must not keep the first stake type."""
    roulette = json.loads((EXAMPLES / "roulette.json").read_text(encoding="utf-8"))
    roulette["legal_bet_types"] = ["straight_up", "red"]
    roulette["bankroll"]["session_profit"] = -80
    roulette["bankroll"]["stop_loss"] = 50
    request = build_request(roulette, policy=RiskPolicy())
    ids = [option.id for option in request.questions["bet_type"].options]
    assert ids == ["pass", HOLD_POLICY]
    assert "bet_amount" not in request.questions
    assert "straight_up" not in ids and "red" not in ids


def test_scopa_and_tre_sette_honor_stop_with_pass():
    """L3: should_stop yields a no-play pass. The default policy does not delete itself."""
    scopa = json.loads((EXAMPLES / "scopa.json").read_text(encoding="utf-8"))
    playing = [option.id for option in build_request(scopa).questions["play"].options]
    assert "p0" in playing
    assert "pass" not in playing
    stopped = build_request(scopa, policy=RiskPolicy())
    assert [option.id for option in stopped.questions["play"].options] == ["pass", HOLD_POLICY]

    scopa["bankroll"]["cash"] = 100
    scopa["bankroll"]["session_profit"] = -40
    scopa["bankroll"]["stop_loss"] = 20
    stopped = build_request(scopa, policy=RiskPolicy(min_bet=0))
    assert [option.id for option in stopped.questions["play"].options] == ["pass", HOLD_POLICY]
    assert stopped.state["policy_stop"] is True

    tre = json.loads((EXAMPLES / "tre_sette.json").read_text(encoding="utf-8"))
    playing = [option.id for option in build_request(tre).questions["card"].options]
    assert any(option_id.startswith("c") for option_id in playing)
    tre["bankroll"]["cash"] = 50
    tre["bankroll"]["session_profit"] = -15
    tre["bankroll"]["stop_loss"] = 10
    stopped = build_request(tre, policy=RiskPolicy(min_bet=0))
    assert [option.id for option in stopped.questions["card"].options] == ["pass", HOLD_POLICY]


def _option_ids(request):
    return [option.id for option in request.questions["action"].options]


def test_empty_filtered_actions_offer_pass_not_the_first_legal_move():
    """L8: an empty post-policy set must not resurrect legal_actions[0]."""
    blackjack = json.loads((EXAMPLES / "blackjack.json").read_text(encoding="utf-8"))
    blackjack["legal_actions"] = ["hit", "double"]
    blackjack["bankroll"]["session_profit"] = -80
    blackjack["bankroll"]["stop_loss"] = 50
    request = build_request(blackjack, policy=RiskPolicy())
    assert _option_ids(request) == ["pass", HOLD_POLICY]
    assert request.state["legal_actions_after_policy"] == ["pass"]
    Request.model_validate(request.model_dump())

    still_open = json.loads((EXAMPLES / "blackjack.json").read_text(encoding="utf-8"))
    still_open["legal_actions"] = ["hit"]
    open_request = build_request(still_open, policy=RiskPolicy())
    assert open_request.questions["action"].options[0].id == "hit"

    holdem = json.loads((EXAMPLES / "holdem.json").read_text(encoding="utf-8"))
    holdem["legal_actions"] = ["call", "raise"]
    holdem["bankroll"]["session_profit"] = -80
    holdem["bankroll"]["stop_loss"] = 50
    request = build_request(holdem, policy=RiskPolicy())
    assert _option_ids(request) == ["pass", HOLD_POLICY]
    assert "raise_amount" not in request.questions
    assert request.state["legal_actions_after_policy"] == ["pass"]

    holdem["legal_actions"] = ["all_in"]
    holdem["bankroll"]["session_profit"] = 0
    holdem["bankroll"].pop("stop_loss", None)
    blocked = build_request(holdem, policy=RiskPolicy(forbid_all_in=True))
    assert _option_ids(blocked) == ["pass", HOLD_POLICY]
    allowed = build_request(holdem, policy=RiskPolicy(forbid_all_in=False))
    assert allowed.questions["action"].options[0].id == "all_in"

    italian = json.loads((EXAMPLES / "italian_poker.json").read_text(encoding="utf-8"))
    italian["legal_actions"] = ["call", "raise"]
    italian["bankroll"]["session_profit"] = -40
    italian["bankroll"]["stop_loss"] = 20
    request = build_request(italian, policy=RiskPolicy())
    assert _option_ids(request) == ["pass", HOLD_POLICY]
    assert "call" not in _option_ids(request)
    Request.model_validate(request.model_dump())


def test_singleton_games_use_sentinel_not_a_fake_move():
    from jevbet.choices import HOLD_POLICY

    roulette = json.loads((EXAMPLES / "roulette.json").read_text(encoding="utf-8"))
    roulette["legal_bet_types"] = ["red"]
    ids = [o.id for o in build_request(roulette).questions["bet_type"].options]
    assert ids == ["red", HOLD_POLICY]

    scopa = json.loads((EXAMPLES / "scopa.json").read_text(encoding="utf-8"))
    scopa["legal_plays"] = [scopa["legal_plays"][0]]
    ids = [o.id for o in build_request(scopa).questions["play"].options]
    assert ids == ["p0", HOLD_POLICY]
    assert "p_alt" not in ids


def test_cli_schema_only(tmp_path):
    from jevbet.cli import main

    out = tmp_path / "req.json"
    code = main(
        [
            "decide",
            str(EXAMPLES / "blackjack.json"),
            "--schema-only",
            "--output",
            str(out),
        ]
    )
    assert code == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    Request.model_validate(body)
    assert body["questions"]["action"]["type"] == "choice"
