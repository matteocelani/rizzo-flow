"""Turn strategy advice (and an optional model report) into a decision response.

The response keeps the Rizzo answer shape the play loop already applies.
When ``source`` is ``strategy``, the choice is the strategy action even if a
model response was attached for its probabilities.
"""

from __future__ import annotations

import copy

from rizzo_flow.schema import Request

from ..choices import HOLD_POLICY
from .advice import StrategyAdvice

_CHOICE_KEYS = ("action", "play", "card", "bet_type")


def should_use_model(
    advice: StrategyAdvice, advisor: str, *, model_available: bool, rules: dict
) -> bool:
    """True when the published action should be the model's, not the chart's."""
    if advisor == "strategy_only":
        return False
    if advisor == "llm":
        return model_available
    if advisor != "strategy":
        raise ValueError(f"unknown advisor {advisor!r}")
    if not model_available:
        return False
    if rules.get("model_override"):
        return True
    return not advice.confident


def primary_choice(request: Request):
    for key in _CHOICE_KEYS:
        question = request.questions.get(key)
        if question is not None and question.type == "choice":
            return key, question
    for key, question in request.questions.items():
        if question.type == "choice":
            return key, question
    raise ValueError("request has no choice question")


def _choice_answer(question, choice: str) -> dict:
    probs = {option.id: (1.0 if option.id == choice else 0.0) for option in question.options}
    return {
        "type": "choice",
        "status": "ok",
        "choice": choice,
        "probabilities": probs,
        "option_logits": {
            option.id: (10.0 if option.id == choice else 0.0) for option in question.options
        },
        "legend": {option.id: option.description for option in question.options},
        "uncertainty": {
            "top_probability": 1.0,
            "entropy_nats": 0.0,
            "concentration": 1.0,
            "unavailable_probability": 0.0,
        },
        "probability_status": "uncalibrated_conditional_option_scores",
        "temperature": 1.0,
        "prompt_sha256": "jevbet-strategy",
        "input_tokens": 0,
    }


def _numeric_answer(question, value: float) -> dict:
    return {
        "type": "numeric",
        "status": "ok",
        "value": value,
        "probabilities": {
            str(anchor.value): (1.0 if anchor.value == value else 0.0)
            for anchor in question.anchors
        },
        "option_logits": {str(anchor.value): 0.0 for anchor in question.anchors},
        "legend": {str(anchor.value): anchor.description for anchor in question.anchors},
        "uncertainty": {
            "top_probability": 1.0,
            "entropy_nats": 0.0,
            "concentration": 1.0,
            "unavailable_probability": 0.0,
        },
        "probability_status": "uncalibrated_conditional_option_scores",
        "temperature": 1.0,
        "prompt_sha256": "jevbet-strategy",
        "input_tokens": 0,
        "unit": question.unit,
        "statistics_given_available": None,
        "support": [question.anchors[0].value, question.anchors[-1].value],
    }


def _closest(anchors: list[float], target: float) -> float:
    return float(min(anchors, key=lambda value: abs(value - target)))


def _apply_size(response: dict, request: Request, advice: StrategyAdvice) -> None:
    if advice.size is None or advice.action in {None, "pass", "fold", "check", "stand"}:
        return
    for key in ("raise_amount", "bet_amount"):
        question = request.questions.get(key)
        if question is None or question.type != "numeric":
            continue
        anchors = [anchor.value for anchor in question.anchors]
        value = _closest(anchors, advice.size)
        response["answers"][key] = _numeric_answer(question, value)
        return


def compose_response(
    request: Request,
    advice: StrategyAdvice,
    model_response: dict | None,
    *,
    source: str,
) -> dict:
    """Publish ``advice.action`` unless ``source`` is ``model``."""
    key, question = primary_choice(request)
    legal = [option.id for option in question.options if option.id != HOLD_POLICY]
    action = advice.action if advice.action in legal else (legal[0] if legal else None)
    model_choice = None
    if model_response is not None:
        response = copy.deepcopy(model_response)
        answer = response.setdefault("answers", {}).get(key)
        if isinstance(answer, dict):
            model_choice = answer.get("choice")
        else:
            response.setdefault("answers", {})[key] = _choice_answer(question, action or legal[0])
    else:
        response = {
            "model": {"fingerprint": "jevbet-strategy"},
            "mode": request.mode,
            "answers": {key: _choice_answer(question, action or legal[0])},
            "calibration": None,
            "timing": {"generated_tokens": 0, "total_seconds": 0.0},
        }
    if source == "strategy" and action is not None:
        response["answers"][key]["choice"] = action
        response["answers"][key]["status"] = "ok"
        _apply_size(response, request, advice)
    block = advice.as_dict()
    block["source"] = source
    block["model_choice"] = model_choice
    response["strategy"] = block
    return response
