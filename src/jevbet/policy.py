"""Bankroll and risk helpers that constrain options before calling Rizzo."""

from __future__ import annotations

from .cards import Bankroll, Money


class RiskPolicy:
    """Hard limits applied to legal actions / bet sizes before the model sees them.

    The model never invents bet sizes outside this filtered set: Jevbet shrinks
    the choice set, then Rizzo scores the remaining letters.
    """

    def __init__(
        self,
        *,
        max_bet_fraction: float = 0.05,
        max_bet_absolute: Money | None = None,
        min_bet: Money = 1.0,
        forbid_all_in: bool = True,
    ):
        if not 0 < max_bet_fraction <= 1:
            raise ValueError("max_bet_fraction must be in (0, 1]")
        if min_bet < 0:
            raise ValueError("min_bet must be non-negative")
        self.max_bet_fraction = max_bet_fraction
        self.max_bet_absolute = max_bet_absolute
        self.min_bet = min_bet
        self.forbid_all_in = forbid_all_in

    def max_allowed_bet(self, bankroll: Bankroll) -> Money:
        if self.should_stop(bankroll):
            return 0.0
        cap = bankroll.cash * self.max_bet_fraction
        if self.max_bet_absolute is not None:
            cap = min(cap, self.max_bet_absolute)
        if self.forbid_all_in:
            cap = min(cap, max(0.0, bankroll.cash - self.min_bet))
        return max(0.0, float(cap))

    def should_stop(self, bankroll: Bankroll) -> bool:
        if bankroll.cash < self.min_bet:
            return True
        if bankroll.stop_loss is not None and bankroll.session_profit <= -bankroll.stop_loss:
            return True
        return bankroll.take_profit is not None and bankroll.session_profit >= bankroll.take_profit

    def filter_bet_sizes(self, bankroll: Bankroll, candidates: list[float]) -> list[float]:
        """Keep strictly positive bets within [min_bet, max_allowed] and cash."""
        if self.should_stop(bankroll):
            return []
        ceiling = min(self.max_allowed_bet(bankroll), bankroll.cash)
        kept = sorted(
            {
                float(x)
                for x in candidates
                if self.min_bet <= float(x) <= ceiling + 1e-9 and float(x) <= bankroll.cash + 1e-9
            }
        )
        return kept

    def filter_actions(
        self,
        bankroll: Bankroll,
        actions: list[str],
        *,
        costly: frozenset[str] | set[str] = frozenset(),
    ) -> list[str]:
        """Drop costly actions when the session must stop; keep free ones (fold/check/stand)."""
        if not self.should_stop(bankroll):
            return list(actions)
        return [a for a in actions if a not in costly]
