"""Read-only checks for Alpaca's free indicative options market data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from options_alpha_agent.config import Settings
from options_alpha_agent.market_evidence import (
    MAX_CLOCK_SKEW_SECONDS,
    _quote_datetime,
    alpaca_contract_rows,
    build_market_evidence,
)
from options_alpha_agent.signals import analyze_bars, analyze_intraday_bars


@dataclass(frozen=True, slots=True)
class OptionDataProbe:
    underlying: str
    feed: str
    contract_count: int
    sample_contract: str
    quote_timestamp: str
    bid_price: str
    ask_price: str
    bid_size: str
    ask_size: str
    spread_pct: str
    implied_volatility: str
    greeks_available: bool

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def _midpoint(bid: Decimal, ask: Decimal) -> Decimal:
    return (bid + ask) / Decimal("2")


def probe_option_data(
    settings: Settings,
    underlying: str = "SPY",
    *,
    as_of: date | None = None,
    stock_client: Any | None = None,
    option_client: Any | None = None,
) -> OptionDataProbe:
    """Verify indicative chain, quote, IV, and Greeks access without placing orders."""

    if not settings.has_alpaca_credentials:
        raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")

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

    if stock_client is None:
        stock_client = StockHistoricalDataClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
        )
    if option_client is None:
        option_client = OptionHistoricalDataClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
        )

    symbol = underlying.upper()
    quotes = stock_client.get_stock_latest_quote(
        StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
    )
    underlying_quote = quotes[symbol]
    underlying_bid = Decimal(str(underlying_quote.bid_price))
    underlying_ask = Decimal(str(underlying_quote.ask_price))
    underlying_mid = _midpoint(underlying_bid, underlying_ask)
    if underlying_mid <= 0:
        raise RuntimeError("Underlying quote has no positive midpoint")

    probe_date = as_of or datetime.now(UTC).date()
    chain = option_client.get_option_chain(
        OptionChainRequest(
            underlying_symbol=symbol,
            feed=OptionsFeed.INDICATIVE,
            strike_price_gte=float(underlying_mid * Decimal("0.97")),
            strike_price_lte=float(underlying_mid * Decimal("1.03")),
            expiration_date_gte=probe_date + timedelta(days=2),
            expiration_date_lte=probe_date + timedelta(days=10),
        )
    )
    if not chain:
        raise RuntimeError("Indicative option chain returned no contracts")

    candidates: list[tuple[Decimal, str, Any, Decimal, Decimal]] = []
    for contract_symbol, snapshot in chain.items():
        quote = getattr(snapshot, "latest_quote", None)
        greeks = getattr(snapshot, "greeks", None)
        implied_volatility = getattr(snapshot, "implied_volatility", None)
        if quote is None or greeks is None or implied_volatility is None:
            continue
        bid = Decimal(str(quote.bid_price))
        ask = Decimal(str(quote.ask_price))
        mid = _midpoint(bid, ask)
        if bid <= 0 or ask <= bid or mid <= 0:
            continue
        spread_pct = (ask - bid) / mid
        candidates.append((spread_pct, contract_symbol, snapshot, bid, ask))

    if not candidates:
        raise RuntimeError("No quoted option contract with IV and Greeks was returned")

    spread_pct, contract_symbol, snapshot, bid, ask = min(candidates, key=lambda row: row[0])
    quote = snapshot.latest_quote
    return OptionDataProbe(
        underlying=symbol,
        feed="indicative",
        contract_count=len(chain),
        sample_contract=contract_symbol,
        quote_timestamp=str(quote.timestamp),
        bid_price=str(bid),
        ask_price=str(ask),
        bid_size=str(quote.bid_size),
        ask_size=str(quote.ask_size),
        spread_pct=str(spread_pct.quantize(Decimal("0.0001"))),
        implied_volatility=str(snapshot.implied_volatility),
        greeks_available=True,
    )


def collect_market_evidence(
    settings: Settings,
    underlying: str = "SPY",
    *,
    now: datetime | None = None,
    max_age_seconds: int = 300,
    trading_client: Any | None = None,
    stock_client: Any | None = None,
    option_client: Any | None = None,
) -> dict[str, Any]:
    """Collect read-only Alpaca metadata and indicative quotes for the AI evidence pack."""

    if not settings.has_alpaca_credentials:
        raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
    if not settings.alpaca_paper:
        raise RuntimeError("paper mode is required")
    if max_age_seconds < 1:
        raise ValueError("max_age_seconds must be positive")

    if stock_client is None or option_client is None or trading_client is None:
        from alpaca.data.enums import DataFeed, OptionsFeed
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.data.requests import (
            OptionChainRequest,
            StockBarsRequest,
            StockLatestQuoteRequest,
        )
        from alpaca.data.timeframe import TimeFrame
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetOptionContractsRequest
    else:
        DataFeed = SimpleNamespace(IEX="iex")
        OptionsFeed = SimpleNamespace(INDICATIVE="indicative")
        OptionChainRequest = SimpleNamespace
        StockBarsRequest = SimpleNamespace
        StockLatestQuoteRequest = SimpleNamespace
        TimeFrame = SimpleNamespace(Day="day", Minute="minute")
        GetOptionContractsRequest = SimpleNamespace

    symbol = underlying.upper()
    reference_time = now or datetime.now(UTC)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=UTC)
    else:
        reference_time = reference_time.astimezone(UTC)
    valuation_date = reference_time.date()
    stock_client = stock_client or StockHistoricalDataClient(
        settings.alpaca_api_key,
        settings.alpaca_secret_key,
    )
    option_client = option_client or OptionHistoricalDataClient(
        settings.alpaca_api_key,
        settings.alpaca_secret_key,
    )
    trading_client = trading_client or TradingClient(
        settings.alpaca_api_key,
        settings.alpaca_secret_key,
        paper=True,
    )

    quotes = stock_client.get_stock_latest_quote(
        StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
    )
    underlying_quote = quotes[symbol]
    wall_clock = datetime.now(UTC)
    quote_received_at = (
        wall_clock if abs((wall_clock - reference_time).total_seconds()) <= 600 else reference_time
    )
    bid = Decimal(str(underlying_quote.bid_price))
    ask = Decimal(str(underlying_quote.ask_price))
    spot = _midpoint(bid, ask)
    if spot <= 0:
        raise RuntimeError("underlying quote has no positive midpoint")
    underlying_timestamp = _quote_datetime(underlying_quote.timestamp)
    underlying_fresh = bool(
        underlying_timestamp
        and quote_received_at.timestamp() - underlying_timestamp.timestamp() <= max_age_seconds
        and underlying_timestamp <= quote_received_at + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)
    )

    def _bar_rows(response: Any) -> list[Any]:
        bar_data = getattr(response, "data", None)
        if isinstance(bar_data, dict):
            return list(bar_data.get(symbol, []))
        if isinstance(response, dict):
            return list(response.get(symbol, []))
        return []

    try:
        daily_bars_response = stock_client.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=symbol,
                start=reference_time - timedelta(days=90),
                limit=60,
                timeframe=TimeFrame.Day,
                feed=DataFeed.IEX,
            )
        )
        signal_data = analyze_bars(
            _bar_rows(daily_bars_response), as_of=reference_time
        ).public_dict()
    except Exception as exc:  # noqa: BLE001 - unavailable signal means AI must abstain
        signal_data = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "lookahead_safe": True,
        }
    try:
        minute_bars_response = stock_client.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=symbol,
                start=reference_time - timedelta(minutes=90),
                limit=90,
                timeframe=TimeFrame.Minute,
                feed=DataFeed.IEX,
            )
        )
        intraday_signal_data = analyze_intraday_bars(
            _bar_rows(minute_bars_response), as_of=reference_time, minimum_bars=21
        ).public_dict()
    except Exception as exc:  # noqa: BLE001 - no minute confirmation means no new entry
        intraday_signal_data = {
            "status": "unavailable",
            "entry_allowed": False,
            "error_type": type(exc).__name__,
            "lookahead_safe": True,
        }

    contract_request_kwargs = {
        "underlying_symbols": [symbol],
        "expiration_date_gte": valuation_date + timedelta(days=2),
        "expiration_date_lte": valuation_date + timedelta(days=10),
        "strike_price_gte": str((spot * Decimal("0.95")).quantize(Decimal("0.01"))),
        "strike_price_lte": str((spot * Decimal("1.05")).quantize(Decimal("0.01"))),
        "limit": 10_000,
    }
    contracts: list[Any] = []
    page_token: str | None = None
    for _ in range(5):
        if page_token:
            contract_request_kwargs["page_token"] = page_token
        contract_response = trading_client.get_option_contracts(
            GetOptionContractsRequest(**contract_request_kwargs)
        )
        page_contracts = getattr(contract_response, "option_contracts", None)
        response_page_token = getattr(contract_response, "next_page_token", None)
        if isinstance(contract_response, dict):
            page_contracts = contract_response.get("option_contracts", [])
            response_page_token = contract_response.get("next_page_token")
        contracts.extend(list(page_contracts or []))
        page_token = response_page_token or None
        if not page_token:
            break
    if page_token:
        raise RuntimeError("option contract pagination exceeded the safety limit")
    snapshots = option_client.get_option_chain(
        OptionChainRequest(
            underlying_symbol=symbol,
            feed=OptionsFeed.INDICATIVE,
            strike_price_gte=float(spot * Decimal("0.95")),
            strike_price_lte=float(spot * Decimal("1.05")),
            expiration_date_gte=valuation_date + timedelta(days=2),
            expiration_date_lte=valuation_date + timedelta(days=10),
        )
    )
    option_observed_at = datetime.now(UTC)
    option_observation_time = (
        option_observed_at
        if abs((option_observed_at - reference_time).total_seconds()) <= 600
        else reference_time
    )
    rows = alpaca_contract_rows(
        contracts,
        snapshots,
        now=option_observation_time,
        max_age_seconds=max_age_seconds,
    )
    evidence = build_market_evidence(
        symbol,
        spot,
        rows,
        as_of=valuation_date,
        source="alpaca_paper_contracts+indicative_options",
        data_fresh=underlying_fresh and bool(rows),
        signal=signal_data,
        intraday_signal=intraday_signal_data,
    )
    evidence["underlying_quote"] = {
        "bid": str(bid),
        "ask": str(ask),
        "timestamp": underlying_timestamp.isoformat() if underlying_timestamp else None,
    }
    evidence["contract_count"] = len(contracts)
    evidence["fresh_row_count"] = len(rows)
    return evidence
