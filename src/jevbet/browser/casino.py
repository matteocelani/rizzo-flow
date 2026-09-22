"""In-process mock casino used by the play loop when Chromium is not required.

Blackjack supports a full hand lifecycle: deal → optional insurance → act each
hand (including split / resplit / split aces) → settle → next round. Hold'em is
still one street. Not a rules certification of either game.
"""

from __future__ import annotations

import random
from typing import Any

from ..cards import Bankroll, Card
from ..games.blackjack import das_allowed, hit_split_aces_allowed, max_hands, resplit_aces_allowed
from ..policy import RiskPolicy
from ..strategy.betting import next_progression_step, normalize_bet_system, recommend_bet
from ..strategy.count import counting_enabled, hi_lo_tag, true_count
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


def _rank(label: str) -> str:
    return label[:-1]


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
        rules: dict[str, Any] | None = None,
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
        self.from_split: list[bool] = []
        self.split_aces: list[bool] = []
        self.doubled: list[bool] = []
        self.active = 0
        self.dealer: list[str] = []
        self.hole: list[str] = []
        self.board: list[str] = []
        self.street = "flop"
        self.pot = 0.0
        self.to_call = 0.0
        self.min_raise = 0.0
        self.raise_suggestions: list[float] = []
        self.rules: dict[str, Any] = {
            "decks": 4,
            "dealer_stands_soft_17": True,
            "das": True,
            "resplit": 4,
            "resplit_aces": False,
            "hit_split_aces": False,
            "counting": "off",
            "bet_system": "flat",
            "bet_unit": base_bet,
            "table_min": base_bet,
            **(rules or {}),
        }
        self.running_count = 0
        self.cards_seen = 0
        self.cards_dealt_this_hand = 0
        self.discarded: list[str] = []
        self.last_round_result: str | None = None
        self.martingale_step = 0
        self.pending_bet: float | None = None
        self.insurance_bet = 0.0
        self._start_hand()

    def peek(self) -> dict[str, Any]:
        table_min = self.base_bet if self.game == "blackjack" else 0.0
        return {
            "phase": self.phase,
            "bankroll": self._bankroll(),
            "table_min_bet": table_min,
        }

    def read_state(self) -> dict[str, Any]:
        if self.phase == "between":
            self._start_hand()
        if self.phase not in {"playing", "insurance", "betting"}:
            raise RuntimeError(
                "Mock table has no playable hand (bankroll is below the table minimum)"
            )
        return self._state_dict()

    def legal_actions(self) -> list[str]:
        if self.phase == "betting":
            return ["bet"]
        if self.phase == "insurance":
            return ["insurance", "decline"]
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
        return self._blackjack_legal()

    def act(self, action: str, *, amount: float | None = None) -> None:
        legal = self.legal_actions()
        if action not in legal:
            raise ValueError(f"Action {action!r} is not legal: {legal}")
        self.history.append({"action": action, "amount": amount})
        if self.game == "blackjack":
            self._act_blackjack(action, amount)
        else:
            self._act_holdem(action, amount)

    def _start_hand(self) -> None:
        if self.game == "blackjack":
            self._prepare_blackjack_round()
        else:
            self._deal_holdem()

    def _draw(self) -> str:
        if not self._shoe:
            decks = max(1, int(self.rules.get("decks") or 4))
            deck = [f"{rank}{suit}" for _ in range(decks) for rank in _RANKS for suit in _SUITS]
            self.rng.shuffle(deck)
            self._shoe = deck
            if counting_enabled(self.rules):
                self.running_count = 0
                self.cards_seen = 0
                self.discarded = []
        label = self._shoe.pop()
        self.cards_seen += 1
        self.cards_dealt_this_hand += 1
        self.running_count += hi_lo_tag(_rank(label))
        return label

    def _prepare_blackjack_round(self) -> None:
        bankroll = Bankroll(
            cash=self.cash,
            session_profit=self.session_profit,
            stop_loss=self.stop_loss,
        )
        advice = recommend_bet(
            bankroll,
            true_count=self._true_count() if counting_enabled(self.rules) else None,
            rules=self.rules,
            policy=RiskPolicy(min_bet=float(self.rules.get("table_min") or self.base_bet)),
            last_result=self.last_round_result,
            step=self.martingale_step,
        )
        bet = advice.amount if advice.amount > 0 else self.base_bet
        if self.pending_bet is not None:
            bet = self.pending_bet
            self.pending_bet = None
        if self.cash + 1e-9 < bet or bet <= 0:
            self.phase = "between"
            return
        self.cards_dealt_this_hand = 0
        self.cash = _money(self.cash - bet)
        self.hands = [[self._draw(), self._draw()]]
        self.bets = [bet]
        self.from_split = [False]
        self.split_aces = [False]
        self.doubled = [False]
        self.active = 0
        self.dealer = [self._draw(), self._draw()]
        self.insurance_bet = 0.0
        if _rank(self.dealer[0]) == "A":
            self.phase = "insurance"
        else:
            self.phase = "playing"
            self._check_player_blackjack()

    def _check_player_blackjack(self) -> None:
        if len(self.hands) == 1 and len(self.hands[0]) == 2 and hand_total(self.hands[0])[0] == 21:
            self._settle_blackjack()

    def _blackjack_legal(self) -> list[str]:
        hand = self.hands[self.active]
        total, _ = hand_total(hand)
        if total >= 21:
            return ["stand"]
        actions = ["hit", "stand"]
        two = len(hand) == 2
        split_aces = self.split_aces[self.active]
        if split_aces and not hit_split_aces_allowed(self.rules):
            return ["stand"]
        if two and self.cash + 1e-9 >= self.bets[self.active]:
            if das_allowed(self.rules) or not self.from_split[self.active]:
                actions.append("double")
            same = _rank(hand[0]) == _rank(hand[1])
            tens = _rank(hand[0]) in {"10", "J", "Q", "K"} and _rank(hand[1]) in {
                "10",
                "J",
                "Q",
                "K",
            }
            if (same or tens) and len(self.hands) < max_hands(self.rules):
                if _rank(hand[0]) == "A" and (self.from_split[self.active] or split_aces):
                    if resplit_aces_allowed(self.rules):
                        actions.append("split")
                else:
                    actions.append("split")
        return actions

    def _act_blackjack(self, action: str, amount: float | None) -> None:
        if action == "bet":
            self.pending_bet = None if amount is None else _money(float(amount))
            self.phase = "between"
            self._prepare_blackjack_round()
            return
        if action == "insurance":
            side = _money(self.bets[0] / 2)
            if self.cash + 1e-9 >= side:
                self.cash = _money(self.cash - side)
                self.insurance_bet = side
            self.phase = "playing"
            if hand_total(self.dealer)[0] == 21:
                self.cash = _money(self.cash + self.insurance_bet * 3)
                self.session_profit = _money(self.session_profit + self.insurance_bet * 2)
                self._settle_blackjack()
            else:
                self.session_profit = _money(self.session_profit - self.insurance_bet)
                self.insurance_bet = 0.0
                self._check_player_blackjack()
            return
        if action == "decline":
            self.phase = "playing"
            if hand_total(self.dealer)[0] == 21:
                self._settle_blackjack()
            else:
                self._check_player_blackjack()
            return
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
            self.doubled[self.active] = True
            self.hands[self.active].append(self._draw())
            self._finish_active_hand()
            return
        if action == "split":
            self._split_active()
            return
        raise ValueError(f"Unsupported blackjack action {action!r}")

    def _split_active(self) -> None:
        extra = self.bets[self.active]
        self.cash = _money(self.cash - extra)
        first, second = self.hands[self.active]
        ace_split = _rank(first) == "A"
        left = [first, self._draw()]
        right = [second, self._draw()]
        self.hands[self.active] = left
        self.hands.insert(self.active + 1, right)
        self.bets[self.active] = extra
        self.bets.insert(self.active + 1, extra)
        self.from_split[self.active] = True
        self.from_split.insert(self.active + 1, True)
        self.split_aces[self.active] = ace_split
        self.split_aces.insert(self.active + 1, ace_split)
        self.doubled[self.active] = False
        self.doubled.insert(self.active + 1, False)
        if ace_split and not hit_split_aces_allowed(self.rules):
            self._finish_active_hand()
            if self.phase == "playing":
                self._finish_active_hand()

    def _finish_active_hand(self) -> None:
        if self.active + 1 < len(self.hands):
            self.active += 1
            return
        self._settle_blackjack()

    def _settle_blackjack(self) -> None:
        player_live = any(hand_total(hand)[0] <= 21 for hand in self.hands)
        opening = self.dealer[:2]
        dealer_has_natural = len(opening) == 2 and hand_total(opening)[0] == 21
        hits_soft = not bool(self.rules.get("dealer_stands_soft_17", True))
        if "dealer_hits_soft_17" in self.rules:
            hits_soft = bool(self.rules["dealer_hits_soft_17"])
        if player_live and not dealer_has_natural:
            guard = 0
            while guard < 12:
                total, soft = hand_total(self.dealer)
                if total > 17:
                    break
                if total == 17 and soft and hits_soft:
                    self.dealer.append(self._draw())
                    guard += 1
                    continue
                if total >= 17:
                    break
                self.dealer.append(self._draw())
                guard += 1
        dealer_total, _ = hand_total(self.dealer)
        single_hand = len(self.hands) == 1
        net = 0.0
        for hand, bet in zip(self.hands, self.bets, strict=True):
            total, _ = hand_total(hand)
            player_natural = single_hand and len(hand) == 2 and total == 21
            if total > 21 or (dealer_total <= 21 and total < dealer_total):
                net -= bet
            elif player_natural and not dealer_has_natural:
                self.cash = _money(self.cash + bet * 2.5)
                net += bet * 1.5
            elif dealer_total > 21 or total > dealer_total:
                self.cash = _money(self.cash + bet * 2)
                net += bet
            else:
                self.cash = _money(self.cash + bet)
        self.session_profit = _money(self.session_profit + net)
        self.cash = _money(self.cash)
        if net > 0:
            self.last_round_result = "win"
        elif net < 0:
            self.last_round_result = "loss"
        else:
            self.last_round_result = "push"
        self.martingale_step = next_progression_step(
            normalize_bet_system(str(self.rules.get("bet_system") or "flat")),
            last_result=self.last_round_result,
            step=self.martingale_step,
            rules=self.rules,
        )
        self.discarded.extend(card for hand in self.hands for card in hand)
        self.discarded.extend(self.dealer)
        self.phase = "between"

    def _true_count(self) -> float:
        decks = max(1, int(self.rules.get("decks") or 4))
        left = max(0.25, (decks * 52 - self.cards_seen) / 52.0)
        return true_count(self.running_count, left)

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
                        "is_from_split": from_split,
                        "is_split_aces": split_aces,
                        "is_doubled": doubled,
                    }
                    for hand, bet, from_split, split_aces, doubled in zip(
                        self.hands,
                        self.bets,
                        self.from_split,
                        self.split_aces,
                        self.doubled,
                        strict=True,
                    )
                ],
                "active_hand": self.active,
                "legal_actions": self.legal_actions(),
                "bankroll": self._bankroll(),
                "rules": dict(self.rules),
                "phase": self.phase,
                "can_double": "double" in self.legal_actions(),
                "can_split": "split" in self.legal_actions(),
                "can_resplit": "split" in self.legal_actions() and len(self.hands) > 1,
                "can_insurance": self.phase == "insurance",
                "cards_dealt_this_hand": self.cards_dealt_this_hand,
                "cards_seen": self.cards_seen,
                "running_count": self.running_count,
                "true_count": self._true_count(),
                "decks_remaining": max(
                    0.25, (int(self.rules.get("decks") or 4) * 52 - self.cards_seen) / 52.0
                ),
                "last_round_result": self.last_round_result,
                "martingale_step": self.martingale_step,
                "bet_unit": float(self.rules.get("bet_unit") or self.base_bet),
                "shoe_penetration": min(
                    1.0, self.cards_seen / max(1, int(self.rules.get("decks") or 4) * 52)
                ),
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
