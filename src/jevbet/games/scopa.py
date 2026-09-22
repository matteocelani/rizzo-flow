"""Scopa state and decision builder."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from rizzo_flow.schema import ChoiceQuestion, Option, Request, Strict

from ..cards import Bankroll, ItalianCard
from ..choices import pad_singleton
from ..policy import RiskPolicy


class ScopaCapture(Strict):
    """One legal play: which hand card and which table cards it would capture."""

    hand_card: ItalianCard
    table_cards: list[ItalianCard] = Field(default_factory=list, max_length=10)
    is_scopa: bool = False


class ScopaState(Strict):
    game: Literal["scopa"] = "scopa"
    hand: list[ItalianCard] = Field(min_length=1, max_length=3)
    table: list[ItalianCard] = Field(default_factory=list, max_length=10)
    captured_us: Annotated[int, Field(ge=0, le=40)] = 0
    captured_them: Annotated[int, Field(ge=0, le=40)] = 0
    legal_plays: list[ScopaCapture] = Field(min_length=1, max_length=26)
    bankroll: Bankroll
    rules: dict[str, bool | int | float | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def hand_owns_plays(self):
        hand_labels = {c.label() for c in self.hand}
        for play in self.legal_plays:
            if play.hand_card.label() not in hand_labels:
                raise ValueError(f"play uses card not in hand: {play.hand_card.label()}")
        return self


def build_scopa_request(state: ScopaState, policy: RiskPolicy | None = None) -> Request:
    del policy
    evidence = {
        "game": "scopa",
        "hand": [c.label() for c in state.hand],
        "table": [c.label() for c in state.table],
        "captured_us": state.captured_us,
        "captured_them": state.captured_them,
        "bankroll_cash": state.bankroll.cash,
        "rules": state.rules,
        "legal_plays": [
            {
                "hand_card": p.hand_card.label(),
                "table_cards": [c.label() for c in p.table_cards],
                "is_scopa": p.is_scopa,
            }
            for p in state.legal_plays
        ],
    }
    options = []
    for i, play in enumerate(state.legal_plays[:26]):
        captured = ", ".join(c.label() for c in play.table_cards) or "nothing (trail)"
        scopa = " (scopa!)" if play.is_scopa else ""
        options.append(
            Option(
                id=f"p{i}",
                description=f"Play {play.hand_card.label()} capturing {captured}{scopa}.",
            )
        )
    options = pad_singleton(options)
    return Request(
        state=evidence,
        questions={
            "play": ChoiceQuestion(
                type="choice",
                instructions=(
                    "In scopa, choose the best legal capture or trail. Prefer scopas, denari, "
                    "sette bello, and denying opponent captures. "
                    "Answer with the letter of the best option."
                ),
                options=options,
                policy={"allow_abstain": False},
            )
        },
        mode="shared",
    )
