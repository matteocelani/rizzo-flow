"""Tre sette state and decision builder."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from rizzo_flow.schema import ChoiceQuestion, Option, Request, Strict

from ..cards import Bankroll, ItalianCard
from ..policy import RiskPolicy

TreSetteAction = Literal["play_card", "pass"]


class TreSetteState(Strict):
    game: Literal["tre_sette"] = "tre_sette"
    hand: list[ItalianCard] = Field(min_length=1, max_length=10)
    trump_suit: Literal["denari", "coppe", "spade", "bastoni"] | None = None
    lead_suit: Literal["denari", "coppe", "spade", "bastoni"] | None = None
    trick: list[ItalianCard] = Field(default_factory=list, max_length=4)
    partner_known: bool = False
    points_us: Annotated[int, Field(ge=0, le=21)] = 0
    points_them: Annotated[int, Field(ge=0, le=21)] = 0
    legal_cards: list[ItalianCard] = Field(min_length=1, max_length=10)
    legal_actions: list[TreSetteAction] = Field(default_factory=lambda: ["play_card"])
    bankroll: Bankroll
    rules: dict[str, bool | int | float | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def cards_legal(self):
        hand_labels = {c.label() for c in self.hand}
        for card in self.legal_cards:
            if card.label() not in hand_labels:
                raise ValueError(f"legal card {card.label()} is not in hand")
        return self


def build_tre_sette_request(state: TreSetteState, policy: RiskPolicy | None = None) -> Request:
    del policy  # card games without chip bets still carry bankroll for session stops
    cards = state.legal_cards
    evidence = {
        "game": "tre_sette",
        "hand": [c.label() for c in state.hand],
        "trump_suit": state.trump_suit,
        "lead_suit": state.lead_suit,
        "trick": [c.label() for c in state.trick],
        "partner_known": state.partner_known,
        "points_us": state.points_us,
        "points_them": state.points_them,
        "bankroll_cash": state.bankroll.cash,
        "rules": state.rules,
        "legal_cards": [c.label() for c in cards],
    }
    # Option IDs must match schema pattern: alphanumeric + _-
    options = []
    for i, card in enumerate(cards):
        options.append(
            Option(
                id=f"c{i}_{card.rank}_{card.suit}",
                description=f"Play {card.label()} from hand.",
            )
        )
    if len(options) < 2:
        options.append(
            Option(
                id="hold_tempo", description="No alternate legal card; keep tempo (forced play)."
            )
        )
    return Request(
        state=evidence,
        questions={
            "card": ChoiceQuestion(
                type="choice",
                instructions=(
                    "In tre sette, choose which legal card to play. Follow suit when required, "
                    "value aces and threes highly, and track the trump suit. "
                    "Answer with the letter of the best option."
                ),
                options=options,
                policy={"allow_abstain": False},
            )
        },
        mode="shared",
    )
