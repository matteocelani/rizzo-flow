"""Texas Hold'em state and decision builder."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from rizzo_flow.schema import ChoiceQuestion, NumericQuestion, Option, Request, Strict

from ..cards import Bankroll, Card, Money
from ..choices import pad_singleton
from ..policy import RiskPolicy

Street = Literal["preflop", "flop", "turn", "river"]
HoldemAction = Literal["fold", "check", "call", "raise", "all_in"]

_COSTLY = frozenset({"call", "raise", "all_in"})


class HoldemState(Strict):
    game: Literal["holdem"] = "holdem"
    street: Street
    hole_cards: list[Card] = Field(min_length=0, max_length=2)
    community: list[Card] = Field(min_length=0, max_length=5)
    pot: Money
    to_call: Money
    stack: Money
    position: Annotated[str, Field(min_length=1, max_length=32)]
    num_players: Annotated[int, Field(ge=2, le=10)]
    legal_actions: list[HoldemAction] = Field(min_length=1, max_length=5)
    min_raise: Money = 0.0
    max_raise: Money | None = None
    raise_suggestions: list[Money] = Field(default_factory=list)
    bankroll: Bankroll
    rules: dict[str, bool | int | float | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent(self):
        if len(set(self.legal_actions)) != len(self.legal_actions):
            raise ValueError("legal_actions must be unique")
        expected = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[self.street]
        # Allow incomplete DOM reads; still reject too many community cards.
        if self.street != "preflop" and len(self.community) > expected:
            raise ValueError(f"Too many community cards for {self.street}")
        return self


def build_holdem_request(state: HoldemState, policy: RiskPolicy | None = None) -> Request:
    policy = policy or RiskPolicy()
    actions = policy.filter_actions(state.bankroll, list(state.legal_actions), costly=_COSTLY)
    if policy.forbid_all_in:
        actions = [a for a in actions if a != "all_in"]
    if not actions:
        actions = ["fold"] if "fold" in state.legal_actions else [state.legal_actions[0]]

    evidence = {
        "game": "texas_holdem",
        "street": state.street,
        "hole_cards": [c.label() for c in state.hole_cards],
        "community": [c.label() for c in state.community],
        "pot": state.pot,
        "to_call": state.to_call,
        "stack": state.stack,
        "position": state.position,
        "num_players": state.num_players,
        "min_raise": state.min_raise,
        "max_raise": state.max_raise,
        "bankroll_cash": state.bankroll.cash,
        "session_profit": state.bankroll.session_profit,
        "rules": state.rules,
        "legal_actions_after_policy": actions,
    }
    options = []
    for action in actions:
        if action == "fold":
            desc = "Fold and surrender the pot."
        elif action == "check":
            desc = "Check; put no more chips in."
        elif action == "call":
            desc = f"Call {state.to_call} to match the current bet."
        elif action == "raise":
            desc = f"Raise; minimum {state.min_raise}."
        else:
            desc = "Move all-in with the remaining stack."
        options.append(Option(id=action, description=desc))
    options = pad_singleton(options)

    questions = {
        "action": ChoiceQuestion(
            type="choice",
            instructions=(
                "Choose the best Texas Hold'em action given hole cards, board, pot odds, "
                "position, and stack depth. Answer with the letter of the best option."
            ),
            options=options,
            policy={"allow_abstain": False},
        )
    }

    if "raise" in actions:
        suggestions = list(state.raise_suggestions) or [
            state.min_raise,
            max(state.min_raise, state.pot * 0.5),
            max(state.min_raise, state.pot),
            max(state.min_raise, state.pot * 2),
        ]
        if state.max_raise is not None:
            suggestions = [s for s in suggestions if s <= state.max_raise + 1e-9]
        sizes = policy.filter_bet_sizes(state.bankroll, suggestions)
        sizes = [s for s in sizes if s <= state.stack + 1e-9]
        ceiling = min(policy.max_allowed_bet(state.bankroll), state.stack)
        if not sizes and state.min_raise > 0 and state.min_raise <= ceiling + 1e-9:
            sizes = [float(state.min_raise)]
        if len(sizes) == 1 and ceiling > sizes[0] + 1e-9:
            sizes.append(float(ceiling))
        if len(sizes) >= 2:
            if len(sizes) == 2:
                anchors = [
                    {"value": sizes[0], "description": f"Small raise of {sizes[0]} chips."},
                    {"value": sizes[-1], "description": f"Large raise of {sizes[-1]} chips."},
                ]
            else:
                anchors = [
                    {"value": sizes[0], "description": f"Small raise of {sizes[0]} chips."},
                    {
                        "value": sizes[len(sizes) // 2],
                        "description": f"Medium raise of {sizes[len(sizes) // 2]} chips.",
                    },
                    {"value": sizes[-1], "description": f"Large raise of {sizes[-1]} chips."},
                ]
            questions["raise_amount"] = NumericQuestion(
                type="numeric",
                instructions=(
                    "If raising, how many chips should the raise be (total raise size)? "
                    "Prefer sizes that preserve stack for later streets."
                ),
                unit="chips",
                anchors=anchors,
                policy={"allow_abstain": True},
            )

    return Request(state=evidence, questions=questions, mode="shared")
