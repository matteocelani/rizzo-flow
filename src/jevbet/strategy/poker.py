"""Shared poker helpers: pot odds, 5-card rank, preflop class, draw flags.

This is a heuristic, not a GTO solver. Hand ranks are deterministic categories
used to pick fold/call/raise. They are not equities from a neural net.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations

FRENCH_RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
FRENCH_SUITS = ("S", "H", "D", "C")
FRENCH_VALUE = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "10": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14,
}
# Poker italiano: asso high, then Re, Cavallo, Fante, then pips.
ITALIAN_VALUE = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "Fante": 8,
    "Cavallo": 9,
    "Re": 10,
    "1": 14,
}
ITALIAN_RANKS = ("1", "2", "3", "4", "5", "6", "7", "Fante", "Cavallo", "Re")
ITALIAN_SUITS = ("denari", "coppe", "spade", "bastoni")


def pot_odds(pot: float, to_call: float) -> float:
    """Price of a call: ``to_call / (pot + to_call)``. Zero when checking is free."""
    if to_call <= 0:
        return 0.0
    return float(to_call) / float(pot + to_call)


def rank5(cards: list[tuple[int, str]]) -> tuple:
    """Total order for one 5-card hand. Higher tuple wins. Ties compare equal."""
    values = sorted((card[0] for card in cards), reverse=True)
    flush = len({card[1] for card in cards}) == 1
    unique = sorted(set(values), reverse=True)
    straight = False
    straight_high = 0
    if len(unique) == 5 and unique[0] - unique[4] == 4:
        straight = True
        straight_high = unique[0]
    if set(values) == {14, 2, 3, 4, 5}:
        straight = True
        straight_high = 5
    counts = Counter(values)
    groups = sorted(((count, value) for value, count in counts.items()), reverse=True)
    if flush and straight:
        return (8, straight_high)
    if groups[0][0] == 4:
        return (7, groups[0][1], groups[1][1])
    if groups[0][0] == 3 and len(groups) > 1 and groups[1][0] == 2:
        return (6, groups[0][1], groups[1][1])
    if flush:
        return (5, tuple(values))
    if straight:
        return (4, straight_high)
    if groups[0][0] == 3:
        kickers = tuple(value for value in values if value != groups[0][1])
        return (3, groups[0][1], kickers)
    if groups[0][0] == 2 and len(groups) > 1 and groups[1][0] == 2:
        pairs = tuple(sorted((groups[0][1], groups[1][1]), reverse=True))
        kicker = next(value for value in values if value not in pairs)
        return (2, pairs, kicker)
    if groups[0][0] == 2:
        kickers = tuple(value for value in values if value != groups[0][1])
        return (1, groups[0][1], kickers)
    return (0, tuple(values))


def best_rank(cards: list[tuple[int, str]]) -> tuple | None:
    if len(cards) < 5:
        return None
    return max(rank5(list(combo)) for combo in combinations(cards, 5))


def is_nuts(
    hole: list[tuple[int, str]],
    board: list[tuple[int, str]],
    deck: list[tuple[int, str]],
) -> bool:
    """True when no other two hole cards can beat this holding on ``board``.

    Ties (the board itself is the nuts) count as the nuts: we do not fold.
    """
    if len(hole) != 2 or len(board) < 3:
        return False
    hero = best_rank(hole + board)
    if hero is None:
        return False
    used = set(hole) | set(board)
    remaining = [card for card in deck if card not in used]
    for opp in combinations(remaining, 2):
        other = best_rank(list(opp) + board)
        if other is not None and other > hero:
            return False
    return True


def french_deck() -> list[tuple[int, str]]:
    return [(FRENCH_VALUE[rank], suit) for rank in FRENCH_RANKS for suit in FRENCH_SUITS]


def italian_deck() -> list[tuple[int, str]]:
    return [(ITALIAN_VALUE[rank], suit) for rank in ITALIAN_RANKS for suit in ITALIAN_SUITS]


def preflop_class(values: tuple[int, int], suited: bool) -> str:
    """``premium`` / ``strong`` / ``speculative`` / ``trash`` from two hole ranks."""
    high, low = sorted(values, reverse=True)
    pair = high == low
    gap = high - low
    if pair and high >= 12:
        return "premium"
    if high == 14 and low == 13 and suited:
        return "premium"
    if pair and high >= 10:
        return "strong"
    if high == 14 and low == 13:
        return "strong"
    if high == 14 and low == 12:
        return "strong"
    if high == 13 and low == 12 and suited:
        return "strong"
    if pair:
        return "speculative"
    if suited and high == 14:
        return "speculative"
    if suited and gap == 1 and low >= 5:
        return "speculative"
    if suited and gap == 2 and low >= 6:
        return "speculative"
    if gap == 1 and low >= 10:
        return "speculative"
    return "trash"


def _straight_draw(hole_vals: set[int], all_vals: set[int]) -> str | None:
    ranks = set(all_vals)
    hole = set(hole_vals)
    if 14 in ranks:
        ranks.add(1)
    if 14 in hole:
        hole.add(1)
    best = None
    for start in range(1, 11):
        window = set(range(start, start + 5))
        have = ranks & window
        if len(have) != 4 or not (hole & have):
            continue
        missing = window - ranks
        gap = next(iter(missing))
        # Open-ended: the missing card is an end, and the four we hold are consecutive.
        # A wheel missing the ace or the five is open at one end only; treat as gutshot
        # unless both neighbors of a 4-run are live, which they aren't at the wheel edge.
        if gap in {start, start + 4} and start != 1:
            best = "oesd"
        elif best is None:
            best = "gutshot"
    return best


def postflop_flags(
    hole: list[tuple[int, str]],
    board: list[tuple[int, str]],
    deck: list[tuple[int, str]],
) -> dict:
    """Pair / overcards / draw / nuts flags. ``kind`` is the 5-card category or 0."""
    hole_vals = [card[0] for card in hole]
    board_vals = [card[0] for card in board]
    pocket = len(hole_vals) == 2 and hole_vals[0] == hole_vals[1]
    matched = [value for value in hole_vals if value in board_vals]
    pair = pocket or bool(matched)
    hero = best_rank(hole + board)
    board_rank = best_rank(board)
    kind = hero[0] if hero else 0
    board_kind = board_rank[0] if board_rank else 0
    hero_made = kind > board_kind or (pair and kind >= 1 and kind >= board_kind)
    overcards = bool(board_vals) and all(value > max(board_vals) for value in hole_vals)
    suits = Counter(card[1] for card in hole + board)
    flush_draw = False
    if len(board) < 5:
        for suit, count in suits.items():
            if count == 4 and any(card[1] == suit for card in hole):
                flush_draw = True
    straight = None
    if len(board) < 5 and hole_vals:
        straight = _straight_draw(set(hole_vals), set(hole_vals) | set(board_vals))
        if hero and hero[0] >= 4:
            straight = None
    return {
        "kind": kind,
        "pair": pair and hero_made,
        "hero_made": hero_made,
        "overcards": overcards and not pair,
        "flush_draw": flush_draw,
        "straight_draw": straight,
        "nuts": is_nuts(hole, board, deck),
    }


def draw_equity(flags: dict, board_len: int) -> float:
    """Fixed rough equity for a draw that is not already a made hand. Not a sim."""
    cards_left = 2 if board_len == 3 else 1 if board_len == 4 else 0
    if cards_left == 0:
        return 0.0
    flush = 0.35 if cards_left == 2 else 0.19
    oesd = 0.32 if cards_left == 2 else 0.17
    gut = 0.16 if cards_left == 2 else 0.08
    equity = 0.0
    if flags["flush_draw"]:
        equity = flush
    if flags["straight_draw"] == "oesd":
        equity = 0.50 if flags["flush_draw"] and cards_left == 2 else max(equity, oesd)
        if flags["flush_draw"] and cards_left == 1:
            equity = max(equity, 0.30)
    elif flags["straight_draw"] == "gutshot":
        equity = max(equity, 0.45 if flags["flush_draw"] and cards_left == 2 else gut)
    return equity
