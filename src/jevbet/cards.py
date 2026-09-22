"""Shared card and money primitives for every Jevbet game."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from rizzo_flow.schema import Strict

Rank = Literal["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
Suit = Literal["S", "H", "D", "C"]  # spades, hearts, diamonds, clubs
ItalianSuit = Literal["denari", "coppe", "spade", "bastoni"]
ItalianRank = Literal["1", "2", "3", "4", "5", "6", "7", "Fante", "Cavallo", "Re"]

Money = Annotated[float, Field(allow_inf_nan=False, ge=0, le=1e12)]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class Card(Strict):
    """Standard 52-card French deck card (blackjack, Hold'em, roulette side notes)."""

    rank: Rank
    suit: Suit

    def label(self) -> str:
        return f"{self.rank}{self.suit}"

    @classmethod
    def parse(cls, text: str) -> "Card":
        raw = text.strip().upper().replace(" ", "")
        if len(raw) < 2:
            raise ValueError(f"Invalid card: {text!r}")
        suit = raw[-1]
        rank = raw[:-1]
        if rank == "1":
            rank = "A"
        if rank == "T":
            rank = "10"
        return cls.model_validate({"rank": rank, "suit": suit})


class ItalianCard(Strict):
    """40-card Italian deck used by scopa, tre sette, and poker italiano variants."""

    rank: ItalianRank
    suit: ItalianSuit

    def label(self) -> str:
        return f"{self.rank}-{self.suit}"

    @classmethod
    def parse(cls, text: str) -> "ItalianCard":
        raw = text.strip().lower().replace(" ", "")
        for sep in ("-", "_", "/"):
            if sep in raw:
                rank, suit = raw.split(sep, 1)
                break
        else:
            raise ValueError(f"Italian card must look like '7-denari', got {text!r}")
        rank_map = {
            "1": "1",
            "a": "1",
            "asso": "1",
            "2": "2",
            "3": "3",
            "4": "4",
            "5": "5",
            "6": "6",
            "7": "7",
            "f": "fante",
            "fante": "fante",
            "j": "fante",
            "c": "cavallo",
            "cavallo": "cavallo",
            "q": "cavallo",
            "r": "re",
            "re": "re",
            "k": "re",
        }
        suit_map = {
            "d": "denari",
            "denari": "denari",
            "denaro": "denari",
            "c": "coppe",
            "coppe": "coppe",
            "s": "spade",
            "spade": "spade",
            "b": "bastoni",
            "bastoni": "bastoni",
        }
        if rank not in rank_map or suit not in suit_map:
            raise ValueError(f"Unknown Italian card: {text!r}")
        # Capitalize face ranks to match Literal values.
        out_rank = rank_map[rank]
        if out_rank in {"fante", "cavallo", "re"}:
            out_rank = out_rank.capitalize()
        return cls.model_validate({"rank": out_rank, "suit": suit_map[suit]})


class Bankroll(Strict):
    """Player funds and stop conditions shared across games."""

    cash: Money
    currency: NonEmptyText = "EUR"
    session_profit: Annotated[float, Field(allow_inf_nan=False, ge=-1e12, le=1e12)] = 0.0
    stop_loss: Money | None = None
    take_profit: Money | None = None

    @field_validator("stop_loss", "take_profit", mode="before")
    @classmethod
    def empty_to_none(cls, value):
        return None if value == "" else value
