"""Read-only paper-account reconciliation and safe portfolio-state projection."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any

from options_alpha_agent.config import Settings
from options_alpha_agent.models import PortfolioState
from options_alpha_agent.order_lifecycle import (
    LifecycleError,
    classify_fill_state,
    evaluate_lifecycle,
)


class ReconciliationError(RuntimeError):
    """Raised when a paper-account snapshot cannot be trusted."""


def _plain(value: Any) -> Any:
    return getattr(value, "value", value)


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ReconciliationError(f"{field_name} is not numeric") from exc
    if not parsed.is_finite():
        raise ReconciliationError(f"{field_name} is not finite")
    return parsed


def _text(value: Any, field_name: str) -> str:
    plain = _plain(value)
    if plain is None:
        raise ReconciliationError(f"{field_name} is missing")
    text = str(plain)
    if not text or len(text) > 128:
        raise ReconciliationError(f"{field_name} is invalid")
    return text


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    symbol: str
    qty: str
    side: str
    avg_entry_price_usd: str
    market_value_usd: str
    unrealized_pl_usd: str
    unrealized_pl_pct: str

    def public_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    """Safe, read-only lifecycle state for one broker order.

    Alpaca's internal order UUID is represented only by a short SHA-256 digest.
    Order-level P&L is deliberately not inferred: Alpaca order snapshots expose
    fills, while current P&L is reconciled separately at the exact-position level.
    """

    client_order_id: str | None
    broker_order_ref: str | None
    status: str
    requested_qty: int | None
    filled_qty: int | None
    filled_avg_price_usd: str | None
    submitted_at: str | None
    filled_at: str | None
    lifecycle_action: str
    lifecycle_reasons: tuple[str, ...]
    assignment_manual_review: bool
    pnl_attribution: str

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["lifecycle_reasons"] = list(self.lifecycle_reasons)
        return result


@dataclass(frozen=True, slots=True)
class ReconciliationSnapshot:
    timestamp: str
    paper_mode: bool
    equity_usd: str
    last_equity_usd: str
    cash_usd: str
    buying_power_usd: str
    day_pnl_usd: str
    order_count: int
    filled_order_count: int
    open_order_count: int
    position_count: int
    positions: tuple[PositionSnapshot, ...]
    orders: tuple[OrderSnapshot, ...]
    market_open: bool
    next_open_at: str | None
    next_close_at: str | None
    order_lifecycle_counts: dict[str, int]

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["positions"] = [position.public_dict() for position in self.positions]
        result["orders"] = [order.public_dict() for order in self.orders]
        return result

    def portfolio_state(self, settings: Settings) -> PortfolioState:
        equity = Decimal(self.equity_usd)
        last_equity = Decimal(self.last_equity_usd)
        # Individual option max loss is not available from account marks alone.
        # Treat any existing position as the complete risk budget until a position
        # ledger with per-structure max loss is reconciled.
        deployed_risk = (
            equity * settings.max_portfolio_risk_pct if self.position_count else Decimal("0")
        )
        return PortfolioState(
            equity_usd=equity,
            start_of_day_equity_usd=last_equity,
            deployed_risk_usd=deployed_risk,
            open_positions=self.position_count,
        )


def _position_snapshot(position: Any) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=_text(getattr(position, "symbol", None), "position symbol"),
        qty=_text(getattr(position, "qty", None), "position quantity"),
        side=_text(getattr(position, "side", None), "position side"),
        avg_entry_price_usd=str(_decimal(getattr(position, "avg_entry_price", 0), "entry price")),
        market_value_usd=str(_decimal(getattr(position, "market_value", 0), "market value")),
        unrealized_pl_usd=str(_decimal(getattr(position, "unrealized_pl", 0), "unrealized P&L")),
        unrealized_pl_pct=str(
            _decimal(getattr(position, "unrealized_plpc", 0), "unrealized P&L percent")
        ),
    )


def _optional_decimal_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = _decimal(value, field_name)
    except ReconciliationError:
        return None
    return str(parsed)


def _optional_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _safe_client_order_id(value: Any) -> str | None:
    if value is None:
        return None
    candidate = str(_plain(value))
    if (
        not candidate
        or len(candidate) > 128
        or not candidate.isascii()
        or not all(character.isalnum() or character in "_-" for character in candidate)
    ):
        return None
    return candidate


def _broker_order_ref(value: Any) -> str | None:
    if value is None:
        return None
    digest = hashlib.sha256(str(_plain(value)).encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _order_snapshot(order: Any) -> OrderSnapshot:
    status = _text(getattr(order, "status", "unknown"), "order status").lower()
    requested_raw = getattr(order, "qty", 1)
    filled_raw = getattr(order, "filled_qty", 1 if status == "filled" else 0)
    try:
        fill_state = classify_fill_state(status, requested_raw, filled_raw)
        lifecycle = evaluate_lifecycle(fill_state)
        requested_qty: int | None = fill_state.requested_qty
        filled_qty: int | None = fill_state.filled_qty
        lifecycle_action = lifecycle.action
        lifecycle_reasons = lifecycle.reasons
        assignment_manual_review = lifecycle.assignment_manual_review
    except LifecycleError:
        requested_qty = None
        filled_qty = None
        lifecycle_action = "MANUAL_REVIEW"
        lifecycle_reasons = ("invalid_order_fill_payload",)
        assignment_manual_review = False

    average_price = _optional_decimal_text(
        getattr(order, "filled_avg_price", None),
        "filled average price",
    )
    if filled_qty and (average_price is None or Decimal(average_price) <= 0):
        lifecycle_action = "MANUAL_REVIEW"
        lifecycle_reasons = (*lifecycle_reasons, "filled_average_price_missing_or_invalid")

    return OrderSnapshot(
        client_order_id=_safe_client_order_id(getattr(order, "client_order_id", None)),
        broker_order_ref=_broker_order_ref(getattr(order, "id", None)),
        status=status,
        requested_qty=requested_qty,
        filled_qty=filled_qty,
        filled_avg_price_usd=average_price,
        submitted_at=_optional_timestamp(getattr(order, "submitted_at", None)),
        filled_at=_optional_timestamp(getattr(order, "filled_at", None)),
        lifecycle_action=lifecycle_action,
        lifecycle_reasons=lifecycle_reasons,
        assignment_manual_review=assignment_manual_review,
        pnl_attribution="position_level_only",
    )


def reconcile_paper_account(
    settings: Settings,
    *,
    client: Any | None = None,
    now: datetime | None = None,
) -> ReconciliationSnapshot:
    """Fetch account, orders, and positions without exposing IDs or mutating state."""

    if not settings.alpaca_paper:
        raise ReconciliationError("paper mode is required")
    if not settings.has_alpaca_credentials and client is None:
        raise ReconciliationError("Alpaca credentials are required")
    if client is None:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        client = TradingClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper=True,
        )
        orders_request = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=500)
    else:
        orders_request = SimpleNamespace(status="all", limit=500)

    account = client.get_account()
    orders = client.get_orders(orders_request)
    positions = client.get_all_positions()
    clock = client.get_clock()
    market_open = getattr(clock, "is_open", None)
    if not isinstance(market_open, bool):
        raise ReconciliationError("Alpaca market clock did not return a boolean state")
    equity = _decimal(getattr(account, "equity", None), "equity")
    last_equity = _decimal(getattr(account, "last_equity", None), "last equity")
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    else:
        timestamp = timestamp.astimezone(UTC)
    safe_orders = tuple(_order_snapshot(order) for order in orders)
    status_counts = Counter(order.status for order in safe_orders)
    lifecycle_counts = Counter(order.lifecycle_action for order in safe_orders)
    filled = sum(count for status, count in status_counts.items() if status == "filled")
    closed_statuses = {
        "filled",
        "canceled",
        "expired",
        "replaced",
        "rejected",
        "done_for_day",
        "stopped",
        "suspended",
    }
    open_orders = sum(
        count for status, count in status_counts.items() if status not in closed_statuses
    )
    safe_positions = tuple(_position_snapshot(position) for position in positions)
    return ReconciliationSnapshot(
        timestamp=timestamp.isoformat(),
        paper_mode=True,
        equity_usd=str(equity),
        last_equity_usd=str(last_equity),
        cash_usd=str(_decimal(getattr(account, "cash", None), "cash")),
        buying_power_usd=str(_decimal(getattr(account, "buying_power", None), "buying power")),
        day_pnl_usd=str(equity - last_equity),
        order_count=len(orders),
        filled_order_count=filled,
        open_order_count=open_orders,
        position_count=len(safe_positions),
        positions=safe_positions,
        orders=safe_orders,
        market_open=market_open,
        next_open_at=str(getattr(clock, "next_open", "")) or None,
        next_close_at=str(getattr(clock, "next_close", "")) or None,
        order_lifecycle_counts=dict(lifecycle_counts),
    )


def append_reconciliation_audit(
    snapshot: ReconciliationSnapshot,
    *,
    audit_log: Any,
) -> None:
    """Write a safe account/P&L event through the existing hash chain."""

    for order in snapshot.orders:
        audit_log.append(
            {
                "timestamp": snapshot.timestamp,
                "event_type": "paper_order_reconciliation",
                "paper_mode": snapshot.paper_mode,
                "order": order.public_dict(),
                "order_sent": False,
            }
        )
    audit_log.append(
        {
            "timestamp": snapshot.timestamp,
            "event_type": "account_reconciliation",
            "paper_mode": snapshot.paper_mode,
            "snapshot": snapshot.public_dict(),
            "order_sent": False,
        }
    )
