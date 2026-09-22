"""Texas Hold'em heuristic. Not a GTO solution.

Preflop is the complete Sklansky–Malmuth matrix (all 169 starting hands) plus
documented pot-odds thresholds. Postflop uses pot odds plus deterministic
classes: high pair, top pair, overpair, overcards, open-ended straight draw,
gutshot, flush draw, two pair or better, set, and nuts. Raise sizes are chosen
only from ``filtered_raise_sizes`` (already inside RiskPolicy).
"""

from __future__ import annotations

from ..cards import Card
from ..games.holdem import HoldemState, actions_after_policy, filtered_raise_sizes
from ..policy import RiskPolicy
from .advice import StrategyAdvice
from .poker import (
    FRENCH_VALUE,
    draw_equity,
    french_deck,
    postflop_flags,
    pot_odds,
    preflop_group,
    starting_hand_key,
)

# Documented continue/raise prices by Sklansky–Malmuth group. Not a GTO chart.
# ``price`` is ``to_call / (pot + to_call)``. Group 9 never continues.
MAX_CONTINUE_PRICE = {
    1: 1.0,
    2: 0.45,
    3: 0.35,
    4: 0.28,
    5: 0.22,
    6: 0.16,
    7: 0.12,
    8: 0.08,
    9: 0.0,
}
# Facing a bet, these groups raise when the price is at or under the cutoff.
RAISE_PRICE = {1: 0.40, 2: 0.25, 3: 0.15}
# Unopened pot: groups 1–4 raise from any seat; 5–6 also raise from late seats.
OPEN_GROUPS = frozenset({1, 2, 3, 4})
LATE_OPEN_GROUPS = frozenset({5, 6})
LATE_POSITIONS = frozenset({"BTN", "BU", "BUTTON", "CO", "CUTOFF", "HJ", "HIJACK"})


def _cards(cards: list[Card]) -> list[tuple[int, str]]:
    return [(FRENCH_VALUE[card.rank], card.suit) for card in cards]


