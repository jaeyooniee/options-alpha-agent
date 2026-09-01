"""Normalize option-chain records into safe, deterministic strategy candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from options_alpha_agent.ai import ALLOWED_AI_STRATEGIES

MIN_OPEN_INTEREST = 100
MAX_SPREAD_PCT = Decimal("0.15")
PRODUCTION_MIN_DTE = 2
PRODUCTION_MAX_DTE = 10
TARGET_DTE = 5
LONG_DELTA_TARGET = Decimal("0.45")
SHORT_DELTA_TARGET = Decimal("0.25")
MAX_CLOCK_SKEW_SECONDS = 60


class MarketEvidenceError(ValueError):
    """Raised when a chain record cannot support a safe candidate."""


def _decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise MarketEvidenceError(f"{field_name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MarketEvidenceError(f"{field_name} must be numeric") from exc
    if not parsed.is_finite():
        raise MarketEvidenceError(f"{field_name} must be finite")
    return parsed


def _date(value: Any, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError as exc:
            raise MarketEvidenceError(f"{field_name} must be an ISO date") from exc
    raise MarketEvidenceError(f"{field_name} must be an ISO date")


def _contract(row: Mapping[str, Any]) -> dict[str, Any]:
    symbol = row.get("symbol")
    option_type = row.get("option_type")
    if (
        not isinstance(symbol, str)
        or not symbol.isascii()
        or not symbol.isalnum()
        or symbol != symbol.upper()
    ):
        raise MarketEvidenceError("option symbol must be uppercase ASCII alphanumeric")
    if option_type not in {"call", "put"}:
        raise MarketEvidenceError("option_type must be call or put")
    strike = _decimal(row.get("strike"), "strike")
    bid = _decimal(row.get("bid"), "bid")
    ask = _decimal(row.get("ask"), "ask")
    open_interest = row.get("open_interest")
    if isinstance(open_interest, bool) or not isinstance(open_interest, int):
        raise MarketEvidenceError("open_interest must be an integer")
    expiration = _date(row.get("expiration"), "expiration")
    if strike <= 0 or bid <= 0 or ask < bid or open_interest < MIN_OPEN_INTEREST:
        raise MarketEvidenceError("option quote is not tradable under the safety filter")
    midpoint = (bid + ask) / Decimal("2")
    spread_pct = (ask - bid) / midpoint
    if spread_pct > MAX_SPREAD_PCT:
        raise MarketEvidenceError("option spread is too wide")
    result = {
        "symbol": symbol,
        "option_type": option_type,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "open_interest": open_interest,
        "expiration": expiration,
        "spread_pct": spread_pct,
    }
    quote_timestamp = _quote_datetime(row.get("quote_timestamp"))
    if quote_timestamp is not None:
        result["quote_timestamp"] = quote_timestamp.isoformat()
    implied_volatility = _optional_number(row.get("implied_volatility"))
    if implied_volatility is not None:
        result["implied_volatility"] = implied_volatility
    raw_greeks = row.get("greeks")
    if isinstance(raw_greeks, Mapping):
        greeks = {
            name: value
            for name in ("delta", "gamma", "rho", "theta", "vega")
            if (value := _optional_number(raw_greeks.get(name))) is not None
        }
        if greeks:
            result["greeks"] = greeks
    return result


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _enum_text(value: Any) -> str:
    return str(getattr(value, "value", value)).lower()


def _quote_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _optional_number(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return str(parsed) if parsed.is_finite() else None


def _greeks(snapshot: Any) -> dict[str, str] | None:
    raw_greeks = _field(snapshot, "greeks")
    if raw_greeks is None:
        return None
    values = {
        name: _optional_number(_field(raw_greeks, name))
        for name in ("delta", "gamma", "rho", "theta", "vega")
    }
    result = {name: value for name, value in values.items() if value is not None}
    return result or None


def alpaca_contract_rows(
    contracts: Sequence[Any],
    snapshots: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: int = 300,
) -> list[dict[str, Any]]:
    """Convert Alpaca contract metadata plus indicative snapshots into safe rows."""

    if max_age_seconds < 1:
        raise ValueError("max_age_seconds must be positive")
    cutoff = None
    if now is not None:
        normalized_now = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
        cutoff = normalized_now - timedelta(seconds=max_age_seconds)
    rows: list[dict[str, Any]] = []
    for contract in contracts:
        symbol = _field(contract, "symbol")
        snapshot = snapshots.get(symbol)
        quote = _field(snapshot, "latest_quote") if snapshot is not None else None
        quote_time = _quote_datetime(_field(quote, "timestamp")) if quote is not None else None
        if not isinstance(symbol, str) or quote is None or quote_time is None:
            continue
        if cutoff is not None and (
            quote_time < cutoff
            or quote_time > normalized_now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)
        ):
            continue
        try:
            open_interest = int(str(_field(contract, "open_interest")))
            row = {
                "symbol": symbol,
                "option_type": _enum_text(_field(contract, "type")),
                "strike": _field(contract, "strike_price"),
                "expiration": _field(contract, "expiration_date"),
                "bid": _field(quote, "bid_price"),
                "ask": _field(quote, "ask_price"),
                "open_interest": open_interest,
                "quote_timestamp": quote_time.isoformat(),
            }
            implied_volatility = _optional_number(_field(snapshot, "implied_volatility"))
            if implied_volatility is not None:
                row["implied_volatility"] = implied_volatility
            greeks = _greeks(snapshot)
            if greeks is not None:
                row["greeks"] = greeks
            _contract(row)
        except (TypeError, ValueError, MarketEvidenceError):
            continue
        rows.append(row)
    return rows


def _public_leg(contract: Mapping[str, Any], side: str) -> dict[str, Any]:
    return {
        "symbol": contract["symbol"],
        "side": side,
        "ratio_qty": 1,
    }


def _abs_delta(contract: Mapping[str, Any]) -> Decimal | None:
    """Return absolute option delta when Alpaca supplied a usable Greek."""

    greeks = contract.get("greeks")
    if not isinstance(greeks, Mapping):
        return None
    raw_delta = greeks.get("delta")
    if raw_delta is None:
        return None
    try:
        delta = _decimal(raw_delta, "delta")
    except MarketEvidenceError:
        return None
    return abs(delta) if Decimal("0") < abs(delta) < Decimal("1") else None


def _delta_distance(contract: Mapping[str, Any], target: Decimal) -> Decimal:
    """Prefer a usable target delta but retain fail-closed quote/OI safeguards.

    Some free indicative records may omit Greeks temporarily. Such a contract is
    not promoted over a comparable contract with a valid delta, but remains in
    the catalog so the downstream evidence/AI boundary can abstain rather than
    treating a transient missing Greek as invented data.
    """

    delta = _abs_delta(contract)
    return abs(delta - target) if delta is not None else Decimal("10")


def _candidate(
    strategy: str,
    long_contract: Mapping[str, Any],
    short_contract: Mapping[str, Any] | None = None,
    *,
    as_of: date,
) -> dict[str, Any]:
    debit = long_contract["ask"]
    width = Decimal("0")
    legs = [_public_leg(long_contract, "buy")]
    if short_contract is not None:
        debit -= short_contract["bid"]
        width = abs(long_contract["strike"] - short_contract["strike"])
        legs.append(_public_leg(short_contract, "sell"))
    if debit <= 0:
        raise MarketEvidenceError("candidate debit must be positive")
    if short_contract is not None and width <= debit:
        raise MarketEvidenceError("debit spread must have positive bounded payoff width")
    result = {
        "contract_symbol": long_contract["symbol"],
        "strategy": strategy,
        "days_to_expiry": (long_contract["expiration"] - as_of).days,
        "bid_ask_spread_pct": max(
            long_contract["spread_pct"],
            short_contract["spread_pct"] if short_contract is not None else Decimal("0"),
        ),
        "min_open_interest": min(
            long_contract["open_interest"],
            short_contract["open_interest"]
            if short_contract is not None
            else long_contract["open_interest"],
        ),
        "defined_risk": True,
        "debit_per_share_usd": debit,
        "max_loss_per_share_usd": debit,
        "width_per_share_usd": width,
        # Preserve the executable sides of the indicative market so later
        # shadow cycles can mark the exact structure conservatively.  Entry
        # uses long ask / short bid; liquidation uses long bid / short ask.
        "long_bid_per_share_usd": long_contract["bid"],
        "long_ask_per_share_usd": long_contract["ask"],
        "short_bid_per_share_usd": (short_contract["bid"] if short_contract is not None else None),
        "short_ask_per_share_usd": (short_contract["ask"] if short_contract is not None else None),
        "long_quote_timestamp": long_contract.get("quote_timestamp"),
        "short_quote_timestamp": (
            short_contract.get("quote_timestamp") if short_contract is not None else None
        ),
        "legs": legs,
        "target_days_to_expiry": TARGET_DTE,
        "long_abs_delta": _abs_delta(long_contract),
    }
    if long_contract.get("implied_volatility") is not None:
        result["long_implied_volatility"] = long_contract["implied_volatility"]
    if short_contract is not None and short_contract.get("implied_volatility") is not None:
        result["short_implied_volatility"] = short_contract["implied_volatility"]
    if long_contract.get("greeks") is not None:
        result["long_greeks"] = long_contract["greeks"]
    if short_contract is not None and short_contract.get("greeks") is not None:
        result["short_greeks"] = short_contract["greeks"]
    if short_contract is not None:
        result["short_abs_delta"] = _abs_delta(short_contract)
    return result


def _eligible(rows: Sequence[Mapping[str, Any]], as_of: date) -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    for row in rows:
        try:
            contract = _contract(row)
        except MarketEvidenceError:
            continue
        dte = (contract["expiration"] - as_of).days
        if PRODUCTION_MIN_DTE <= dte <= PRODUCTION_MAX_DTE:
            eligible.append(contract)
    return eligible


def select_option_candidate(
    rows: Sequence[Mapping[str, Any]],
    strategy: str,
    *,
    spot: Decimal,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Select one defined-risk candidate from normalized chain-like records."""

    if strategy not in ALLOWED_AI_STRATEGIES:
        raise MarketEvidenceError("strategy is not in the options-only allowlist")
    if not spot.is_finite() or spot <= 0:
        raise MarketEvidenceError("spot must be a positive finite number")
    valuation_date = as_of or date.today()
    eligible = _eligible(rows, valuation_date)
    same_type = [
        row for row in eligible if row["option_type"] == ("call" if "call" in strategy else "put")
    ]
    if not same_type:
        raise MarketEvidenceError("no eligible option contracts for strategy")

    if strategy in {"long_call", "long_put"}:
        selected = min(
            same_type,
            key=lambda row: (
                abs((row["expiration"] - valuation_date).days - TARGET_DTE),
                _delta_distance(row, LONG_DELTA_TARGET),
                abs(row["strike"] - spot),
                row["spread_pct"],
                -row["open_interest"],
            ),
        )
        result = _candidate(strategy, selected, as_of=valuation_date)
    else:
        by_expiration: dict[date, list[dict[str, Any]]] = {}
        for row in same_type:
            by_expiration.setdefault(row["expiration"], []).append(row)
        pairs: list[tuple[tuple[Decimal, Decimal, int], dict[str, Any]]] = []
        for expiration, contracts in by_expiration.items():
            for long_contract in contracts:
                for short_contract in contracts:
                    if strategy == "call_debit_spread":
                        valid_direction = long_contract["strike"] < short_contract["strike"]
                    else:
                        valid_direction = long_contract["strike"] > short_contract["strike"]
                    if not valid_direction or long_contract["symbol"] == short_contract["symbol"]:
                        continue
                    try:
                        candidate = _candidate(
                            strategy,
                            long_contract,
                            short_contract,
                            as_of=valuation_date,
                        )
                    except MarketEvidenceError:
                        continue
                    candidate["days_to_expiry"] = (expiration - valuation_date).days
                    width_distance = abs(candidate["width_per_share_usd"] - spot * Decimal("0.02"))
                    pairs.append(
                        (
                            (
                                abs((expiration - valuation_date).days - TARGET_DTE),
                                _delta_distance(long_contract, LONG_DELTA_TARGET),
                                _delta_distance(short_contract, SHORT_DELTA_TARGET),
                                width_distance,
                                candidate["bid_ask_spread_pct"],
                                -candidate["min_open_interest"],
                            ),
                            candidate,
                        )
                    )
        if not pairs:
            raise MarketEvidenceError("no bounded debit spread could be constructed")
        result = min(pairs, key=lambda pair: pair[0])[1]

    return {
        key: str(value) if isinstance(value, Decimal) else value for key, value in result.items()
    }


