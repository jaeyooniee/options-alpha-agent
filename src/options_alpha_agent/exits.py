"""AI-independent exit policy for defined-risk option positions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo


class ExitPolicyError(ValueError):
    """Raised when a position snapshot cannot be evaluated safely."""


@dataclass(frozen=True, slots=True)
class ManagedPosition:
    symbol: str
    strategy: str
    quantity: int
    entry_debit_usd: Decimal
    current_value_usd: Decimal
    max_loss_usd: Decimal
    days_to_expiry: int
    quote_fresh: bool
    opened_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ExitDecision:
    action: str
    reasons: tuple[str, ...]
    unrealized_pnl_usd: Decimal
    risk_multiple: Decimal

    def public_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reasons": list(self.reasons),
            "unrealized_pnl_usd": str(self.unrealized_pnl_usd),
            "risk_multiple": str(self.risk_multiple),
        }


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ExitPolicyError(f"{field_name} must be numeric") from exc
    if not parsed.is_finite():
        raise ExitPolicyError(f"{field_name} must be finite")
    return parsed


def evaluate_exit(
    position: ManagedPosition,
    *,
    take_profit_r: Decimal = Decimal("0.25"),
    stop_loss_r: Decimal = Decimal("0.35"),
    now: datetime | None = None,
    max_holding_minutes: int = 15,
) -> ExitDecision:
    """Return a deterministic close-review decision without contacting a broker."""

    if position.quantity < 1:
        raise ExitPolicyError("quantity must be positive")
    if max_holding_minutes < 1:
        raise ExitPolicyError("max_holding_minutes must be positive")
    numeric_fields = (
        position.entry_debit_usd,
        position.current_value_usd,
        position.max_loss_usd,
        take_profit_r,
        stop_loss_r,
    )
    if any(not value.is_finite() for value in numeric_fields):
        raise ExitPolicyError("exit policy inputs must be finite")
    if position.max_loss_usd <= 0 or position.entry_debit_usd <= 0:
        raise ExitPolicyError("entry debit and maximum loss must be positive")
    if position.current_value_usd < 0 or take_profit_r <= 0 or stop_loss_r <= 0:
        raise ExitPolicyError("exit policy inputs must be positive")
    if not position.quote_fresh and position.days_to_expiry <= 1:
        return ExitDecision(
            "MANUAL_REVIEW",
            ("stale_quote_near_expiry",),
            Decimal("0"),
            Decimal("0"),
        )
    pnl = position.current_value_usd - position.entry_debit_usd
    risk_multiple = pnl / position.max_loss_usd
    cycle_time = now or datetime.now(UTC)
    if cycle_time.tzinfo is None:
        cycle_time = cycle_time.replace(tzinfo=UTC)
    else:
        cycle_time = cycle_time.astimezone(UTC)
    session_time = cycle_time.astimezone(ZoneInfo("America/New_York")).time()
    if session_time >= time(15, 45):
        reasons = ("session_close_flatten",)
    elif position.opened_at is not None:
        opened_at = position.opened_at
        if opened_at.tzinfo is None:
            raise ExitPolicyError("opened_at must be timezone-aware")
        held_minutes = (cycle_time - opened_at.astimezone(UTC)).total_seconds() / 60
        if held_minutes >= max_holding_minutes:
            reasons = ("max_intraday_holding_time",)
        elif position.days_to_expiry <= 0:
            reasons = ("expired_or_expiring",)
        elif pnl >= position.max_loss_usd * take_profit_r:
            reasons = ("take_profit_threshold",)
        elif pnl <= -position.max_loss_usd * stop_loss_r:
            reasons = ("stop_loss_threshold",)
        else:
            reasons = ()
    elif position.days_to_expiry <= 0:
        reasons = ("expired_or_expiring",)
    elif pnl >= position.max_loss_usd * take_profit_r:
        reasons = ("take_profit_threshold",)
    elif pnl <= -position.max_loss_usd * stop_loss_r:
        reasons = ("stop_loss_threshold",)
    else:
        reasons = ()
    if not position.quote_fresh:
        return ExitDecision(
            "MANUAL_REVIEW" if reasons else "HOLD",
            ("stale_quote", *reasons) if reasons else ("stale_quote",),
            pnl,
            risk_multiple,
        )
    return ExitDecision("EXIT_REVIEW" if reasons else "HOLD", reasons, pnl, risk_multiple)
