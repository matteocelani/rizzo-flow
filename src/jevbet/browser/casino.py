"""In-process mock casino used by the play loop when Chromium is not required.

The tables are intentionally small: one blackjack hand at a time (hit, stand,
double, split) and one Texas Hold'em street (fold, check, call, raise). They
are not a rules certification of either game. ``--browser`` drives the HTML
pages in ``fixtures/`` instead; this module lets ``--fake`` run in CI.
"""

from __future__ import annotations

import random
from typing import Any

from ..cards import Card
from .driver import TableDriver

_RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
_SUITS = ("S", "H", "D", "C")


def _money(value: float) -> float:
    rounded = round(float(value), 2)
    if rounded == 0:
        return 0.0
    return rounded


def hand_total(labels: list[str]) -> tuple[int, bool]:
    """Return ``(total, soft)``. Soft means an ace is still counted as 11."""
    total = 0
    aces = 0
    for label in labels:
        rank = label[:-1]
        if rank == "A":
            aces += 1
            total += 11
        elif rank in {"10", "J", "Q", "K"}:
            total += 10
        else:
            total += int(rank)
    soft_aces = aces
    while total > 21 and soft_aces:
        total -= 10
        soft_aces -= 1
    return total, soft_aces > 0


def _card(label: str) -> dict[str, str]:
    parsed = Card.parse(label)
    return {"rank": parsed.rank, "suit": parsed.suit}


