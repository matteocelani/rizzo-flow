"""Blackjack bet sizing strategies.

Systems
-------
* ``flat`` — one unit every round; ignores the true count.
* ``ramp`` / ``tc_ramp`` — 1 unit at TC ≤ 1, then ramp with TC (capped).
* ``kelly`` / ``kelly_fraction`` — fractional Kelly on an estimated edge vs TC.
* ``martingale`` — double after a loss, reset after a win.
* ``martingale_limited`` — martingale capped at ``rules.martingale_max_steps``.
* ``grand_martingale`` — after a loss, double + one unit.
* ``anti_martingale`` — double after a win, reset after a loss.

Honest warning: the Martingale family does **not** overcome the house edge.
Table maxima and finite bankrolls make ruin certain under long losing streaks.
Prefer ``ramp`` / ``kelly`` when Hi-Lo counting is enabled and the shoe is
continuous. These systems exist because the reference site documents them, not
because they are +EV.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..cards import Bankroll
from ..policy import RiskPolicy

# Rough multi-deck Hi-Lo edge ≈ −0.5% + 0.5% × TC (common teaching rule of thumb).
_BASE_EDGE = -0.005
_EDGE_PER_TC = 0.005


@dataclass(frozen=True)
class BetAdvice:
    amount: float
    reason: str
    system: str
    unit: float
    true_count: float | None = None

    def as_dict(self) -> dict:
        return {
            "amount": self.amount,
            "reason": self.reason,
            "system": self.system,
            "unit": self.unit,
            "true_count": self.true_count,
        }


def normalize_bet_system(raw: str | None) -> str:
    text = (raw or "flat").strip().lower().replace("-", "_")
    aliases = {
        "tc_ramp": "ramp",
        "kelly_fraction": "kelly",
        "fractional_kelly": "kelly",
        "off": "flat",
        "none": "flat",
    }
    return aliases.get(text, text)


def estimated_edge(true_count: float) -> float:
    return _BASE_EDGE + _EDGE_PER_TC * float(true_count)


def _unit(rules: dict, bankroll: Bankroll, policy: RiskPolicy) -> float:
    raw = rules.get("bet_unit") or rules.get("unit") or rules.get("table_min") or policy.min_bet
    try:
        unit = float(raw)
    except (TypeError, ValueError):
        unit = float(policy.min_bet)
    return max(float(policy.min_bet), unit)


def _cap(amount: float, bankroll: Bankroll, policy: RiskPolicy, rules: dict) -> float:
    if policy.should_stop(bankroll):
        return 0.0
    table_min = float(rules.get("table_min") or policy.min_bet)
    table_max = rules.get("table_max")
    ceiling = policy.max_allowed_bet(bankroll)
    if table_max is not None:
        ceiling = min(ceiling, float(table_max))
    ceiling = min(ceiling, bankroll.cash)
    if ceiling + 1e-9 < table_min:
        return 0.0
    return max(0.0, min(float(amount), ceiling))


def recommend_bet(
    bankroll: Bankroll,
    *,
    true_count: float | None = None,
    rules: dict | None = None,
    policy: RiskPolicy | None = None,
    last_result: str | None = None,
    step: int = 0,
) -> BetAdvice:
    """Recommend a round bet before cards are dealt."""
    rules = dict(rules or {})
    policy = policy or RiskPolicy()
    system = normalize_bet_system(str(rules.get("bet_system") or rules.get("betting") or "flat"))
    unit = _unit(rules, bankroll, policy)
    tc = 0.0 if true_count is None else float(true_count)

    if policy.should_stop(bankroll):
        return BetAdvice(
            amount=0.0,
            reason="stop-loss / take-profit / cash below min_bet; bet 0",
            system=system,
            unit=unit,
            true_count=true_count,
        )

    if system == "flat":
        amount = unit
        reason = f"flat {unit}"
    elif system == "ramp":
        if tc <= 1:
            units = 1.0
        else:
            units = min(12.0, 1.0 + (tc - 1.0))
        amount = unit * units
        reason = f"tc_ramp {units:.2f}× unit at TC {tc:.2f}"
    elif system == "kelly":
        edge = estimated_edge(tc)
        fraction = float(rules.get("kelly_fraction") or 0.25)
        fraction = max(0.0, min(1.0, fraction))
        if edge <= 0:
            amount = unit
            reason = f"kelly edge {edge:.4f} ≤ 0; fall back to 1 unit"
        else:
            # Even-money approx: f* = edge (for 1:1). Stake = fraction × f* × bankroll.
            kelly = edge * fraction * bankroll.cash
            amount = max(unit, kelly)
            reason = f"fractional kelly {fraction} on edge {edge:.4f}"
    elif system in {"martingale", "martingale_limited", "grand_martingale", "anti_martingale"}:
        amount, reason = _progression(
            system, unit=unit, last_result=last_result, step=step, rules=rules
        )
    else:
        amount = unit
        reason = f"unknown bet system {system!r}; flat"
        system = "flat"

    capped = _cap(amount, bankroll, policy, rules)
    if capped + 1e-9 < amount:
        reason = f"{reason}; capped to {capped}"
    return BetAdvice(
        amount=round(capped, 2),
        reason=reason,
        system=system,
        unit=unit,
        true_count=true_count,
    )


def _progression(
    system: str,
    *,
    unit: float,
    last_result: str | None,
    step: int,
    rules: dict,
) -> tuple[float, str]:
    result = (last_result or "").lower()
    max_steps = int(rules.get("martingale_max_steps") or 4)
    step = max(0, int(step))
    if system == "anti_martingale":
        if result == "win":
            step = step + 1
        else:
            step = 0
        amount = unit * (2**step)
        return amount, f"anti_martingale step {step} after {result or 'reset'}"
    # Loss progressions.
    if result == "loss":
        next_step = step + 1
    elif result == "win":
        next_step = 0
    else:
        next_step = step
    if system == "martingale_limited":
        next_step = min(next_step, max_steps)
        amount = unit * (2**next_step)
        return amount, f"martingale_limited step {next_step}/{max_steps}"
    if system == "grand_martingale":
        amount = unit * (2**next_step) + (unit if next_step else 0.0)
        if next_step == 0:
            amount = unit
        else:
            amount = unit * (2**next_step) + unit
        return amount, f"grand_martingale step {next_step}"
    # classic martingale
    amount = unit * (2**next_step)
    return amount, f"martingale step {next_step} (does not overcome house edge)"


def next_progression_step(
    system: str, *, last_result: str | None, step: int, rules: dict | None = None
) -> int:
    """Update the stored progression step after a settled round."""
    system = normalize_bet_system(system)
    rules = rules or {}
    result = (last_result or "").lower()
    max_steps = int(rules.get("martingale_max_steps") or 4)
    if system == "anti_martingale":
        return step + 1 if result == "win" else 0
    if system not in {"martingale", "martingale_limited", "grand_martingale"}:
        return 0
    if result == "win":
        return 0
    if result == "loss":
        nxt = step + 1
        if system == "martingale_limited":
            return min(nxt, max_steps)
        return nxt
    return step
