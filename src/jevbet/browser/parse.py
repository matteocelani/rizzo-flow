"""Turn mock-casino DOM attributes into a Jevbet state dict.

Both ``MockTableDriver`` (static HTML) and ``ChromeTableDriver`` (live page)
call this so the two paths describe the same table. Real-site adapters that
do not use these ``data-*`` attributes should not go through this parser.
"""

from __future__ import annotations

import re
from typing import Any

# Attributes the mock pages actually set. Chrome reads this fixed list via
# ``element.get_attribute`` so a test double does not have to run JavaScript.
TABLE_ATTRS = (
    "data-game",
    "data-bankroll",
    "data-currency",
    "data-session-profit",
    "data-stop-loss",
    "data-take-profit",
    "data-bet",
    "data-decks",
    "data-phase",
    "data-street",
    "data-pot",
    "data-to-call",
    "data-stack",
    "data-position",
    "data-players",
    "data-min-raise",
    "data-max-raise",
    "data-raise-suggestions",
    "data-table-min",
)

ROLE_ATTRS = (
    "data-role",
    "data-cards",
    "data-upcard",
    "data-soft",
    "data-hole",
)


def read_element_attrs(element: Any, names: tuple[str, ...]) -> dict[str, str]:
    """Copy known attributes off a Playwright element (or a test double)."""
    if element is None:
        return {}
    out: dict[str, str] = {}
    for name in names:
        value = element.get_attribute(name)
        if value is not None:
            out[name] = value
    return out


def _rank(token: str) -> str:
    body = token[:-1]
    if body in {"1", "A"}:
        return "A"
    if body in {"T", "10"}:
        return "10"
    return body


def split_cards(raw: str | None) -> list[dict[str, str]]:
    if not raw:
        return []
    out = []
    for token in re.split(r"[,\s]+", raw.strip()):
        if not token:
            continue
        token = token.upper()
        out.append({"rank": _rank(token), "suit": token[-1]})
    return out


def bankroll_from_attrs(attrs: dict[str, str]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "cash": float(attrs.get("data-bankroll", "1000")),
        "currency": attrs.get("data-currency") or "EUR",
        "session_profit": float(attrs.get("data-session-profit") or "0"),
    }
    if attrs.get("data-stop-loss"):
        data["stop_loss"] = float(attrs["data-stop-loss"])
    if attrs.get("data-take-profit"):
        data["take_profit"] = float(attrs["data-take-profit"])
    return data


def parse_observed_table(
    *,
    game: str,
    table_attrs: dict[str, str],
    roles: dict[str, dict[str, str]],
    actions: list[str],
) -> dict[str, Any]:
    """Build a blackjack or holdem state from mock-casino attributes.

    ``deal`` is a table control, not a decision, and is dropped here.
    """
    game_id = (table_attrs.get("data-game") or game or "").strip().lower()
    legal = [action for action in actions if action and action != "deal"]
    bankroll = bankroll_from_attrs(table_attrs)
    if game_id == "blackjack":
        player = roles.get("player", {})
        dealer = roles.get("dealer", {})
        up = split_cards(dealer.get("data-upcard") or dealer.get("data-cards"))
        if not up:
            raise ValueError("blackjack table is missing the dealer upcard")
        bet = float(table_attrs.get("data-bet", "10"))
        return {
            "game": "blackjack",
            "dealer_upcard": up[0],
            "hands": [
                {
                    "cards": split_cards(player.get("data-cards")),
                    "bet": bet,
                    "is_soft": player.get("data-soft", "false").lower() == "true",
                }
            ],
            "legal_actions": legal,
            "bankroll": bankroll,
            "rules": {"decks": int(table_attrs.get("data-decks", "6"))},
        }
    if game_id in {"holdem", "texas_holdem"}:
        hero = roles.get("hero", {})
        board = roles.get("board", {})
        suggestions = [
            float(part)
            for part in table_attrs.get("data-raise-suggestions", "").split(",")
            if part.strip()
        ]
        state: dict[str, Any] = {
            "game": "holdem",
            "street": table_attrs.get("data-street", "flop"),
            "hole_cards": split_cards(hero.get("data-cards")),
            "community": split_cards(board.get("data-cards")),
            "pot": float(table_attrs.get("data-pot", "0")),
            "to_call": float(table_attrs.get("data-to-call", "0")),
            "stack": float(table_attrs.get("data-stack", str(bankroll["cash"]))),
            "position": table_attrs.get("data-position", "BTN"),
            "num_players": int(table_attrs.get("data-players", "6")),
            "legal_actions": legal,
            "min_raise": float(table_attrs.get("data-min-raise", "0")),
            "raise_suggestions": suggestions,
            "bankroll": bankroll,
            "rules": {"small_blind": 1, "big_blind": 2},
        }
        if table_attrs.get("data-max-raise"):
            state["max_raise"] = float(table_attrs["data-max-raise"])
        return state
    raise ValueError(f"No mock-casino reader for game {game_id!r}")
