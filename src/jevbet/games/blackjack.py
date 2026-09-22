"""Blackjack state and decision builder."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from rizzo_flow.schema import ChoiceQuestion, Option, Request, Strict

from ..cards import Bankroll, Card, Money
from ..choices import fail_closed_choice, pad_singleton
from ..policy import RiskPolicy

BlackjackAction = Literal["hit", "stand", "double", "split", "surrender", "insurance"]

# Surrender spends half the bet; stop-loss must not leave it as the only letter.
COSTLY_ACTIONS = frozenset({"hit", "double", "split", "insurance", "surrender"})

_ACTION_TEXT = {
    "hit": "Take one more card.",
    "stand": "Keep the current hand; take no more cards.",
    "double": "Double the bet and take exactly one more card.",
    "split": "Split a pair into two hands with an equal additional bet.",
    "surrender": "Forfeit half the bet and end the hand.",
    "insurance": "Side bet that the dealer has blackjack.",
}


class BlackjackHand(Strict):
    cards: list[Card] = Field(min_length=1, max_length=12)
    bet: Money
    is_soft: bool = False
    is_doubled: bool = False
    is_from_split: bool = False


class BlackjackState(Strict):
    game: Literal["blackjack"] = "blackjack"
    shoe_penetration: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    dealer_upcard: Card
    dealer_hole: Card | None = None
    hands: list[BlackjackHand] = Field(min_length=1, max_length=4)
    active_hand: Annotated[int, Field(ge=0, le=3)] = 0
    legal_actions: list[BlackjackAction] = Field(min_length=1, max_length=6)
    bankroll: Bankroll
    rules: dict[str, bool | int | float | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def active_in_range(self):
        if self.active_hand >= len(self.hands):
            raise ValueError("active_hand out of range")
        if len(set(self.legal_actions)) != len(self.legal_actions):
            raise ValueError("legal_actions must be unique")
        return self


def actions_after_policy(state: BlackjackState, policy: RiskPolicy) -> list[str]:
    """Legal actions after stop-loss.

    When every table action was costly, return ``["pass"]``. Never put an
    unfiltered ``legal_actions[0]`` (hit, double, …) back in front of strategy
    or the model.
    """
    actions = policy.filter_actions(
        state.bankroll, list(state.legal_actions), costly=COSTLY_ACTIONS
    )
    if not actions:
        return ["pass"]
    return actions


def build_blackjack_request(state: BlackjackState, policy: RiskPolicy | None = None) -> Request:
    policy = policy or RiskPolicy()
    actions = actions_after_policy(state, policy)
    # Pass here means the table set was emptied by policy, not a casino button.
    fail_closed = actions == ["pass"] and "pass" not in state.legal_actions
    hand = state.hands[state.active_hand]
    evidence = {
        "game": "blackjack",
        "dealer_upcard": state.dealer_upcard.label(),
        "dealer_hole_known": state.dealer_hole.label() if state.dealer_hole else None,
        "active_hand_index": state.active_hand,
        "active_hand_cards": [c.label() for c in hand.cards],
        "active_hand_bet": hand.bet,
        "active_hand_is_soft": hand.is_soft,
        "hands": [
            {
                "cards": [c.label() for c in h.cards],
                "bet": h.bet,
                "is_soft": h.is_soft,
                "is_doubled": h.is_doubled,
                "is_from_split": h.is_from_split,
            }
            for h in state.hands
        ],
        "bankroll_cash": state.bankroll.cash,
        "session_profit": state.bankroll.session_profit,
        "rules": state.rules,
        "shoe_penetration": state.shoe_penetration,
        "legal_actions_after_policy": actions,
    }
    if fail_closed:
        question = fail_closed_choice("no blackjack action left after the risk policy")
    else:
        question = ChoiceQuestion(
            type="choice",
            instructions=(
                "You are choosing the next legal blackjack action for the active hand. "
                "Prefer basic strategy adjusted for the visible dealer upcard and bankroll risk. "
                "Answer with the letter of the best option."
            ),
            options=pad_singleton(
                [
                    Option(id=a, description=_ACTION_TEXT.get(a, f"Perform action {a}."))
                    for a in actions
                ]
            ),
            policy={"allow_abstain": False},
        )
    return Request(state=evidence, questions={"action": question}, mode="shared")
