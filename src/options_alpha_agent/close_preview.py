"""Fail-closed exact-leg close preview construction.

The builder is deliberately broker-free. It converts an existing debit-spread
entry preview plus a fresh exact-leg quote mark into an inverse MLeg payload,
but it never submits that payload. A future execution adapter must apply the
same approval and kill-switch gates as entry execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

CONTRACT_MULTIPLIER = Decimal("100")
MAX_QUOTE_AGE_SECONDS = 300


class ClosePreviewError(ValueError):
    """Raised when a safe exact-leg close preview cannot be built."""


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ClosePreviewError(f"{field_name} must be numeric") from exc
    if not parsed.is_finite():
        raise ClosePreviewError(f"{field_name} must be finite")
    return parsed


def _timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ClosePreviewError(f"{field_name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClosePreviewError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ClosePreviewError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _leg_symbol(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isalnum()
        or value != value.upper()
        or not value
    ):
        raise ClosePreviewError("option leg symbol must be uppercase ASCII alphanumeric")
    return value


def _entry_legs(entry_preview: Mapping[str, Any]) -> tuple[str, int, list[Mapping[str, Any]]]:
    if entry_preview.get("paper") is not True or entry_preview.get("sent") is True:
        raise ClosePreviewError("an unexecuted paper entry preview is required")
    if entry_preview.get("order_class") != "mleg":
        raise ClosePreviewError("only a two-leg debit-spread close is supported")
    if entry_preview.get("type") != "limit" or entry_preview.get("time_in_force") != "day":
        raise ClosePreviewError("only a day limit MLeg close is supported")
    client_order_id = entry_preview.get("client_order_id")
    if not isinstance(client_order_id, str) or not client_order_id:
        raise ClosePreviewError("entry client_order_id is required")
    quantity = entry_preview.get("qty")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ClosePreviewError("entry qty must be a positive integer")
    raw_legs = entry_preview.get("legs")
    if not isinstance(raw_legs, list) or len(raw_legs) != 2:
        raise ClosePreviewError("exactly two entry legs are required")
    legs: list[Mapping[str, Any]] = []
    for raw_leg in raw_legs:
        if not isinstance(raw_leg, Mapping):
            raise ClosePreviewError("each entry leg must be an object")
        symbol = _leg_symbol(raw_leg.get("symbol"))
        side = raw_leg.get("side")
        ratio_qty = raw_leg.get("ratio_qty")
        if side not in {"buy", "sell"}:
            raise ClosePreviewError("entry leg side must be buy or sell")
        if isinstance(ratio_qty, bool) or not isinstance(ratio_qty, int) or ratio_qty != 1:
            raise ClosePreviewError("only one-to-one debit spreads are supported")
        legs.append({"symbol": symbol, "side": side, "ratio_qty": ratio_qty})
    if sorted(leg["side"] for leg in legs) != ["buy", "sell"]:
        raise ClosePreviewError("entry spread must contain one buy and one sell leg")
    return client_order_id, quantity, legs


def build_close_order_preview(
    entry_preview: Mapping[str, Any],
    quote_candidate: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_quote_age_seconds: int = MAX_QUOTE_AGE_SECONDS,
) -> dict[str, Any]:
    """Build an inverse exact-leg close payload without contacting Alpaca."""

    if not 1 <= max_quote_age_seconds <= 3_600:
        raise ClosePreviewError("max_quote_age_seconds must be between 1 and 3600")
    entry_id, quantity, entry_legs = _entry_legs(entry_preview)
    candidate_legs = quote_candidate.get("legs")
    if not isinstance(candidate_legs, list) or len(candidate_legs) != 2:
        raise ClosePreviewError("quote candidate must contain exactly two legs")
    candidate_by_symbol: dict[str, Mapping[str, Any]] = {}
    for raw_leg in candidate_legs:
        if not isinstance(raw_leg, Mapping):
            raise ClosePreviewError("each quote candidate leg must be an object")
        symbol = _leg_symbol(raw_leg.get("symbol"))
        candidate_by_symbol[symbol] = raw_leg
    if set(candidate_by_symbol) != {str(leg["symbol"]) for leg in entry_legs}:
        raise ClosePreviewError("quote candidate does not match the exact entry legs")

    cycle_time = now or datetime.now(UTC)
    if cycle_time.tzinfo is None:
        cycle_time = cycle_time.replace(tzinfo=UTC)
    else:
        cycle_time = cycle_time.astimezone(UTC)
    quote_times = [
        _timestamp(quote_candidate.get("long_quote_timestamp"), "long_quote_timestamp"),
        _timestamp(quote_candidate.get("short_quote_timestamp"), "short_quote_timestamp"),
    ]
    for quote_time in quote_times:
        age = (cycle_time - quote_time).total_seconds()
        if age < 0 or age > max_quote_age_seconds:
            raise ClosePreviewError("exact-leg quote is stale or from the future")

    long_bid = _decimal(quote_candidate.get("long_bid_per_share_usd"), "long_bid")
    short_ask = _decimal(quote_candidate.get("short_ask_per_share_usd"), "short_ask")
    if long_bid <= 0 or short_ask < 0:
        raise ClosePreviewError("close quote sides must be non-negative and executable")
    close_credit_per_share = long_bid - short_ask
    if close_credit_per_share <= 0:
        raise ClosePreviewError("close quote is not a positive executable credit")

    close_legs = [
        {
            "symbol": str(leg["symbol"]),
            "side": "sell" if leg["side"] == "buy" else "buy",
            "ratio_qty": 1,
        }
        for leg in entry_legs
    ]
    client_order_id = f"exit-{entry_id}"
    if len(client_order_id) > 48:
        client_order_id = client_order_id[:48]
    return {
        "client_order_id": client_order_id,
        "order_class": "mleg",
        "type": "limit",
        "time_in_force": "day",
        "qty": quantity,
        "limit_price": str(close_credit_per_share.quantize(Decimal("0.01"))),
        "legs": close_legs,
        "paper": True,
        "sent": False,
        "exit_only": True,
        "entry_client_order_id": entry_id,
        "expected_liquidation_value_usd": str(
            (close_credit_per_share * CONTRACT_MULTIPLIER * quantity).quantize(Decimal("0.01"))
        ),
        "quote_as_of": max(quote_times).isoformat(),
    }
