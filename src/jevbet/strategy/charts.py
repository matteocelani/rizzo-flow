"""Blackjack basic-strategy chart strings.

Sources
-------
* **H17 multi-deck** (``HARD_H17`` / ``SOFT_H17`` / ``PAIRS_H17_*``): Blackjack
  Apprenticeship H17 chart (2024). Used whenever ``dealer_hits_soft_17`` is true.
* **S17 multi-deck** (``*_S17_MULTI_*``): encoded from the blackjacksimulator.net
  "più mazzi" table (independent re-implementation; not affiliated).
* **S17 single-deck** (``*_S17_1D_*``): encoded from the blackjacksimulator.net
  "un mazzo" table. Selected when ``rules.decks == 1`` and the dealer stands on
  soft 17.

Codes (one character per dealer upcard 2…A):

* ``H`` hit, ``S`` stand
* ``D`` double else hit, ``U`` double else stand
* ``R`` surrender else hit, ``W`` surrender else stand
* ``Y`` split, ``Z`` surrender else split, ``.`` play the hard/soft total
"""

from __future__ import annotations

DEALER_UPCARDS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "A")

# --- Blackjack Apprenticeship H17 (4–8 decks) ---------------------------------

HARD_H17 = {
    5: "HHHHHHHHHH",
    6: "HHHHHHHHHH",
    7: "HHHHHHHHHH",
    8: "HHHHHHHHHH",
    9: "HDDDDHHHHH",
    10: "DDDDDDDDHH",
    11: "DDDDDDDDDD",
    12: "HHSSSHHHHH",
    13: "SSSSSHHHHH",
    14: "SSSSSHHHHH",
    15: "SSSSSHHHRR",
    16: "SSSSSHHRRR",
    17: "SSSSSSSSSW",
    18: "SSSSSSSSSS",
    19: "SSSSSSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
SOFT_H17 = {
    13: "HHHDDHHHHH",
    14: "HHHDDHHHHH",
    15: "HHDDDHHHHH",
    16: "HHDDDHHHHH",
    17: "HDDDDHHHHH",
    18: "UUUUUSSHHH",
    19: "SSSSUSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
PAIRS_H17_DAS = {
    "A": "YYYYYYYYYY",
    "10": "SSSSSSSSSS",
    "9": "YYYYYSYYSS",
    "8": "YYYYYYYYYZ",
    "7": "YYYYYY....",
    "6": "YYYYY.....",
    "5": "..........",
    "4": "...YY.....",
    "3": "YYYYYY....",
    "2": "YYYYYY....",
}
PAIRS_H17_NDAS = {
    "A": "YYYYYYYYYY",
    "10": "SSSSSSSSSS",
    "9": "YYYYYSYYSS",
    "8": "YYYYYYYYYZ",
    "7": "YYYYYY....",
    "6": ".YYYY.....",
    "5": "..........",
    "4": "..........",
    "3": "..YYYY....",
    "2": "..YYYY....",
}

# --- blackjacksimulator.net S17 multi-deck ("più mazzi") ----------------------

HARD_S17_MULTI = {
    5: "HHHHHHHHHH",
    6: "HHHHHHHHHH",
    7: "HHHHHHHHHH",
    8: "HHHHHHHHHH",
    9: "HDDDDHHHHH",
    10: "DDDDDDDDHH",
    11: "DDDDDDDDDH",
    12: "HHSSSHHHHH",
    13: "SSSSSHHHHH",
    14: "SSSSSHHHHH",
    15: "SSSSSHHHRH",
    16: "SSSSSHHRRR",
    17: "SSSSSSSSSS",
    18: "SSSSSSSSSS",
    19: "SSSSSSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
SOFT_S17_MULTI = {
    13: "HHHDDHHHHH",
    14: "HHHDDHHHHH",
    15: "HHDDDHHHHH",
    16: "HHDDDHHHHH",
    17: "HDDDDHHHHH",
    18: "SUUUUSSHHH",
    19: "SSSSSSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
PAIRS_S17_MULTI_DAS = {
    "A": "YYYYYYYYYY",
    "10": "SSSSSSSSSS",
    "9": "YYYYYSYYSS",
    "8": "YYYYYYYYYY",
    "7": "YYYYYY....",
    "6": ".YYYY.....",
    "5": "..........",
    "4": "..........",
    "3": "..YYYY....",
    "2": "..YYYY....",
}
# Site multi-deck pair chart already matches classic no-DAS splits; keep an alias.
PAIRS_S17_MULTI_NDAS = dict(PAIRS_S17_MULTI_DAS)

# --- blackjacksimulator.net S17 single-deck ("un mazzo") ----------------------

HARD_S17_1D = {
    5: "HHHHHHHHHH",
    6: "HHHHHHHHHH",
    7: "HHHHHHHHHH",
    8: "HHHDDHHHHH",
    9: "DDDDDHHHHH",
    10: "DDDDDDDDHH",
    11: "DDDDDDDDDD",
    12: "HHSSSHHHHH",
    13: "SSSSSHHHHH",
    14: "SSSSSHHHHH",
    15: "SSSSSHHHHH",
    16: "SSSSSHHHRR",
    17: "SSSSSSSSSS",
    18: "SSSSSSSSSS",
    19: "SSSSSSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
SOFT_S17_1D = {
    13: "HHHDDHHHHH",
    14: "HHHDDHHHHH",
    15: "HHDDDHHHHH",
    16: "HHDDDHHHHH",
    17: "DDDDDHHHHH",
    18: "SUUUUSSHHH",
    19: "SSSSUSSSSS",
    20: "SSSSSSSSSS",
    21: "SSSSSSSSSS",
}
# Soft 18 vs A stands on the single-deck image (last column S, not H).
SOFT_S17_1D[18] = "SUUUUSSHHS"
PAIRS_S17_1D_DAS = {
    "A": "YYYYYYYYYY",
    "10": "SSSSSSSSSS",
    "9": "YYYYYSYYSS",
    "8": "YYYYYYYYYY",
    "7": "YYYYYYHHWH",
    "6": "YYYYY.....",
    "5": "..........",
    "4": "..........",
    "3": "HHYYYY....",
    "2": "HYYYYY....",
}
PAIRS_S17_1D_NDAS = {
    "A": "YYYYYYYYYY",
    "10": "SSSSSSSSSS",
    "9": "YYYYYSYYSS",
    "8": "YYYYYYYYYY",
    "7": "YYYYYYHHWH",
    "6": ".YYYY.....",
    "5": "..........",
    "4": "..........",
    "3": "HHYYYY....",
    "2": "HYYYYY....",
}

# Public aliases used by older imports / H17 path documentation.
HARD_S17 = HARD_S17_MULTI
SOFT_S17 = SOFT_S17_MULTI
PAIRS_S17_DAS = PAIRS_S17_MULTI_DAS
PAIRS_S17_NDAS = PAIRS_S17_MULTI_NDAS

_HARD_CODES = frozenset("HSDRW")
_SOFT_CODES = frozenset("HSDU")
# Single-deck 7,7 uses H (hit) and W (surrender else stand) on some columns.
_PAIR_CODES = frozenset("YSZ.HW")
_HARD_KEYS = tuple(range(5, 22))
_SOFT_KEYS = tuple(range(13, 22))
_PAIR_KEYS = ("A", "10", "9", "8", "7", "6", "5", "4", "3", "2")


def _check_table(name: str, table: dict, keys: tuple, alphabet: frozenset[str]) -> None:
    found = tuple(table)
    if found != keys:
        raise RuntimeError(f"{name} keys {found} != {keys}")
    for key in keys:
        row = table[key]
        if len(row) != len(DEALER_UPCARDS):
            raise RuntimeError(f"{name}[{key!r}] length {len(row)} != 10")
        bad = set(row) - alphabet
        if bad:
            raise RuntimeError(f"{name}[{key!r}] has codes {sorted(bad)}")


def validate_charts() -> None:
    """Every published string is 10 characters and the key sets are complete."""
    hard = {
        "HARD_H17": HARD_H17,
        "HARD_S17_MULTI": HARD_S17_MULTI,
        "HARD_S17_1D": HARD_S17_1D,
    }
    soft = {
        "SOFT_H17": SOFT_H17,
        "SOFT_S17_MULTI": SOFT_S17_MULTI,
        "SOFT_S17_1D": SOFT_S17_1D,
    }
    pairs = {
        "PAIRS_H17_DAS": PAIRS_H17_DAS,
        "PAIRS_H17_NDAS": PAIRS_H17_NDAS,
        "PAIRS_S17_MULTI_DAS": PAIRS_S17_MULTI_DAS,
        "PAIRS_S17_MULTI_NDAS": PAIRS_S17_MULTI_NDAS,
        "PAIRS_S17_1D_DAS": PAIRS_S17_1D_DAS,
        "PAIRS_S17_1D_NDAS": PAIRS_S17_1D_NDAS,
    }
    for name, table in hard.items():
        _check_table(name, table, _HARD_KEYS, _HARD_CODES)
    for name, table in soft.items():
        _check_table(name, table, _SOFT_KEYS, _SOFT_CODES)
    for name, table in pairs.items():
        _check_table(name, table, _PAIR_KEYS, _PAIR_CODES)


def hits_soft_17(rules: dict) -> bool:
    if "dealer_hits_soft_17" in rules:
        return bool(rules["dealer_hits_soft_17"])
    if "dealer_stands_soft_17" in rules:
        return not bool(rules["dealer_stands_soft_17"])
    return True


def das_enabled(rules: dict) -> bool:
    if "das" not in rules:
        return True
    return bool(rules["das"])


def surrender_enabled(rules: dict) -> bool:
    if "surrender" not in rules:
        return True
    raw = rules["surrender"]
    if isinstance(raw, str):
        return raw.strip().lower() in {"late", "ls", "true", "yes", "1"}
    return bool(raw)


def deck_count(rules: dict) -> int:
    raw = rules.get("decks", 6)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 6


def select_tables(rules: dict) -> tuple[dict[int, str], dict[int, str], dict[str, str], str]:
    """Return ``(hard, soft, pairs, chart_label)`` for these rules."""
    h17 = hits_soft_17(rules)
    das = das_enabled(rules)
    decks = deck_count(rules)
    if h17:
        hard, soft = HARD_H17, SOFT_H17
        pairs = PAIRS_H17_DAS if das else PAIRS_H17_NDAS
        label = "H17 multi-deck BJA"
    elif decks == 1:
        hard, soft = HARD_S17_1D, SOFT_S17_1D
        pairs = PAIRS_S17_1D_DAS if das else PAIRS_S17_1D_NDAS
        label = "S17 single-deck (blackjacksimulator.net)"
    else:
        hard, soft = HARD_S17_MULTI, SOFT_S17_MULTI
        pairs = PAIRS_S17_MULTI_DAS if das else PAIRS_S17_MULTI_NDAS
        label = "S17 multi-deck (blackjacksimulator.net)"
    return hard, soft, pairs, label


validate_charts()