def build_market_evidence(
    underlying: str,
    spot: Decimal,
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: date | None = None,
    source: str = "alpaca_options_indicative",
    data_fresh: bool = True,
    signal: Mapping[str, Any] | None = None,
    intraday_signal: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an AI-safe evidence pack with all four candidate structures."""

    symbol = underlying.upper()
    valuation_date = as_of or date.today()
    catalog: dict[str, Any] = {}
    failures: dict[str, str] = {}
    for strategy in sorted(ALLOWED_AI_STRATEGIES):
        try:
            catalog[strategy] = select_option_candidate(
                rows,
                strategy,
                spot=spot,
                as_of=valuation_date,
            )
        except MarketEvidenceError as exc:
            failures[strategy] = type(exc).__name__
    return {
        "underlying": symbol,
        "source": source,
        "as_of": datetime.combine(valuation_date, datetime.min.time(), tzinfo=UTC).isoformat(),
        "spot": str(spot),
        "data_fresh": data_fresh,
        "market_data_available": bool(catalog),
        "candidate_catalog": catalog,
        "candidate_failures": failures,
        "signal": dict(signal) if signal is not None else {"status": "unavailable"},
        "intraday_signal": (
            dict(intraday_signal) if intraday_signal is not None else {"status": "unavailable"}
        ),
    }
