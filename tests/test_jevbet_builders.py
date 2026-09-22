"""Unit tests for Jevbet state → Rizzo request builders and risk policy."""

import json
from pathlib import Path

import pytest

from jevbet.cards import Bankroll, Card, ItalianCard
from jevbet.games import build_request, load_game_state, register_game
from jevbet.policy import RiskPolicy
from rizzo_flow.schema import Request

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
    req = build_request(
        {"game": "toy", "legal_actions": ["x", "y"], "bankroll": {"cash": 10}},
    )
    assert req.questions["action"].options[0].id == "x"


def test_load_game_state_requires_game_id():
    with pytest.raises(ValueError, match="Missing game"):
        load_game_state({"legal_actions": ["hit", "stand"]})


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
