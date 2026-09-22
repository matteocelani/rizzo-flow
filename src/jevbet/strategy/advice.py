"""Strategy result shared by every game engine."""

from __future__ import annotations

from dataclasses import dataclass

# At or above this, the decide path keeps the strategy action unless the
# caller sets model override / ``--llm``.
CONFIDENT_AT = 0.75


@dataclass(frozen=True)
class StrategyAdvice:
    """One recommended action plus why, and optional ranked fallbacks.

    ``action`` is an option id the table builder would actually offer after
    ``RiskPolicy`` (``hit``, ``p0``, ``c0_7_coppe``, ``pass``, …). It is never
    the ``hold_policy`` sentinel.
    """

    action: str | None
    reason: str
    confidence: float
    alternatives: tuple[tuple[str, str], ...] = ()
    game: str = ""
    size: float | None = None

    @property
    def confident(self) -> bool:
        return self.action is not None and self.confidence >= CONFIDENT_AT

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "reason": self.reason,
            "confidence": self.confidence,
            "confident": self.confident,
            "alternatives": [
                {"action": action, "reason": why} for action, why in self.alternatives
            ],
            "game": self.game,
            "size": self.size,
        }