class MockCasinoTable(TableDriver):
    """Stateful blackjack or holdem table. ``read_state`` deals when idle."""

    def __init__(
        self,
        game: str,
        *,
        seed: int = 7,
        cash: float = 500.0,
        stop_loss: float | None = None,
        base_bet: float = 25.0,
    ):
        if game not in {"blackjack", "holdem"}:
            raise ValueError(f"Mock casino has no table for game {game!r}")
        self.game = game
        self.rng = random.Random(seed)
        self.cash = _money(cash)
        self.session_profit = 0.0
        self.stop_loss = stop_loss
        self.currency = "EUR"
        self.base_bet = _money(base_bet)
        self.history: list[dict[str, Any]] = []
        self._shoe: list[str] = []
        self.phase = "between"
        self.hands: list[list[str]] = []
        self.bets: list[float] = []
        self.active = 0
        self.dealer: list[str] = []
        self.hole: list[str] = []
        self.board: list[str] = []
        self.street = "flop"
        self.pot = 0.0
        self.to_call = 0.0
        self.min_raise = 0.0
        self.raise_suggestions: list[float] = []
        self._start_hand()

    def peek(self) -> dict[str, Any]:
        table_min = self.base_bet if self.game == "blackjack" else 0.0
        return {
            "phase": self.phase,
            "bankroll": self._bankroll(),
            "table_min_bet": table_min,
        }

    def read_state(self) -> dict[str, Any]:
        if self.phase != "playing":
            self._start_hand()
        if self.phase != "playing":
            raise RuntimeError(
                "Mock table has no playable hand (bankroll is below the table minimum)"
            )
        return self._state_dict()

    def legal_actions(self) -> list[str]:
        if self.phase != "playing":
            return []
        if self.game == "holdem":
            actions = ["fold"]
            if self.to_call <= 1e-9:
                actions.append("check")
            elif self.cash + 1e-9 >= self.to_call:
                actions.append("call")
            if self.min_raise > 0 and self.cash + 1e-9 >= self.min_raise:
                actions.append("raise")
            return actions
        hand = self.hands[self.active]
        actions = ["hit", "stand"]
        if len(hand) == 2 and self.cash + 1e-9 >= self.bets[self.active]:
            actions.append("double")
            same_rank = hand[0][:-1] == hand[1][:-1]
            if len(self.hands) == 1 and same_rank:
                actions.append("split")
        return actions

    def act(self, action: str, *, amount: float | None = None) -> None:
        legal = self.legal_actions()
        if action not in legal:
            raise ValueError(f"Action {action!r} is not legal: {legal}")
        self.history.append({"action": action, "amount": amount})
        if self.game == "blackjack":
            self._act_blackjack(action)
        else:
            self._act_holdem(action, amount)

    def _start_hand(self) -> None:
        if self.game == "blackjack":
            self._deal_blackjack()
        else:
            self._deal_holdem()

    def _draw(self) -> str:
        if not self._shoe:
            deck = [f"{rank}{suit}" for _ in range(4) for rank in _RANKS for suit in _SUITS]
            self.rng.shuffle(deck)
            self._shoe = deck
        return self._shoe.pop()

    def _deal_blackjack(self) -> None:
        if self.cash + 1e-9 < self.base_bet:
            self.phase = "between"
            return
        self.cash = _money(self.cash - self.base_bet)
        bet = self.base_bet
        self.hands = [[self._draw(), self._draw()]]
        self.bets = [bet]
        self.active = 0
        self.dealer = [self._draw(), self._draw()]
        self.phase = "playing"

    def _act_blackjack(self, action: str) -> None:
        if action == "hit":
            self.hands[self.active].append(self._draw())
            if hand_total(self.hands[self.active])[0] > 21:
                self._finish_active_hand()
            return
        if action == "stand":
            self._finish_active_hand()
            return
        if action == "double":
            extra = self.bets[self.active]
            self.cash = _money(self.cash - extra)
            self.bets[self.active] = _money(extra * 2)
            self.hands[self.active].append(self._draw())
            self._finish_active_hand()
            return
        if action == "split":
            extra = self.bets[self.active]
            self.cash = _money(self.cash - extra)
            first, second = self.hands[0]
            self.hands = [[first, self._draw()], [second, self._draw()]]
            self.bets = [extra, extra]
            self.active = 0
            return
        raise ValueError(f"Unsupported blackjack action {action!r}")

    def _finish_active_hand(self) -> None:
        if self.active + 1 < len(self.hands):
            self.active += 1
            return
        self._settle_blackjack()

    def _settle_blackjack(self) -> None:
        player_live = any(hand_total(hand)[0] <= 21 for hand in self.hands)
        opening = self.dealer[:2]
        dealer_has_natural = len(opening) == 2 and hand_total(opening)[0] == 21
        if player_live and not dealer_has_natural:
            guard = 0
            while hand_total(self.dealer)[0] < 17 and guard < 12:
                self.dealer.append(self._draw())
                guard += 1
        dealer_total, _ = hand_total(self.dealer)
        single_hand = len(self.hands) == 1
        for hand, bet in zip(self.hands, self.bets, strict=True):
            total, _ = hand_total(hand)
            player_natural = single_hand and len(hand) == 2 and total == 21
            if total > 21 or (dealer_total <= 21 and total < dealer_total):
                self.session_profit = _money(self.session_profit - bet)
            elif player_natural and not dealer_has_natural:
                self.cash = _money(self.cash + bet * 2.5)
                self.session_profit = _money(self.session_profit + bet * 1.5)
            elif dealer_total > 21 or total > dealer_total:
                self.cash = _money(self.cash + bet * 2)
                self.session_profit = _money(self.session_profit + bet)
            else:
                self.cash = _money(self.cash + bet)
        self.cash = _money(self.cash)
        self.session_profit = _money(self.session_profit)
        self.phase = "between"

    def _deal_holdem(self) -> None:
        self.hole = [self._draw(), self._draw()]
        self.board = [self._draw(), self._draw(), self._draw()]
        self.street = "flop"
        self.pot = 60.0
        self.to_call = 20.0
        self.min_raise = 20.0
        self.raise_suggestions = [20.0, 40.0, 60.0]
        self.phase = "playing"

    def _act_holdem(self, action: str, amount: float | None) -> None:
        if action in {"fold", "check"}:
            self.phase = "between"
            return
        if action == "call":
            pay = _money(min(self.to_call, self.cash))
            self.cash = _money(self.cash - pay)
            if self.rng.random() < 0.45:
                self.cash = _money(self.cash + self.pot + pay)
                self.session_profit = _money(self.session_profit + self.pot)
            else:
                self.session_profit = _money(self.session_profit - pay)
            self.phase = "between"
            return
        if action == "raise":
            pay = self.min_raise if amount is None else _money(float(amount))
            if pay + 1e-9 < self.min_raise or pay > self.cash + 1e-9:
                raise ValueError(f"raise amount {pay} is outside {self.min_raise}..{self.cash}")
            self.cash = _money(self.cash - pay)
            if self.rng.random() < 0.45:
                self.cash = _money(self.cash + self.pot + pay + pay)
                self.session_profit = _money(self.session_profit + self.pot + pay)
            else:
                self.session_profit = _money(self.session_profit - pay)
            self.phase = "between"
            return
        raise ValueError(f"Unsupported holdem action {action!r}")

    def _bankroll(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "cash": _money(self.cash),
            "currency": self.currency,
            "session_profit": _money(self.session_profit),
        }
        if self.stop_loss is not None:
            data["stop_loss"] = float(self.stop_loss)
        return data

    def _state_dict(self) -> dict[str, Any]:
        if self.game == "blackjack":
            return {
                "game": "blackjack",
                "dealer_upcard": _card(self.dealer[0]),
                "hands": [
                    {
                        "cards": [_card(label) for label in hand],
                        "bet": bet,
                        "is_soft": hand_total(hand)[1],
                    }
                    for hand, bet in zip(self.hands, self.bets, strict=True)
                ],
                "active_hand": self.active,
                "legal_actions": self.legal_actions(),
                "bankroll": self._bankroll(),
                "rules": {"decks": 4, "dealer_stands_soft_17": True},
            }
        return {
            "game": "holdem",
            "street": self.street,
            "hole_cards": [_card(label) for label in self.hole],
            "community": [_card(label) for label in self.board],
            "pot": self.pot,
            "to_call": self.to_call,
            "stack": _money(self.cash),
            "position": "BTN",
            "num_players": 6,
            "legal_actions": self.legal_actions(),
            "min_raise": self.min_raise,
            "raise_suggestions": list(self.raise_suggestions),
            "bankroll": self._bankroll(),
            "rules": {"small_blind": 1, "big_blind": 2},
        }
