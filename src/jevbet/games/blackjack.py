"""Blackjack state and decision builder."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from rizzo_flow.schema import ChoiceQuestion, Option, Request, Strict

from ..cards import Bankroll, Card, Money
from ..choices import fail_closed_choice, pad_singleton
from ..policy import RiskPolicy

BlackjackAction = Literal[
    "hit",
    "stand",
    "double",
    "split",
    "surrender",
    "insurance",
    "decline",
    "bet",
]

# Surrender spends half the bet; stop-loss must not leave it as the only letter.
COSTLY_ACTIONS = frozenset({"hit", "double", "split", "insurance", "surrender", "bet"})

_ACTION_TEXT = {
    "hit": "Take one more card.",
    "stand": "Keep the current hand; take no more cards.",
    "double": "Double the bet and take exactly one more card.",
    "split": "Split a pair into two hands with an equal additional bet.",
    "surrender": "Forfeit half the bet and end the hand.",
    "insurance": "Side bet that the dealer has blackjack.",
    "decline": "Decline insurance and continue the hand.",
    "bet": "Place the recommended round bet.",
}


class BlackjackHand(Strict):
    cards: list[Card] = Field(min_length=1, max_length=12)
    bet: Money
    is_soft: bool = False
    is_doubled: bool = False
    is_from_split: bool = False
    is_split_aces: bool = False
    stood: bool = False
    resolved: bool = False


class BlackjackState(Strict):
    game: Literal["blackjack"] = "blackjack"
    shoe_penetration: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    dealer_upcard: Card
    dealer_hole: Card | None = None
    hands: list[BlackjackHand] = Field(min_length=1, max_length=8)
    active_hand: Annotated[int, Field(ge=0, le=7)] = 0
    legal_actions: list[BlackjackAction] = Field(min_length=1, max_length=8)
    bankroll: Bankroll
    rules: dict[str, bool | int | float | str] = Field(default_factory=dict)
    # Lifecycle / capability flags (optional; derived when omitted).
    can_double: bool | None = None
    can_split: bool | None = None
    can_resplit: bool | None = None
    can_insurance: bool | None = None
    cards_dealt_this_hand: Annotated[int, Field(ge=0, le=416)] | None = None
    cards_seen: Annotated[int, Field(ge=0, le=416)] | None = None
    running_count: int | None = None
    true_count: Annotated[float, Field(allow_inf_nan=False)] | None = None
    decks_remaining: Annotated[float, Field(allow_inf_nan=False, gt=0)] | None = None
    phase: Literal["betting", "insurance", "playing", "between"] | None = None
    discarded: list[Card] = Field(default_factory=list)
    last_round_result: Literal["win", "loss", "push"] | None = None
    martingale_step: Annotated[int, Field(ge=0, le=32)] = 0
    bet_unit: Money | None = None

    @model_validator(mode="after")
    def active_in_range(self):
        if self.active_hand >= len(self.hands):
            raise ValueError("active_hand out of range")
        if len(set(self.legal_actions)) != len(self.legal_actions):
            raise ValueError("legal_actions must be unique")
        return self


def max_hands(rules: dict) -> int:
    raw = rules.get("resplit", rules.get("max_hands", 4))
    try:
        return max(2, min(8, int(raw)))
    except (TypeError, ValueError):
        return 4


def resplit_aces_allowed(rules: dict) -> bool:
    return bool(rules.get("resplit_aces", False))


def hit_split_aces_allowed(rules: dict) -> bool:
    return bool(rules.get("hit_split_aces", False))


def das_allowed(rules: dict) -> bool:
    if "das" not in rules:
        return True
    return bool(rules["das"])


def derive_capabilities(state: BlackjackState) -> dict[str, bool]:
    """Lifecycle flags for the active hand. Explicit state fields win when set."""
    hand = state.hands[state.active_hand]
    n_cards = len(hand.cards)
    two = n_cards == 2
    ranks = [card.rank for card in hand.cards]
    is_pair = two and (
        ranks[0] == ranks[1]
        or (ranks[0] in {"10", "J", "Q", "K"} and ranks[1] in {"10", "J", "Q", "K"})
    )
    # Split aces: one card each, no further hit/double/resplit unless rules say so.
    split_aces = bool(hand.is_split_aces)
    can_hit = True
    can_double = two
    if hand.is_from_split and not das_allowed(state.rules):
        can_double = False
    can_split = is_pair and len(state.hands) < max_hands(state.rules)
    if is_pair and ranks[0] == "A" and (hand.is_from_split or split_aces):
        can_split = can_split and resplit_aces_allowed(state.rules)
    if split_aces and not hit_split_aces_allowed(state.rules):
        can_hit = False
        can_double = False
        if not resplit_aces_allowed(state.rules):
            can_split = False
    can_resplit = can_split and len(state.hands) >= 1 and is_pair
    dealer_ace = state.dealer_upcard.rank == "A"
    can_insurance = dealer_ace and two and not hand.is_from_split and len(state.hands) == 1
    if state.phase == "insurance":
        can_insurance = True
    if state.can_double is not None:
        can_double = state.can_double
    if state.can_split is not None:
        can_split = state.can_split
    if state.can_resplit is not None:
        can_resplit = state.can_resplit
    if state.can_insurance is not None:
        can_insurance = state.can_insurance
    return {
        "can_double": bool(can_double),
        "can_split": bool(can_split),
        "can_resplit": bool(can_resplit),
        "can_insurance": bool(can_insurance),
        "can_hit": bool(can_hit),
        "can_surrender": bool(two and not hand.is_from_split and len(state.hands) == 1),
    }


def filter_actions_by_lifecycle(state: BlackjackState, actions: list[str]) -> list[str]:
    """Drop double/split/surrender/insurance when lifecycle flags forbid them."""
    caps = derive_capabilities(state)
    kept: list[str] = []
    for action in actions:
        if action == "double" and not caps["can_double"]:
            continue
        if action == "split" and not (caps["can_split"] or caps["can_resplit"]):
            continue
        if action == "surrender" and not caps["can_surrender"]:
            continue
        if action == "insurance" and not caps["can_insurance"]:
            continue
        if action == "hit" and not caps["can_hit"]:
            continue
        kept.append(action)
    return kept


def actions_after_policy(state: BlackjackState, policy: RiskPolicy) -> list[str]:
    """Legal actions after stop-loss and lifecycle gates.

    When every table action was costly, return ``["pass"]``. Never put an
    unfiltered ``legal_actions[0]`` (hit, double, …) back in front of strategy
    or the model.
    """
    raw = filter_actions_by_lifecycle(state, list(state.legal_actions))
    actions = policy.filter_actions(state.bankroll, raw, costly=COSTLY_ACTIONS)
    if not actions:
        return ["pass"]
    return actions


def build_blackjack_request(state: BlackjackState, policy: RiskPolicy | None = None) -> Request:
    policy = policy or RiskPolicy()
    actions = actions_after_policy(state, policy)
    # Pass here means the table set was emptied by policy, not a casino button.
    fail_closed = actions == ["pass"] and "pass" not in state.legal_actions
    hand = state.hands[state.active_hand]
    caps = derive_capabilities(state)
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
                "is_split_aces": h.is_split_aces,
            }
            for h in state.hands
        ],
        "bankroll_cash": state.bankroll.cash,
        "session_profit": state.bankroll.session_profit,
        "rules": state.rules,
        "shoe_penetration": state.shoe_penetration,
        "cards_dealt_this_hand": state.cards_dealt_this_hand,
        "cards_seen": state.cards_seen,
        "running_count": state.running_count,
        "true_count": state.true_count,
        "phase": state.phase,
        "capabilities": caps,
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
