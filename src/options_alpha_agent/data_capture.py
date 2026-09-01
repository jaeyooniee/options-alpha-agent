"""Read-only underlying-bar capture with a reproducible file checksum."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from options_alpha_agent.config import Settings
from options_alpha_agent.provenance import file_sha256, is_unsafe_workspace_path
from options_alpha_agent.signals import SignalError, normalize_bars


class DataCaptureError(ValueError):
    """Raised when a safe research-data capture cannot be completed."""


@dataclass(frozen=True, slots=True)
class DataCaptureReport:
    underlying: str
    source: str
    feed: str
    timeframe: str
    requested_days: int
    requested_limit: int
    row_count: int
    first_timestamp: str
    last_timestamp: str
    output_path: str
    sha256: str
    order_sent: bool

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def capture_underlying_bars(
    settings: Settings,
    underlying: str,
    output_path: str | Path,
    *,
    days: int = 90,
    limit: int = 60,
    client: Any | None = None,
    now: datetime | None = None,
) -> DataCaptureReport:
    """Capture IEX daily bars through Alpaca without any trading mutation."""

    if not settings.has_alpaca_credentials:
        raise DataCaptureError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
    if not settings.alpaca_paper:
        raise DataCaptureError("paper mode is required")
    if not 1 <= days <= 3_650:
        raise DataCaptureError("days must be between 1 and 3650")
    if not 1 <= limit <= 1_000:
        raise DataCaptureError("limit must be between 1 and 1000")

    symbol = underlying.strip().upper()
    if not symbol.isascii() or not symbol.isalnum() or not 1 <= len(symbol) <= 8:
        raise DataCaptureError("underlying must be a short uppercase symbol")

    destination = Path(output_path)
    if is_unsafe_workspace_path(output_path):
        raise DataCaptureError("output_path must be workspace-relative")

    if client is None:
        from alpaca.data.enums import DataFeed
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        client = StockHistoricalDataClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
        )
    else:
        DataFeed = SimpleNamespace(IEX="iex")
        StockBarsRequest = SimpleNamespace
        TimeFrame = SimpleNamespace(Day="day")

    reference_time = now or datetime.now(UTC)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=UTC)
    else:
        reference_time = reference_time.astimezone(UTC)
    response = client.get_stock_bars(
        StockBarsRequest(
            symbol_or_symbols=symbol,
            start=reference_time - timedelta(days=days),
            end=reference_time,
            limit=limit,
            timeframe=TimeFrame.Day,
            feed=DataFeed.IEX,
        )
    )
    raw_bars = getattr(response, "data", None)
    if isinstance(raw_bars, dict):
        raw_bars = raw_bars.get(symbol, [])
    elif isinstance(response, dict):
        raw_bars = response.get(symbol, [])
    else:
        raw_bars = []
    try:
        bars = normalize_bars(raw_bars)
    except SignalError as exc:
        raise DataCaptureError(str(exc)) from exc
    if not bars:
        raise DataCaptureError("Alpaca returned no usable bars")

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("timestamp", "close"))
            writer.writeheader()
            writer.writerows(
                {"timestamp": bar.timestamp.isoformat(), "close": str(bar.close)} for bar in bars
            )
    except OSError as exc:
        raise DataCaptureError("could not write captured bars") from exc

    return DataCaptureReport(
        underlying=symbol,
        source="alpaca_trading_api",
        feed="IEX",
        timeframe="1Day",
        requested_days=days,
        requested_limit=limit,
        row_count=len(bars),
        first_timestamp=bars[0].timestamp.isoformat(),
        last_timestamp=bars[-1].timestamp.isoformat(),
        output_path=destination.as_posix(),
        sha256=file_sha256(destination),
        order_sent=False,
    )
