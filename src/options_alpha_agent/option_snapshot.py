"""Strict validation for versioned read-only option-chain snapshots."""

from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from options_alpha_agent.config import Settings
from options_alpha_agent.provenance import file_sha256

OCC_SYMBOL = re.compile(r"^([A-Z0-9]{1,6})(\d{6})([CP])(\d{8})$")
SNAPSHOT_COLUMNS = (
    "underlying",
    "underlying_quote_timestamp",
    "underlying_bid",
    "underlying_ask",
    "feed",
    "symbol",
    "option_quote_timestamp",
    "bid",
    "ask",
    "bid_size",
    "ask_size",
    "implied_volatility",
    "delta",
    "gamma",
    "theta",
    "vega",
)
REQUIRED_COLUMNS = set(SNAPSHOT_COLUMNS)


class OptionSnapshotError(ValueError):
    """Raised when a research snapshot cannot be trusted."""


def _decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise OptionSnapshotError(f"{field_name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OptionSnapshotError(f"{field_name} must be numeric") from exc
    if not parsed.is_finite():
        raise OptionSnapshotError(f"{field_name} must be finite")
    return parsed


def _integer(value: Any, field_name: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise OptionSnapshotError(f"{field_name} must be an integer") from exc
    if str(parsed) != str(value).strip() or parsed < 0:
        raise OptionSnapshotError(f"{field_name} must be a non-negative integer")
    return parsed


def _timestamp(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OptionSnapshotError(f"{field_name} must be an ISO-8601 string") from exc
    else:
        raise OptionSnapshotError(f"{field_name} must be an ISO-8601 string")
    if parsed.tzinfo is None:
        raise OptionSnapshotError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


@dataclass(frozen=True, slots=True)
class OptionSnapshotRow:
    underlying: str
    underlying_quote_timestamp: datetime
    underlying_bid: Decimal
    underlying_ask: Decimal
    feed: str
    symbol: str
    option_quote_timestamp: datetime
    option_type: str
    expiration: str
    strike: Decimal
    bid: Decimal
    ask: Decimal
    bid_size: int
    ask_size: int
    implied_volatility: Decimal
    delta: Decimal
    gamma: Decimal
    theta: Decimal
    vega: Decimal


@dataclass(frozen=True, slots=True)
class OptionSnapshotSummary:
    underlying: str
    feed: str
    record_count: int
    call_count: int
    put_count: int
    quote_start: str
    quote_end: str
    expiration_dates: tuple[str, ...]
    strike_min: Decimal
    strike_max: Decimal
    duplicate_symbols: int
    order_sent: bool = False

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["expiration_dates"] = list(self.expiration_dates)
        result["strike_min"] = str(self.strike_min)
        result["strike_max"] = str(self.strike_max)
        return result


@dataclass(frozen=True, slots=True)
class OptionSnapshotCaptureReport:
    underlying: str
    source: str
    stock_feed: str
    option_feed: str
    expiration: str
    strike_window_pct: Decimal
    max_age_seconds: int
    output_path: str
    sha256: str
    summary: OptionSnapshotSummary
    order_sent: bool = False

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["strike_window_pct"] = str(self.strike_window_pct)
        result["summary"] = self.summary.public_dict()
        return result


def _row(record: dict[str, str]) -> OptionSnapshotRow:
    underlying = str(record.get("underlying", "")).strip().upper()
    symbol = str(record.get("symbol", "")).strip().upper()
    match = OCC_SYMBOL.fullmatch(symbol)
    if not underlying or match is None or match.group(1) != underlying:
        raise OptionSnapshotError("symbol must be a valid OCC contract for the underlying")
    feed = str(record.get("feed", "")).strip().lower()
    if feed not in {"indicative", "opra"}:
        raise OptionSnapshotError("feed must be indicative or opra")
    underlying_bid = _decimal(record.get("underlying_bid"), "underlying_bid")
    underlying_ask = _decimal(record.get("underlying_ask"), "underlying_ask")
    bid = _decimal(record.get("bid"), "bid")
    ask = _decimal(record.get("ask"), "ask")
    implied_volatility = _decimal(record.get("implied_volatility"), "implied_volatility")
    delta = _decimal(record.get("delta"), "delta")
    gamma = _decimal(record.get("gamma"), "gamma")
    theta = _decimal(record.get("theta"), "theta")
    vega = _decimal(record.get("vega"), "vega")
    if underlying_bid <= 0 or underlying_ask < underlying_bid:
        raise OptionSnapshotError("underlying quote must be positive and non-crossed")
    if bid < 0 or ask <= 0 or ask < bid:
        raise OptionSnapshotError("option quote must be non-negative and non-crossed")
    if implied_volatility <= 0:
        raise OptionSnapshotError("implied_volatility must be positive")
    if not Decimal("-1") <= delta <= Decimal("1"):
        raise OptionSnapshotError("delta must be between -1 and 1")
    if gamma < 0 or vega < 0:
        raise OptionSnapshotError("gamma and vega cannot be negative")
    strike = Decimal(match.group(4)) / Decimal("1000")
    expiration = datetime.strptime(match.group(2), "%y%m%d").date().isoformat()
    return OptionSnapshotRow(
        underlying=underlying,
        underlying_quote_timestamp=_timestamp(
            record.get("underlying_quote_timestamp"), "underlying_quote_timestamp"
        ),
        underlying_bid=underlying_bid,
        underlying_ask=underlying_ask,
        feed=feed,
        symbol=symbol,
        option_quote_timestamp=_timestamp(
            record.get("option_quote_timestamp"), "option_quote_timestamp"
        ),
        option_type="call" if match.group(3) == "C" else "put",
        expiration=expiration,
        strike=strike,
        bid=bid,
        ask=ask,
        bid_size=_integer(record.get("bid_size"), "bid_size"),
        ask_size=_integer(record.get("ask_size"), "ask_size"),
        implied_volatility=implied_volatility,
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
    )


def load_option_snapshot(path: str | Path) -> list[OptionSnapshotRow]:
    csv_path = Path(path)
    if not csv_path.is_file():
        raise OptionSnapshotError("option snapshot CSV does not exist")
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or set(reader.fieldnames) != REQUIRED_COLUMNS:
                raise OptionSnapshotError("option snapshot columns do not match the schema")
            rows = [_row(record) for record in reader]
    except OSError as exc:
        raise OptionSnapshotError("option snapshot CSV could not be read") from exc
    if not rows:
        raise OptionSnapshotError("option snapshot CSV has no records")
    return rows


def summarize_option_snapshot(rows: list[OptionSnapshotRow]) -> OptionSnapshotSummary:
    if not rows:
        raise OptionSnapshotError("option snapshot has no records")
    underlyings = {row.underlying for row in rows}
    feeds = {row.feed for row in rows}
    underlying_quotes = {
        (row.underlying_quote_timestamp, row.underlying_bid, row.underlying_ask) for row in rows
    }
    if len(underlyings) != 1 or len(feeds) != 1 or len(underlying_quotes) != 1:
        raise OptionSnapshotError("snapshot metadata must be internally consistent")
    symbols = [row.symbol for row in rows]
    duplicates = len(symbols) - len(set(symbols))
    if duplicates:
        raise OptionSnapshotError("snapshot contains duplicate symbols")
    timestamps = [row.option_quote_timestamp for row in rows]
    strikes = [row.strike for row in rows]
    return OptionSnapshotSummary(
        underlying=next(iter(underlyings)),
        feed=next(iter(feeds)),
        record_count=len(rows),
        call_count=sum(row.option_type == "call" for row in rows),
        put_count=sum(row.option_type == "put" for row in rows),
        quote_start=min(timestamps).isoformat(),
        quote_end=max(timestamps).isoformat(),
        expiration_dates=tuple(sorted({row.expiration for row in rows})),
        strike_min=min(strikes),
        strike_max=max(strikes),
        duplicate_symbols=duplicates,
    )


def _expiration(value: str | date) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise OptionSnapshotError("expiration must be YYYY-MM-DD") from exc


def _capture_size(value: Any, field_name: str) -> str:
    parsed = _decimal(value, field_name)
    if parsed < 0 or parsed != parsed.to_integral_value():
        raise OptionSnapshotError(f"{field_name} must be a non-negative integer")
    return str(int(parsed))


def capture_option_snapshot(
    settings: Settings,
    underlying: str,
    expiration: str | date,
    output_path: str | Path,
    *,
    strike_window_pct: Decimal = Decimal("0.02"),
    max_age_seconds: int = 300,
    stock_client: Any | None = None,
    option_client: Any | None = None,
    now: datetime | None = None,
) -> OptionSnapshotCaptureReport:
    """Capture one fresh IEX/indicative option snapshot without broker mutation."""

    if not settings.has_alpaca_credentials:
        raise OptionSnapshotError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
    if not settings.alpaca_paper:
        raise OptionSnapshotError("paper mode is required")
    symbol = underlying.strip().upper()
    if not symbol.isascii() or not symbol.isalnum() or not 1 <= len(symbol) <= 6:
        raise OptionSnapshotError("underlying must be a short uppercase symbol")
    if not strike_window_pct.is_finite() or not Decimal("0.005") <= strike_window_pct <= Decimal(
        "0.10"
    ):
        raise OptionSnapshotError("strike_window_pct must be between 0.005 and 0.10")
    if not 1 <= max_age_seconds <= 3_600:
        raise OptionSnapshotError("max_age_seconds must be between 1 and 3600")
    destination = Path(output_path)
    if destination.is_absolute() or ".." in destination.parts:
        raise OptionSnapshotError("output_path must be workspace-relative")
    if destination.exists():
        raise OptionSnapshotError("output_path already exists; snapshots are immutable")

    reference_time = _timestamp(now or datetime.now(UTC), "now")
    expiration_date = _expiration(expiration)
    days_to_expiry = (expiration_date - reference_time.date()).days
    if not 1 <= days_to_expiry <= 45:
        raise OptionSnapshotError("expiration must be 1 to 45 days after capture time")

    if stock_client is None or option_client is None:
        from alpaca.data.enums import DataFeed, OptionsFeed
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.data.requests import OptionChainRequest, StockLatestQuoteRequest
    else:
        DataFeed = SimpleNamespace(IEX="iex")
        OptionsFeed = SimpleNamespace(INDICATIVE="indicative")
        OptionChainRequest = SimpleNamespace
        StockLatestQuoteRequest = SimpleNamespace

    stock_client = stock_client or StockHistoricalDataClient(
        settings.alpaca_api_key,
        settings.alpaca_secret_key,
    )
    option_client = option_client or OptionHistoricalDataClient(
        settings.alpaca_api_key,
        settings.alpaca_secret_key,
    )
    quotes = stock_client.get_stock_latest_quote(
        StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
    )
    underlying_quote = quotes[symbol]
    underlying_bid = _decimal(_field(underlying_quote, "bid_price"), "underlying_bid")
    underlying_ask = _decimal(_field(underlying_quote, "ask_price"), "underlying_ask")
    underlying_timestamp = _timestamp(
        _field(underlying_quote, "timestamp"), "underlying_quote_timestamp"
    )
    if underlying_bid <= 0 or underlying_ask < underlying_bid:
        raise OptionSnapshotError("underlying quote must be positive and non-crossed")
    if not 0 <= (reference_time - underlying_timestamp).total_seconds() <= max_age_seconds:
        raise OptionSnapshotError("underlying quote is stale or from the future")
    spot = (underlying_bid + underlying_ask) / Decimal("2")

    chain = option_client.get_option_chain(
        OptionChainRequest(
            underlying_symbol=symbol,
            feed=OptionsFeed.INDICATIVE,
            strike_price_gte=float(spot * (Decimal("1") - strike_window_pct)),
            strike_price_lte=float(spot * (Decimal("1") + strike_window_pct)),
            expiration_date=expiration_date,
        )
    )
    if not isinstance(chain, dict) or not chain:
        raise OptionSnapshotError("Alpaca returned no option snapshots")

    records: list[dict[str, str]] = []
    for contract_symbol, snapshot in sorted(chain.items()):
        quote = _field(snapshot, "latest_quote")
        greeks = _field(snapshot, "greeks")
        if quote is None or greeks is None:
            continue
        try:
            option_timestamp = _timestamp(_field(quote, "timestamp"), "option_quote_timestamp")
            if not 0 <= (reference_time - option_timestamp).total_seconds() <= max_age_seconds:
                continue
            record = {
                "underlying": symbol,
                "underlying_quote_timestamp": underlying_timestamp.isoformat(),
                "underlying_bid": str(underlying_bid),
                "underlying_ask": str(underlying_ask),
                "feed": "indicative",
                "symbol": str(contract_symbol),
                "option_quote_timestamp": option_timestamp.isoformat(),
                "bid": str(_field(quote, "bid_price")),
                "ask": str(_field(quote, "ask_price")),
                "bid_size": _capture_size(_field(quote, "bid_size"), "bid_size"),
                "ask_size": _capture_size(_field(quote, "ask_size"), "ask_size"),
                "implied_volatility": str(_field(snapshot, "implied_volatility")),
                "delta": str(_field(greeks, "delta")),
                "gamma": str(_field(greeks, "gamma")),
                "theta": str(_field(greeks, "theta")),
                "vega": str(_field(greeks, "vega")),
            }
            parsed = _row(record)
            if parsed.expiration != expiration_date.isoformat():
                continue
        except OptionSnapshotError:
            continue
        records.append(record)
    if not records:
        raise OptionSnapshotError("Alpaca returned no fresh complete option snapshots")

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=SNAPSHOT_COLUMNS)
            writer.writeheader()
            writer.writerows(records)
        rows = load_option_snapshot(destination)
        summary = summarize_option_snapshot(rows)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return OptionSnapshotCaptureReport(
        underlying=symbol,
        source="alpaca_trading_api",
        stock_feed="IEX",
        option_feed="indicative",
        expiration=expiration_date.isoformat(),
        strike_window_pct=strike_window_pct,
        max_age_seconds=max_age_seconds,
        output_path=destination.as_posix(),
        sha256=file_sha256(destination),
        summary=summary,
        order_sent=False,
    )
