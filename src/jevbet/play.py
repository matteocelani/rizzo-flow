"""Decide → act loop. Policy is applied before a click, and again after it.

The loop never reintroduces an action the builder filtered out. When the
session must stop and no hand is open, it does not deal. When a hand is open,
it may finish that hand with a free action (stand / fold / check / pass) and
then stop.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rizzo_flow.schema import Request

from .cards import Bankroll
from .choices import HOLD_POLICY, fail_close_answers, legal_ids
from .games.registry import build_request
from .policy import RiskPolicy

SAFE_TABLE_ACTIONS = frozenset({"stand", "fold", "check", "pass"})
_CHOICE_KEYS = ("action", "play", "card", "bet_type")


def _as_bankroll(data: dict) -> Bankroll:
    return Bankroll.model_validate(data)


def _primary_choice(request: Request):
    for key in _CHOICE_KEYS:
        question = request.questions.get(key)
        if question is not None and question.type == "choice":
            return key, question
    for key, question in request.questions.items():
        if question.type == "choice":
            return key, question
    raise ValueError("request has no choice question")


def _spot(state: dict) -> str:
    game = state.get("game")
    if game == "blackjack":
        index = int(state.get("active_hand") or 0)
        hand = state["hands"][index]
        cards = "".join(card["rank"] for card in hand["cards"])
        return f"{cards} vs {state['dealer_upcard']['rank']}"
    if game == "holdem":
        hole = "".join(card["rank"] for card in state.get("hole_cards", []))
        return hole
    return str(game or "")


def _amount_for(choice: str | None, answers: dict) -> float | None:
    if choice != "raise":
        return None
    numeric = answers.get("raise_amount")
    if not isinstance(numeric, dict):
        return None
    if numeric.get("status") not in {None, "ok"}:
        return None
    value = numeric.get("value")
    if value is None:
        return None
    return float(value)


def run_play_loop(
    driver,
    *,
    game: str,
    rounds: int,
    policy: RiskPolicy,
    decide: Callable[[Request], dict] | None = None,
    schema_only: bool = False,
) -> dict[str, Any]:
    """Play up to ``rounds`` decisions. Returns a JSON-serializable log.

    ``schema_only`` reads one state, builds the Rizzo request, and does not
    call ``decide`` or ``act``.
    """
    if rounds < 1 or rounds > 100:
        raise ValueError("rounds must be in 1..100")
    outcome: dict[str, Any] = {
        "game": game,
        "rounds_requested": rounds,
        "schema_only": schema_only,
        "stopped": False,
        "stop_reason": None,
        "hands": [],
    }
    for number in range(1, rounds + 1):
        info = driver.peek()
        bankroll = _as_bankroll(info["bankroll"])
        phase = info.get("phase") or "playing"
        if phase != "playing":
            if policy.should_stop(bankroll):
                outcome["stopped"] = True
                outcome["stop_reason"] = "policy"
                break
            table_min = float(info.get("table_min_bet") or 0)
            if bankroll.cash < table_min:
                outcome["stopped"] = True
                outcome["stop_reason"] = "table_minimum"
                break
        state = driver.read_state()
        request = Request.model_validate(
            build_request(state, game=game, policy=policy).model_dump()
        )
        if schema_only:
            outcome["request"] = request.model_dump()
            return outcome
        if decide is None:
            raise ValueError("decide callback is required unless schema_only is set")
        response = decide(request)
        answers = response.get("answers")
        if not isinstance(answers, dict):
            raise TypeError("decision response is missing answers")
        key, question = _primary_choice(request)
        answer = answers.get(key)
        if not isinstance(answer, dict):
            raise TypeError(f"decision response is missing answer {key!r}")
        raw_choice = answer.get("choice")
        fail_close_answers(request.questions, answers)
        post_policy = set(legal_ids(list(question.options)))
        choice = answer.get("choice")
        if choice not in post_policy or choice == HOLD_POLICY:
            choice = None
        amount = _amount_for(choice, answers)
        # A stopped session may finish the open hand, but only with a free action
        # that the builder still considers legal. Filtered actions stay filtered.
        if policy.should_stop(_as_bankroll(state["bankroll"])):
            if choice not in SAFE_TABLE_ACTIONS:
                choice = next(
                    (
                        action
                        for action in ("stand", "fold", "check", "pass")
                        if action in post_policy and action in driver.legal_actions()
                    ),
                    None,
                )
            amount = None
        legal = set(driver.legal_actions())
        applied = False
        if choice and choice in legal and choice in post_policy:
            driver.act(choice, amount=amount)
            applied = True
        spot_bankroll = _as_bankroll(state["bankroll"])
        outcome["hands"].append(
            {
                "round": number,
                "choice": choice,
                "raw_choice": raw_choice,
                "amount": amount,
                "applied": applied,
                "spot": _spot(state),
                "bankroll_cash": spot_bankroll.cash,
                "session_profit": spot_bankroll.session_profit,
                "legal_actions": list(state.get("legal_actions") or []),
            }
        )
        after = _as_bankroll(driver.peek()["bankroll"])
        if policy.should_stop(after):
            outcome["stopped"] = True
            outcome["stop_reason"] = "policy"
            break
    return outcome
