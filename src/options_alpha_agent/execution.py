"""Explicitly approved paper-order adapter with idempotency and audit gates."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from options_alpha_agent.ai import AuditLog, audit_log_for_settings
from options_alpha_agent.config import Settings
from options_alpha_agent.shadow import ShadowEvaluation

CLIENT_ORDER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,48}$")


class ExecutionValidationError(ValueError):
    """Raised when a preview cannot be converted into a safe paper request."""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: str
    order_sent: bool
    client_order_id: str | None
    broker_order_ref: str | None
    error_type: str | None

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "order_sent": self.order_sent,
            "client_order_id": self.client_order_id,
            "broker_order_ref": self.broker_order_ref,
            "error_type": self.error_type,
        }


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ExecutionValidationError(f"{field_name} must be numeric") from exc
    if not parsed.is_finite():
        raise ExecutionValidationError(f"{field_name} must be finite")
    return parsed


def _validate_preview(
    preview: Mapping[str, Any],
) -> tuple[str, int, Decimal, list[Mapping[str, Any]]]:
    if preview.get("paper") is not True:
        raise ExecutionValidationError("paper preview is required")
    order_class = preview.get("order_class")
    if order_class not in {"simple", "mleg"}:
        raise ExecutionValidationError("simple or mleg order class is required")
    if preview.get("type") != "limit" or preview.get("time_in_force") != "day":
        raise ExecutionValidationError("only day limit MLeg orders are supported")
    client_order_id = preview.get("client_order_id")
    if not isinstance(client_order_id, str) or not CLIENT_ORDER_ID_RE.fullmatch(client_order_id):
        raise ExecutionValidationError("client_order_id has an invalid format")
    quantity = preview.get("qty")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ExecutionValidationError("qty must be a positive integer")
    limit_price = _decimal(preview.get("limit_price"), "limit_price")
    if limit_price <= 0:
        raise ExecutionValidationError("limit_price must be positive")
    raw_legs = preview.get("legs")
    if not isinstance(raw_legs, list) or not 1 <= len(raw_legs) <= 4:
        raise ExecutionValidationError("MLeg orders require between 1 and 4 legs")
    if order_class == "mleg" and len(raw_legs) < 2:
        raise ExecutionValidationError("MLeg orders require at least 2 legs")
    if order_class == "simple" and len(raw_legs) != 1:
        raise ExecutionValidationError("simple option orders require one leg")
    legs: list[Mapping[str, Any]] = []
    for leg in raw_legs:
        if not isinstance(leg, Mapping):
            raise ExecutionValidationError("each order leg must be an object")
        symbol = leg.get("symbol")
        if (
            not isinstance(symbol, str)
            or not symbol.isascii()
            or not symbol.isalnum()
            or symbol != symbol.upper()
        ):
            raise ExecutionValidationError("each leg symbol must be uppercase ASCII alphanumeric")
        if leg.get("side") not in {"buy", "sell"}:
            raise ExecutionValidationError("each leg side must be buy or sell")
        ratio = leg.get("ratio_qty")
        if isinstance(ratio, bool) or not isinstance(ratio, int) or ratio < 1:
            raise ExecutionValidationError("each leg ratio_qty must be a positive integer")
        legs.append(leg)
    sides = [leg["side"] for leg in legs]
    if len(legs) == 1 and sides != ["buy"]:
        raise ExecutionValidationError("a long option order must have one buy leg")
    if len(legs) >= 2 and sides.count("buy") == 0:
        raise ExecutionValidationError("a multi-leg order requires a buy leg")
    if order_class == "simple" and preview.get("symbol") != legs[0]["symbol"]:
        raise ExecutionValidationError("simple order symbol must match its leg")
    if order_class == "simple" and preview.get("side") != "buy":
        raise ExecutionValidationError("simple option order must be a buy")
    return client_order_id, quantity, limit_price, legs


def _build_alpaca_request(preview: Mapping[str, Any]) -> Any:
    """Build the official alpaca-py request only after all local gates pass."""

    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
    from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest

    client_order_id, quantity, limit_price, legs = _validate_preview(preview)
    order_legs = [
        OptionLegRequest(
            symbol=str(leg["symbol"]),
            ratio_qty=float(leg["ratio_qty"]),
            side=OrderSide.BUY if leg["side"] == "buy" else OrderSide.SELL,
        )
        for leg in legs
    ]
    if preview.get("order_class") == "simple":
        return LimitOrderRequest(
            symbol=str(preview["symbol"]),
            qty=quantity,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            limit_price=float(limit_price),
            client_order_id=client_order_id,
        )
    return LimitOrderRequest(
        qty=quantity,
        order_class=OrderClass.MLEG,
        time_in_force=TimeInForce.DAY,
        legs=order_legs,
        limit_price=float(limit_price),
        client_order_id=client_order_id,
    )


def _broker_ref(response: Any) -> str | None:
    value = getattr(response, "id", None)
    if value is None:
        return None
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def submit_paper_order(
    settings: Settings,
    evaluation: ShadowEvaluation,
    *,
    audit_log: AuditLog | None = None,
    client: Any | None = None,
    now: datetime | None = None,
) -> ExecutionResult:
    """Submit only an explicitly approved, risk-checked paper MLeg preview."""

    audit = audit_log or audit_log_for_settings(settings)
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    else:
        timestamp = timestamp.astimezone(UTC)
    preview = evaluation.order_preview
    client_order_id = preview.get("client_order_id") if isinstance(preview, Mapping) else None

    def blocked(status: str, error_type: str) -> ExecutionResult:
        audit.append(
            {
                "timestamp": timestamp.isoformat(),
                "event_type": "order_blocked",
                "status": status,
                "error_type": error_type,
                "client_order_id": client_order_id,
                "trade_execution_enabled": settings.trade_execution_enabled,
                "paper_order_approved": settings.paper_order_approved,
                "order_sent": False,
            }
        )
        return ExecutionResult(status, False, client_order_id, None, error_type)

    if not settings.alpaca_paper:
        return blocked("blocked", "paper_mode_required")
    if not settings.trade_execution_enabled:
        return blocked("disabled", "execution_disabled")
    if settings.trading_kill_switch:
        return blocked("blocked", "trading_kill_switch_enabled")
    if not settings.paper_order_approved:
        return blocked("blocked", "paper_order_not_approved")
    if evaluation.status != "preview_ready" or not evaluation.risk_decision.allowed:
        return blocked("blocked", "risk_preview_required")
    if not isinstance(preview, Mapping):
        return blocked("blocked", "order_preview_missing")

    try:
        client_order_id, _, _, legs = _validate_preview(preview)
        for event in audit.events():
            if (
                event.get("event_type") == "order_submitted"
                and event.get("client_order_id") == client_order_id
            ):
                return blocked("duplicate", "client_order_id_already_submitted")
        if evaluation.proposal is not None and any(
            not str(leg["symbol"]).startswith(evaluation.proposal.underlying) for leg in legs
        ):
            raise ExecutionValidationError("order leg does not match proposal underlying")
        request = _build_alpaca_request(preview)
        audit.append(
            {
                "timestamp": timestamp.isoformat(),
                "event_type": "order_submit_intent",
                "status": "ready",
                "client_order_id": client_order_id,
                "order_class": preview["order_class"],
                "paper": True,
                "order_sent": False,
            }
        )
        if client is None:
            if not settings.has_alpaca_credentials:
                return blocked("blocked", "missing_alpaca_credentials")
            from alpaca.trading.client import TradingClient

            client = TradingClient(
                settings.alpaca_api_key,
                settings.alpaca_secret_key,
                paper=True,
            )
        response = client.submit_order(request)
        broker_order_ref = _broker_ref(response)
        audit.append(
            {
                "timestamp": timestamp.isoformat(),
                "event_type": "order_submitted",
                "status": str(getattr(response, "status", "submitted")),
                "client_order_id": client_order_id,
                "broker_order_ref": broker_order_ref,
                "paper": True,
                "order_sent": True,
            }
        )
        return ExecutionResult("submitted", True, client_order_id, broker_order_ref, None)
    except Exception as exc:  # noqa: BLE001 - execution boundary must fail closed
        with suppress(Exception):
            audit.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "event_type": "order_submit_failed",
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "client_order_id": client_order_id,
                    "order_sent": False,
                }
            )
        return ExecutionResult("failed", False, client_order_id, None, type(exc).__name__)