def _pick_size(sizes: list[float], bias: str) -> float | None:
    if not sizes:
        return None
    if bias == "large":
        return float(sizes[-1])
    if bias == "medium":
        return float(sizes[len(sizes) // 2])
    return float(sizes[0])


def _finish(
    action: str,
    reason: str,
    confidence: float,
    *,
    alternatives: tuple[tuple[str, str], ...] = (),
    size: float | None = None,
) -> StrategyAdvice:
    return StrategyAdvice(
        action=action,
        reason=reason,
        confidence=confidence,
        alternatives=alternatives,
        game="holdem",
        size=size,
    )


def _fallback(legal: list[str]) -> str:
    for action in ("pass", "check", "fold"):
        if action in legal:
            return action
    return legal[0]


def recommend_holdem(state: HoldemState, policy: RiskPolicy | None = None) -> StrategyAdvice:
    policy = policy or RiskPolicy()
    legal = actions_after_policy(state, policy)
    if legal == ["pass"]:
        return _finish(
            "pass",
            "risk policy left no free holdem action; pass "
            "(do not resurrect a costly legal_actions entry)",
            0.99,
        )
    sizes = filtered_raise_sizes(state, policy, legal)
    price = pot_odds(state.pot, state.to_call)
    if len(state.hole_cards) != 2:
        action = _fallback(legal)
        return _finish(
            action,
            "need two hole cards for the heuristic; taking a free or folding action",
            0.4,
        )
    hole = _cards(state.hole_cards)
    if state.street == "preflop" or not state.community:
        return _preflop(state, hole, legal, sizes, price)
    return _postflop(state, hole, _cards(state.community), legal, sizes, price, french_deck())


def _late(position: str) -> bool:
    return position.strip().upper() in LATE_POSITIONS


def _preflop(state, hole, legal, sizes, price) -> StrategyAdvice:
    high, low = sorted((hole[0][0], hole[1][0]), reverse=True)
    suited = hole[0][1] == hole[1][1]
    group = preflop_group((high, low), suited)
    try:
        name = starting_hand_key(high, low, suited)
    except KeyError:
        name = "unknown"
    band = "trash" if group == 9 else f"group {group}"
    label = f"{name} {band} from {state.position}"
    odds = f"pot odds {price:.2f}"
    ceiling = MAX_CONTINUE_PRICE[group]
    if state.to_call <= 0:
        open_raise = group in OPEN_GROUPS or (group in LATE_OPEN_GROUPS and _late(state.position))
        if open_raise and "raise" in legal and sizes:
            return _finish(
                "raise",
                f"{label}; open-raise ({odds})",
                0.90 if group <= 2 else 0.82,
                alternatives=(("check", "check if the raise is declined"),)
                if "check" in legal
                else (),
                size=_pick_size(sizes, "medium" if group == 1 else "small"),
            )
        if "check" in legal:
            return _finish("check", f"{label}; check the unopened pot ({odds})", 0.84)
        return _finish(_fallback(legal), f"{label}; no free check ({odds})", 0.75)
    if group <= 3 and price <= RAISE_PRICE[group] and "raise" in legal and sizes:
        return _finish(
            "raise",
            f"{label}; raise a priced bet ({odds})",
            0.90 if group == 1 else 0.84,
            alternatives=(("call", "call if the raise size is declined"),)
            if "call" in legal
            else (),
            size=_pick_size(sizes, "medium" if group == 1 else "small"),
        )
    if "call" in legal and price <= ceiling + 1e-12:
        why = "call; price is inside the group threshold"
        if group == 1 and "raise" not in legal:
            why = "raise size blocked by policy, call"
        return _finish("call", f"{label}; {why} ({odds})", 0.88 if group <= 2 else 0.78)
    if "fold" in legal:
        note = "fold trash" if group == 9 else "fold"
        return _finish(
            "fold",
            f"{label}; {note}, price is too wide ({odds})",
            0.93 if group == 9 else 0.80,
        )
    return _finish(_fallback(legal), f"{label}; fold not legal ({odds})", 0.75)


def _value_label(flags: dict) -> str:
    if flags["nuts"]:
        return "nuts"
    if flags["set"]:
        return "set"
    if flags["two_pair_plus"]:
        return f"two pair or better (category {flags['kind']})"
    return f"made hand category {flags['kind']}"


def _postflop(state, hole, board, legal, sizes, price, deck) -> StrategyAdvice:
    flags = postflop_flags(hole, board, deck)
    odds = f"pot odds {price:.2f}"
    value = flags["nuts"] or flags["two_pair_plus"]
    if value:
        why = _value_label(flags)
        if "raise" in legal and sizes and (state.to_call <= state.pot or state.to_call <= 0):
            return _finish(
                "raise",
                f"{why} on {state.street}; raise, not fold ({odds})",
                0.90,
                alternatives=(("call", "call if raise is declined"),) if "call" in legal else (),
                size=_pick_size(sizes, "large"),
            )
        if state.to_call > 0 and "call" in legal:
            return _finish("call", f"{why} on {state.street}; call, not fold ({odds})", 0.90)
        if "check" in legal:
            return _finish("check", f"{why} on {state.street}; check ({odds})", 0.88)
        return _finish(_fallback(legal), f"{why}; value action filtered by policy ({odds})", 0.90)

    if flags["high_pair"]:
        which = "overpair" if flags["overpair"] else "top pair"
        if state.to_call <= 0 and "raise" in legal and sizes:
            return _finish(
                "raise",
                f"high pair ({which}) on {state.street}; bet ({odds})",
                0.78,
                size=_pick_size(sizes, "small"),
            )
        if state.to_call <= 0 and "check" in legal:
            return _finish("check", f"high pair ({which}); check ({odds})", 0.76)
        if "call" in legal and price <= 0.40 + 1e-12:
            return _finish("call", f"high pair ({which}); call up to 0.40 ({odds})", 0.76)
        if "fold" in legal and state.to_call > 0:
            return _finish("fold", f"high pair ({which}); price is too wide ({odds})", 0.74)
        return _finish(
            _fallback(legal), f"high pair ({which}); no better legal action ({odds})", 0.72
        )

    equity = draw_equity(flags, len(board))
    drawing = equity > 0 and (flags["oesd"] or flags["gutshot"] or flags["flush_draw"])
    if drawing:
        draw = "flush draw" if flags["flush_draw"] else flags["straight_draw"]
        if state.to_call <= 0 and "check" in legal:
            return _finish("check", f"{draw} equity {equity:.2f}; free card ({odds})", 0.82)
        if "call" in legal and price <= equity + 1e-9:
            return _finish("call", f"{draw} equity {equity:.2f} beats {odds}", 0.80)
        if "fold" in legal and state.to_call > 0:
            return _finish("fold", f"{draw} equity {equity:.2f} loses to {odds}", 0.80)
        return _finish(_fallback(legal), f"{draw} with no priced continue ({odds})", 0.75)

    if flags["pair"]:
        if state.to_call <= 0 and "check" in legal:
            return _finish("check", f"weak pair; check ({odds})", 0.70)
        if "call" in legal and price <= 0.35:
            return _finish("call", f"weak pair; call a small price ({odds})", 0.70)
        if "fold" in legal and state.to_call > 0:
            return _finish("fold", f"weak pair; price is too wide ({odds})", 0.72)
        return _finish(_fallback(legal), f"weak pair; no better legal action ({odds})", 0.70)

    if flags["overcards"]:
        if state.to_call <= 0 and "check" in legal:
            return _finish("check", f"overcards only; check ({odds})", 0.80)
        if "call" in legal and price <= 0.12:
            return _finish("call", f"overcards; very cheap price ({odds})", 0.65)
        if "fold" in legal and state.to_call > 0:
            return _finish("fold", f"overcards only; fold ({odds})", 0.80)
        return _finish(_fallback(legal), f"overcards; fold not legal ({odds})", 0.75)

    if state.to_call <= 0 and "check" in legal:
        return _finish("check", f"no made hand; check ({odds})", 0.85)
    if "fold" in legal and state.to_call > 0:
        return _finish("fold", f"no made hand or draw; fold ({odds})", 0.88)
    return _finish(_fallback(legal), f"no made hand; taking a free action ({odds})", 0.80)
