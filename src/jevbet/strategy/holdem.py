"""Texas Hold'em heuristic. Not a GTO solution.

Preflop classes (premium / strong / speculative / trash) come from the two hole
cards. Postflop uses pot odds plus deterministic flags: pair, overcards, flush
or straight draw, and whether the holding is the nuts on this board. Raise
sizes are chosen only from ``filtered_raise_sizes`` (already inside RiskPolicy).
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
    preflop_class,
)


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


def _preflop(state, hole, legal, sizes, price) -> StrategyAdvice:
    values = (hole[0][0], hole[1][0])
    suited = hole[0][1] == hole[1][1]
    kind = preflop_class(values, suited)
    label = f"{kind} {'suited' if suited else 'offsuit'} from {state.position}"
    odds = f"pot odds {price:.2f}"
    if kind == "premium":
        if "raise" in legal and sizes:
            return _finish(
                "raise",
                f"{label}; raise ({odds})",
                0.90,
                alternatives=(("call", "call if the raise size is declined"),)
                if "call" in legal
                else (),
                size=_pick_size(sizes, "medium"),
            )
        if "call" in legal:
            return _finish("call", f"{label}; raise size blocked by policy, call ({odds})", 0.88)
        return _finish(_fallback(legal), f"{label}; no priced raise or call ({odds})", 0.85)
    if kind == "strong":
        if state.to_call <= 0 and "raise" in legal and sizes:
            return _finish(
                "raise",
                f"{label}; raise when checked to ({odds})",
                0.82,
                size=_pick_size(sizes, "small"),
            )
        if state.to_call <= 0 and "check" in legal:
            return _finish("check", f"{label}; check ({odds})", 0.80)
        if "call" in legal and price <= 0.35:
            return _finish("call", f"{label}; call a modest price ({odds})", 0.80)
        if "fold" in legal and state.to_call > 0:
            return _finish("fold", f"{label}; price is too wide ({odds})", 0.78)
        return _finish(_fallback(legal), f"{label}; no better legal action ({odds})", 0.75)
    if kind == "speculative":
        if state.to_call <= 0 and "check" in legal:
            return _finish("check", f"{label}; free card ({odds})", 0.80)
        if "call" in legal and price <= 0.20:
            return _finish("call", f"{label}; cheap speculative call ({odds})", 0.60)
        if "fold" in legal and state.to_call > 0:
            return _finish("fold", f"{label}; not priced to continue ({odds})", 0.72)
        return _finish(_fallback(legal), f"{label}; taking the free action ({odds})", 0.70)
    # trash
    if state.to_call <= 0 and "check" in legal:
        return _finish("check", f"{label}; nothing to call ({odds})", 0.88)
    if "fold" in legal and state.to_call > 0:
        return _finish("fold", f"{label}; fold trash facing a bet ({odds})", 0.93)
    return _finish(_fallback(legal), f"{label}; fold not legal ({odds})", 0.80)


def _postflop(state, hole, board, legal, sizes, price, deck) -> StrategyAdvice:
    flags = postflop_flags(hole, board, deck)
    odds = f"pot odds {price:.2f}"
    value = flags["nuts"] or (flags["hero_made"] and flags["kind"] >= 2)
    if value:
        why = "nuts" if flags["nuts"] else f"made hand category {flags['kind']}"
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

    equity = draw_equity(flags, len(board))
    drawing = equity > 0 and flags["kind"] < 2
    if drawing:
        if state.to_call <= 0 and "check" in legal:
            return _finish("check", f"draw equity {equity:.2f}; free card ({odds})", 0.82)
        if "call" in legal and price <= equity + 1e-9:
            return _finish("call", f"draw equity {equity:.2f} beats {odds}", 0.80)
        if "fold" in legal and state.to_call > 0:
            return _finish("fold", f"draw equity {equity:.2f} loses to {odds}", 0.80)
        return _finish(_fallback(legal), f"draw with no priced continue ({odds})", 0.75)

    if flags["pair"]:
        if state.to_call <= 0 and "check" in legal:
            return _finish("check", f"one pair; check ({odds})", 0.70)
        if "call" in legal and price <= 0.35:
            return _finish("call", f"one pair; call a small price ({odds})", 0.70)
        if "fold" in legal and state.to_call > 0:
            return _finish("fold", f"one pair; price is too wide ({odds})", 0.72)
        return _finish(_fallback(legal), f"one pair; no better legal action ({odds})", 0.70)

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
