"""Blackjack state and decision builder."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from rizzo_flow.schema import ChoiceQuestion, Option, Request, Strict

from ..cards import Bankroll, Card, Money
from ..policy import RiskPolicy

BlackjackAction = Literal["hit", "stand", "double", "split", "surrender", "insurance"]

_COSTLY = frozenset({"hit", "double", "split", "insurance"})

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


def build_blackjack_request(state: BlackjackState, policy: RiskPolicy | None = None) -> Request:
    policy = policy or RiskPolicy()
    actions = policy.filter_actions(state.bankroll, list(state.legal_actions), costly=_COSTLY)
    if not actions:
        actions = ["stand"] if "stand" in state.legal_actions else [state.legal_actions[0]]
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
    options = [
        Option(id=a, description=_ACTION_TEXT.get(a, f"Perform action {a}.")) for a in actions
    ]
    if len(options) < 2:
        peer = "stand" if options[0].id != "stand" else "hit"
        options.append(Option(id=peer, description=_ACTION_TEXT.get(peer, peer)))
    return Request(
        state=evidence,
        questions={
            "action": ChoiceQuestion(
                type="choice",
                instructions=(
                    "You are choosing the next legal blackjack action for the active hand. "
                    "Prefer basic strategy adjusted for the visible dealer upcard and bankroll risk. "
                    "Answer with the letter of the best option."
                ),
                options=options,
                policy={"allow_abstain": False},
            )
        },
        mode="shared",
    )
