"""Scopa capture heuristic. Not a full search of the remaining deck.

Priority, among ``legal_plays`` (already the only moves the table allows):

1. A scopa if any play is marked ``is_scopa``.
2. Otherwise the capture that takes more cards (the card played counts).
3. Then more sevens, then the sette bello (7 of denari), then more denari.
4. If nothing captures, trail the lowest pip card (Fante 8, Cavallo 9, Re 10).

A stopped session (``RiskPolicy.should_stop``) passes and does not play a card.
"""

from __future__ import annotations

from ..games.scopa import ScopaState
from ..policy import RiskPolicy
from .advice import StrategyAdvice


def _capture_key(play) -> tuple | None:
    if not play.table_cards and not play.is_scopa:
        return None
    taken = [play.hand_card, *play.table_cards]
    sevens = sum(card.rank == "7" for card in taken)
    bello = any(card.rank == "7" and card.suit == "denari" for card in taken)
    denari = sum(card.suit == "denari" for card in taken)
    return (
        1 if play.is_scopa else 0,
        len(taken),
        sevens,
        1 if bello else 0,
        denari,
    )


def recommend_scopa(state: ScopaState, policy: RiskPolicy | None = None) -> StrategyAdvice:
    policy = policy or RiskPolicy(min_bet=0.0)
    if policy.should_stop(state.bankroll):
        return StrategyAdvice(
            action="pass",
            reason="risk policy says stop; pass instead of capturing or trailing",
            confidence=0.99,
            game="scopa",
        )
    plays = list(state.legal_plays[:26])
    ranked = [(index, play, _capture_key(play)) for index, play in enumerate(plays)]
    captures = [item for item in ranked if item[2] is not None]
    if captures:
        index, play, key = max(captures, key=lambda item: item[2])
        bits = []
        if key[0]:
            bits.append("scopa")
        bits.append(f"{key[1]} cards")
        if key[2]:
            bits.append(f"{key[2]} sevens")
        if key[3]:
            bits.append("sette bello")
        if key[4]:
            bits.append(f"{key[4]} denari")
        reason = f"play {play.hand_card.label()}: " + ", ".join(bits)
        alternatives = tuple(
            (f"p{other}", f"weaker capture with {play.hand_card.label()}")
            for other, play, _key in sorted(captures, key=lambda item: item[2], reverse=True)
            if other != index
        )[:3]
    else:
        index, play, _key = min(ranked, key=lambda item: (item[1].hand_card.scopa_pips(), item[0]))
        reason = f"no capture; trail lowest card {play.hand_card.label()}"
        alternatives = tuple(
            (
                f"p{other}",
                f"higher trail {other_play.hand_card.label()}",
            )
            for other, other_play, _key in sorted(
                ranked, key=lambda item: (item[1].hand_card.scopa_pips(), item[0])
            )
            if other != index
        )[:3]
    return StrategyAdvice(
        action=f"p{index}",
        reason=reason,
        confidence=0.85,
        alternatives=alternatives,
        game="scopa",
    )
