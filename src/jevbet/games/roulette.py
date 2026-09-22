"""Roulette state and decision builder."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from rizzo_flow.schema import ChoiceQuestion, NumericQuestion, Option, Request, Strict

from ..cards import Bankroll, Money
from ..choices import pad_singleton
from ..policy import RiskPolicy

RouletteBetType = Literal[
    "straight_up",
    "split",
    "street",
    "corner",
    "sixline",
    "column",
    "dozen",
    "red",
    "black",
    "odd",
    "even",
    "low",
    "high",
    "pass",
]


class RouletteState(Strict):
    game: Literal["roulette"] = "roulette"
    wheel: Literal["european", "american"] = "european"
    last_results: list[Annotated[int, Field(ge=0, le=37)]] = Field(
        default_factory=list, max_length=20
    )
    legal_bet_types: list[RouletteBetType] = Field(min_length=1, max_length=14)
    chip_values: list[Money] = Field(min_length=1, max_length=12)
    min_bet: Money = 1.0
    max_bet: Money | None = None
    bankroll: Bankroll
    rules: dict[str, bool | int | float | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_types(self):
        if len(set(self.legal_bet_types)) != len(self.legal_bet_types):
            raise ValueError("legal_bet_types must be unique")
        if len(set(self.chip_values)) != len(self.chip_values):
            raise ValueError("chip_values must be unique")
        return self


_BET_TEXT = {
    "straight_up": "Single number (35:1).",
    "split": "Two adjacent numbers (17:1).",
    "street": "Row of three (11:1).",
    "corner": "Four numbers (8:1).",
    "sixline": "Two rows / six numbers (5:1).",
    "column": "One of three columns (2:1).",
    "dozen": "1-12, 13-24, or 25-36 (2:1).",
    "red": "Red even-money bet.",
    "black": "Black even-money bet.",
    "odd": "Odd even-money bet.",
    "even": "Even even-money bet.",
    "low": "1-18 even-money bet.",
    "high": "19-36 even-money bet.",
    "pass": "Skip this spin; place no bet.",
}


def offers_after_policy(state: RouletteState, policy: RiskPolicy) -> tuple[list[str], list[float]]:
    """Bet types and chip sizes after stop-loss.

    A stopped session offers only ``pass``, even when the table omitted it.
    """
    if policy.should_stop(state.bankroll):
        return ["pass"], []
    chips = policy.filter_bet_sizes(state.bankroll, list(state.chip_values))
    if state.max_bet is not None:
        chips = [c for c in chips if c <= state.max_bet + 1e-9]
    return list(state.legal_bet_types), chips


def build_roulette_request(state: RouletteState, policy: RiskPolicy | None = None) -> Request:
    policy = policy or RiskPolicy(min_bet=state.min_bet)
    types, chips = offers_after_policy(state, policy)
    evidence = {
        "game": "roulette",
        "wheel": state.wheel,
        "last_results": state.last_results,
        "bankroll_cash": state.bankroll.cash,
        "session_profit": state.bankroll.session_profit,
        "min_bet": state.min_bet,
        "max_bet": state.max_bet,
        "rules": state.rules,
        "legal_bet_types_after_policy": types,
        "chip_values_after_policy": chips,
    }
    options = pad_singleton(
        [Option(id=t.replace("-", "_"), description=_BET_TEXT.get(t, t)) for t in types]
    )
    questions: dict = {
        "bet_type": ChoiceQuestion(
            type="choice",
            instructions=(
                "Choose a roulette bet type for the next spin. Even-money bets have lower variance; "
                "inside bets have higher payouts and higher risk. When the bankroll policy has "
                "stopped the session the only legal action is pass — do not stake chips. "
                "Answer with the letter of the best option."
            ),
            options=options,
            policy={"allow_abstain": False},
        )
    }
    if len(chips) >= 2:
        if len(chips) == 2:
            anchors = [
                {"value": chips[0], "description": f"Small stake of {chips[0]}."},
                {"value": chips[-1], "description": f"Large stake of {chips[-1]}."},
            ]
        else:
            anchors = [
                {"value": chips[0], "description": f"Small stake of {chips[0]}."},
                {
                    "value": chips[len(chips) // 2],
                    "description": f"Medium stake of {chips[len(chips) // 2]}.",
                },
                {"value": chips[-1], "description": f"Large stake of {chips[-1]}."},
            ]
        questions["bet_amount"] = NumericQuestion(
            type="numeric",
            instructions="How many chips (currency units) should this bet stake?",
            unit=state.bankroll.currency,
            anchors=anchors,
            policy={"allow_abstain": True},
        )
    return Request(state=evidence, questions=questions, mode="shared")
