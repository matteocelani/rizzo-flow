"""Tre sette trick heuristic. Must-follow is already ``legal_cards``.

Card order for taking a trick (high to low): Asso, 3, Re, Cavallo, Fante, 7,
6, 5, 4, 2. Trump beats a non-trump. This is not partnership signalling.

- If the trick is empty, lead the lowest card and avoid spending trump.
- If a legal card wins the trick, play the lowest one that does (a small card
  of the lead suit beats a trump that would also win).
- If nothing wins, dump the lowest card, saving trump when a non-trump exists.

A stopped session passes.
"""

from __future__ import annotations

from ..cards import ItalianCard
from ..games.tre_sette import TreSetteState
from ..policy import RiskPolicy
from .advice import StrategyAdvice

# Higher wins a trick in the same suit.
_STRENGTH = {
    "2": 1,
    "4": 2,
    "5": 3,
    "6": 4,
    "7": 5,
    "Fante": 6,
    "Cavallo": 7,
    "Re": 8,
    "3": 9,
    "1": 10,
}


def option_id(index: int, card: ItalianCard) -> str:
    """Same id the request builder assigns: ``c{i}_{rank}_{suit}``."""
    return f"c{index}_{card.rank}_{card.suit}"


def _beats(card: ItalianCard, other: ItalianCard, trump: str | None) -> bool:
    card_trumps = trump is not None and card.suit == trump
    other_trumps = trump is not None and other.suit == trump
    if card_trumps and not other_trumps:
        return True
    if other_trumps and not card_trumps:
        return False
    if card.suit != other.suit:
        return False
    return _STRENGTH[card.rank] > _STRENGTH[other.rank]


def _cost(card: ItalianCard, trump: str | None) -> tuple[int, int]:
    """Lower is cheaper to spend: non-trump before trump, then weaker rank."""
    return (1 if trump and card.suit == trump else 0, _STRENGTH[card.rank])


def _current_best(trick: list[ItalianCard], trump: str | None) -> ItalianCard:
    best = trick[0]
    for card in trick[1:]:
        if _beats(card, best, trump):
            best = card
    return best


def recommend_tre_sette(state: TreSetteState, policy: RiskPolicy | None = None) -> StrategyAdvice:
    policy = policy or RiskPolicy(min_bet=0.0)
    if policy.should_stop(state.bankroll):
        return StrategyAdvice(
            action="pass",
            reason="risk policy says stop; pass instead of playing a card",
            confidence=0.99,
            game="tre_sette",
        )
    legal = list(state.legal_cards)
    trump = state.trump_suit
    if not state.trick:
        index = min(range(len(legal)), key=lambda i: (_cost(legal[i], trump), i))
        card = legal[index]
        reason = f"leading; play lowest card {card.label()}"
    else:
        best = _current_best(list(state.trick), trump)
        winners = [i for i, card in enumerate(legal) if _beats(card, best, trump)]
        if winners:
            index = min(winners, key=lambda i: (_cost(legal[i], trump), i))
            card = legal[index]
            reason = f"win the trick over {best.label()} with lowest sufficient card {card.label()}"
        else:
            index = min(range(len(legal)), key=lambda i: (_cost(legal[i], trump), i))
            card = legal[index]
            reason = f"cannot win the trick; dump lowest card {card.label()}"
    alternatives = tuple(
        (option_id(i, legal[i]), f"also legal: {legal[i].label()}")
        for i in range(len(legal))
        if i != index
    )[:3]
    return StrategyAdvice(
        action=option_id(index, card),
        reason=reason,
        confidence=0.86,
        alternatives=alternatives,
        game="tre_sette",
    )
