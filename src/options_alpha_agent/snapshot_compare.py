"""Conservative exact-symbol comparison for two real option snapshots.

This is quote-path evidence, not a strategy backtest. It uses entry asks/bids
and later liquidation bids/asks, but has no signal selection or open-interest
history and therefore cannot establish an edge.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from options_alpha_agent.option_snapshot import OptionSnapshotError, OptionSnapshotRow

CONTRACT_MULTIPLIER = Decimal("100")


@dataclass(frozen=True, slots=True)
class StructureMetrics:
    strategy: str
    observation_count: int
    positive_count: int
    win_rate: Decimal
    mean_pnl_usd: Decimal
    minimum_pnl_usd: Decimal
    maximum_pnl_usd: Decimal

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("win_rate", "mean_pnl_usd", "minimum_pnl_usd", "maximum_pnl_usd"):
            result[key] = str(result[key])
        return result


@dataclass(frozen=True, slots=True)
class SnapshotComparison:
    research_only: bool
    not_backtest: bool
    selection_edge_claimed: bool
    open_interest_available: bool
    underlying: str
    feed: str
    entry_timestamp: str
    exit_timestamp: str
    elapsed_seconds: Decimal
    entry_underlying_mid: Decimal
    exit_underlying_mid: Decimal
    underlying_return: Decimal
    matched_contracts: int
    unmatched_entry_contracts: int
    unmatched_exit_contracts: int
    structures: tuple[StructureMetrics, ...]
    order_sent: bool

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in (
            "elapsed_seconds",
            "entry_underlying_mid",
            "exit_underlying_mid",
            "underlying_return",
        ):
            result[key] = str(result[key])
        result["structures"] = [item.public_dict() for item in self.structures]
        return result


def _aggregate(strategy: str, pnl_values: list[Decimal]) -> StructureMetrics:
    if not pnl_values:
        raise OptionSnapshotError(f"no comparable observations for {strategy}")
    count = len(pnl_values)
    positive = sum(value > 0 for value in pnl_values)
    return StructureMetrics(
        strategy=strategy,
        observation_count=count,
        positive_count=positive,
        win_rate=Decimal(positive) / Decimal(count),
        mean_pnl_usd=sum(pnl_values, Decimal("0")) / Decimal(count),
        minimum_pnl_usd=min(pnl_values),
        maximum_pnl_usd=max(pnl_values),
    )


def _spread_pnl(
    entry: dict[str, OptionSnapshotRow],
    exit_rows: dict[str, OptionSnapshotRow],
    *,
    option_type: str,
) -> list[Decimal]:
    rows = sorted(
        (row for row in entry.values() if row.option_type == option_type),
        key=lambda row: (row.expiration, row.strike),
    )
    values: list[Decimal] = []
    for first_index, first in enumerate(rows):
        for second in rows[first_index + 1 :]:
            if first.expiration != second.expiration:
                continue
            if option_type == "call":
                long_entry, short_entry = first, second
            else:
                long_entry, short_entry = second, first
            long_exit = exit_rows[long_entry.symbol]
            short_exit = exit_rows[short_entry.symbol]
            width = abs(long_entry.strike - short_entry.strike)
            entry_debit = long_entry.ask - short_entry.bid
            if entry_debit <= 0 or entry_debit >= width:
                continue
            liquidation = max(Decimal("0"), long_exit.bid - short_exit.ask)
            values.append((liquidation - entry_debit) * CONTRACT_MULTIPLIER)
    return values


def compare_option_snapshots(
    entry_rows: list[OptionSnapshotRow],
    exit_rows: list[OptionSnapshotRow],
) -> SnapshotComparison:
    """Compare exact contracts with conservative executable quote sides."""

    if not entry_rows or not exit_rows:
        raise OptionSnapshotError("both option snapshots must contain records")
    entry_underlyings = {row.underlying for row in entry_rows}
    exit_underlyings = {row.underlying for row in exit_rows}
    entry_feeds = {row.feed for row in entry_rows}
    exit_feeds = {row.feed for row in exit_rows}
    if (
        len(entry_underlyings) != 1
        or entry_underlyings != exit_underlyings
        or len(entry_feeds) != 1
        or entry_feeds != exit_feeds
    ):
        raise OptionSnapshotError("snapshots must use the same underlying and feed")
    entry_quote = {
        (row.underlying_quote_timestamp, row.underlying_bid, row.underlying_ask)
        for row in entry_rows
    }
    exit_quote = {
        (row.underlying_quote_timestamp, row.underlying_bid, row.underlying_ask)
        for row in exit_rows
    }
    if len(entry_quote) != 1 or len(exit_quote) != 1:
        raise OptionSnapshotError("snapshot underlying quote metadata is inconsistent")
    entry_timestamp, entry_bid, entry_ask = next(iter(entry_quote))
    exit_timestamp, exit_bid, exit_ask = next(iter(exit_quote))
    if exit_timestamp <= entry_timestamp:
        raise OptionSnapshotError("exit snapshot must be later than entry snapshot")

    entry_by_symbol = {row.symbol: row for row in entry_rows}
    exit_by_symbol = {row.symbol: row for row in exit_rows}
    matched_symbols = sorted(set(entry_by_symbol) & set(exit_by_symbol))
    if not matched_symbols:
        raise OptionSnapshotError("snapshots have no exact-symbol overlap")
    matched_entry = {symbol: entry_by_symbol[symbol] for symbol in matched_symbols}
    matched_exit = {symbol: exit_by_symbol[symbol] for symbol in matched_symbols}

    long_call_pnl = [
        (matched_exit[symbol].bid - row.ask) * CONTRACT_MULTIPLIER
        for symbol, row in matched_entry.items()
        if row.option_type == "call"
    ]
    long_put_pnl = [
        (matched_exit[symbol].bid - row.ask) * CONTRACT_MULTIPLIER
        for symbol, row in matched_entry.items()
        if row.option_type == "put"
    ]
    call_spread_pnl = _spread_pnl(matched_entry, matched_exit, option_type="call")
    put_spread_pnl = _spread_pnl(matched_entry, matched_exit, option_type="put")
    entry_mid = (entry_bid + entry_ask) / Decimal("2")
    exit_mid = (exit_bid + exit_ask) / Decimal("2")
    return SnapshotComparison(
        research_only=True,
        not_backtest=True,
        selection_edge_claimed=False,
        open_interest_available=False,
        underlying=next(iter(entry_underlyings)),
        feed=next(iter(entry_feeds)),
        entry_timestamp=entry_timestamp.isoformat(),
        exit_timestamp=exit_timestamp.isoformat(),
        elapsed_seconds=Decimal(str((exit_timestamp - entry_timestamp).total_seconds())),
        entry_underlying_mid=entry_mid,
        exit_underlying_mid=exit_mid,
        underlying_return=exit_mid / entry_mid - Decimal("1"),
        matched_contracts=len(matched_symbols),
        unmatched_entry_contracts=len(entry_by_symbol) - len(matched_symbols),
        unmatched_exit_contracts=len(exit_by_symbol) - len(matched_symbols),
        structures=(
            _aggregate("long_call", long_call_pnl),
            _aggregate("long_put", long_put_pnl),
            _aggregate("call_debit_spread", call_spread_pnl),
            _aggregate("put_debit_spread", put_spread_pnl),
        ),
        order_sent=False,
    )
