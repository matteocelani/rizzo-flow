"""Shared poker helpers: pot odds, 5-card rank, preflop group, draw flags.

Preflop is a complete matrix of the 169 starting hands (13 pairs, 78 suited,
78 offsuit) in the Sklansky–Malmuth groups from *Hold'em Poker for Advanced
Players* (groups 1–8 listed, group 9 = every other hand). That is a published
ordering, not a GTO solution. Postflop flags are hand classes (high pair, top
pair, overpair, overcards, OESD, gutshot, flush draw, two pair or better, set,
nuts). They are not equities from a solver.
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


# Sklansky–Malmuth groups. Keys are ``AA``, ``AKs``, ``AKo``. Group 9 is every
# starting hand that is not listed. Source: David Sklansky and Mason Malmuth,
# Hold'em Poker for Advanced Players (Two Plus Two), as reproduced by the
# standard nine-group table (thepokerbank / the book). Not a GTO ranking.
SKLANSKY_GROUPS: dict[int, frozenset[str]] = {
    1: frozenset({"AA", "AKs", "KK", "QQ", "JJ"}),
    2: frozenset({"AKo", "AQs", "AJs", "KQs", "TT"}),
    3: frozenset({"AQo", "ATs", "KJs", "QJs", "JTs", "99"}),
    4: frozenset({"AJo", "KQo", "KTs", "QTs", "J9s", "T9s", "98s", "88"}),
    5: frozenset(
        {
            "A9s",
            "A8s",
            "A7s",
            "A6s",
            "A5s",
            "A4s",
            "A3s",
            "A2s",
            "KJo",
            "QJo",
            "JTo",
            "Q9s",
            "T8s",
            "97s",
            "87s",
            "77",
            "76s",
            "66",
        }
    ),
    6: frozenset({"ATo", "KTo", "QTo", "J8s", "86s", "75s", "65s", "55", "54s"}),
    7: frozenset(
        {
            "K9s",
            "K8s",
            "K7s",
            "K6s",
            "K5s",
            "K4s",
            "K3s",
            "K2s",
            "J9o",
            "T9o",
            "98o",
            "64s",
            "53s",
            "44",
            "43s",
            "33",
            "22",
        }
    ),
    8: frozenset(
        {
            "A9o",
            "K9o",
            "Q9o",
            "J8o",
            "J7s",
            "T8o",
            "96s",
            "87o",
            "85s",
            "76o",
            "74s",
            "65o",
            "54o",
            "42s",
            "32s",
        }
    ),
}
_RANK_CHAR = {
    14: "A",
    13: "K",
    12: "Q",
    11: "J",
    10: "T",
    9: "9",
    8: "8",
    7: "7",
    6: "6",
    5: "5",
    4: "4",
    3: "3",
    2: "2",
}
_HAND_GROUP = {hand: group for group, hands in SKLANSKY_GROUPS.items() for hand in hands}


def starting_hand_key(high: int, low: int, suited: bool) -> str:
    """``AKs`` / ``AKo`` / ``AA`` from two rank values. Higher rank is written first."""
    left = _RANK_CHAR[high]
    right = _RANK_CHAR[low]
    if high == low:
        return left + right
    return left + right + ("s" if suited else "o")


def all_starting_hands() -> tuple[str, ...]:
    """The 169 French-deck starting hands, pairs then suited/offsuit under each rank."""
    ranks = "AKQJT98765432"
    hands: list[str] = []
    for index, high in enumerate(ranks):
        hands.append(high + high)
        for low in ranks[index + 1 :]:
            hands.append(f"{high}{low}s")
            hands.append(f"{high}{low}o")
    return tuple(hands)


def preflop_group(values: tuple[int, int], suited: bool) -> int:
    """Sklansky–Malmuth group 1 (strongest) through 9 (unlisted / trash).

    Ranks outside the French 2–A scale (an Italian face that is not mapped)
    are group 9. Italian poker reuses this matrix on numeric ranks
    (Asso = A, Re = T, Cavallo = 9, Fante = 8); that mapping is approximate.
    """
    high, low = sorted(values, reverse=True)
    if high not in _RANK_CHAR or low not in _RANK_CHAR:
        return 9
    return _HAND_GROUP.get(starting_hand_key(high, low, suited), 9)


def preflop_class(values: tuple[int, int], suited: bool) -> str:
    """``group N`` or ``trash`` (group 9) from two hole ranks."""
    group = preflop_group(values, suited)
    if group == 9:
        return "trash"
    return f"group {group}"


def validate_preflop_groups() -> None:
    """Groups 1–8 are disjoint, use real hand keys, and cover 83 published hands."""
    seen: dict[str, int] = {}
    legal = set(all_starting_hands())
    for group, hands in SKLANSKY_GROUPS.items():
        if group not in range(1, 9):
            raise RuntimeError(f"unexpected group {group}")
        for hand in hands:
            if hand not in legal:
                raise RuntimeError(f"{hand} is not one of the 169 starting hands")
            if hand in seen:
                raise RuntimeError(f"{hand} is in group {seen[hand]} and group {group}")
            seen[hand] = group
    if len(seen) != 83:
        raise RuntimeError(f"expected 83 listed hands, found {len(seen)}")
    if len(legal) != 169:
        raise RuntimeError(f"expected 169 starting hands, found {len(legal)}")


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
    """Made-hand and draw classes. ``kind`` is the 5-card category, or 0.

    ``high_pair`` is an overpair or top pair (exactly one pair). ``set`` is a
    pocket pair with at least one board match and three of a kind or better.
    ``two_pair_plus`` is any hero-made hand of category 2 or higher (two pair,
    trips, straight, flush, full house, quads, straight flush). ``oesd`` and
    ``gutshot`` are the straight-draw classes; a wheel missing one end counts
    as a gutshot. This is a classifier, not an equity solver.
    """
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
    board_max = max(board_vals) if board_vals else 0
    overcards = bool(board_vals) and all(value > board_max for value in hole_vals)
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
    pair_rank = hero[1] if hero and kind == 1 else None
    # Overpair: pocket pair above every board card, still exactly one pair.
    overpair = bool(pocket and board_vals and hole_vals[0] > board_max and hero_made and kind == 1)
    # Top pair: hero paired the highest board rank, and that is the whole hand.
    top_pair = bool(
        kind == 1 and hero_made and board_vals and pair_rank == board_max and board_max in hole_vals
    )
    # Set: pocket pair with at least one board match, three of a kind or better.
    set_ = bool(
        pocket and board_vals and board_vals.count(hole_vals[0]) >= 1 and hero_made and kind >= 3
    )
    two_pair_plus = bool(hero_made and kind >= 2)
    return {
        "kind": kind,
        "pair": pair and hero_made,
        "high_pair": overpair or top_pair,
        "top_pair": top_pair,
        "overpair": overpair,
        "set": set_,
        "two_pair_plus": two_pair_plus,
        "hero_made": hero_made,
        "overcards": overcards and not pair,
        "flush_draw": flush_draw,
        "straight_draw": straight,
        "oesd": straight == "oesd",
        "gutshot": straight == "gutshot",
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


validate_preflop_groups()
