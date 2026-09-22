"""Italian poker (poker italiano) state and decision builder."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from rizzo_flow.schema import ChoiceQuestion, Option, Request, Strict

from ..cards import Bankroll, ItalianCard, Money
from ..choices import pad_singleton
from ..policy import RiskPolicy

ItalianStreet = Literal["preflop", "flop", "turn", "river", "showdown"]
ItalianAction = Literal["fold", "check", "call", "raise", "pass"]

_COSTLY = frozenset({"call", "raise"})


class ItalianPokerState(Strict):
    """Poker italiano: often a short-deck / Italian-deck table game with local house rules.

    ``rules`` should record house specifics (antes, wild ranks, open vs closed).
    """

    game: Literal["italian_poker"] = "italian_poker"
    street: ItalianStreet
    hole_cards: list[ItalianCard] = Field(min_length=0, max_length=5)
    community: list[ItalianCard] = Field(default_factory=list, max_length=5)
    pot: Money
    to_call: Money
    stack: Money
    position: Annotated[str, Field(min_length=1, max_length=32)]
    num_players: Annotated[int, Field(ge=2, le=8)]
    legal_actions: list[ItalianAction] = Field(min_length=1, max_length=5)
    min_raise: Money = 0.0
    bankroll: Bankroll
    rules: dict[str, bool | int | float | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_actions(self):
        if len(set(self.legal_actions)) != len(self.legal_actions):
            raise ValueError("legal_actions must be unique")
        return self


def build_italian_poker_request(
    state: ItalianPokerState, policy: RiskPolicy | None = None
) -> Request:
    policy = policy or RiskPolicy()
    actions = policy.filter_actions(state.bankroll, list(state.legal_actions), costly=_COSTLY)
    if not actions:
        actions = ["fold"] if "fold" in state.legal_actions else [state.legal_actions[0]]
    evidence = {
        "game": "italian_poker",
        "street": state.street,
        "hole_cards": [c.label() for c in state.hole_cards],
        "community": [c.label() for c in state.community],
        "pot": state.pot,
        "to_call": state.to_call,
        "stack": state.stack,
        "position": state.position,
        "num_players": state.num_players,
        "min_raise": state.min_raise,
        "bankroll_cash": state.bankroll.cash,
        "session_profit": state.bankroll.session_profit,
        "rules": state.rules,
        "legal_actions_after_policy": actions,
    }
    text = {
        "fold": "Fold and leave the hand.",
        "check": "Check without adding chips.",
        "call": f"Call {state.to_call}.",
        "raise": f"Raise; minimum {state.min_raise}.",
        "pass": "Pass according to house rules (no bet).",
    }
    options = pad_singleton([Option(id=a, description=text.get(a, a)) for a in actions])
    return Request(
        state=evidence,
        questions={
            "action": ChoiceQuestion(
                type="choice",
                instructions=(
                    "Choose the best poker italiano action given the Italian-deck cards, "
                    "pot, and house rules in state.rules. Answer with the letter of the best option."
                ),
                options=options,
                policy={"allow_abstain": False},
            )
        },
        mode="shared",
    )
