from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from options_alpha_agent.config import Settings
from options_alpha_agent.option_snapshot import (
    OptionSnapshotError,
    capture_option_snapshot,
    load_option_snapshot,
    summarize_option_snapshot,
)

FIXTURE = Path("data/options/spy.indicative.2026-08-28T1948Z.csv")


def settings() -> Settings:
    return Settings(
        alpaca_api_key="key",
        alpaca_secret_key="secret",
        openai_api_key=None,
        alpaca_paper=True,
        trade_execution_enabled=False,
        starting_equity_usd=Decimal("100000"),
        max_risk_per_trade_pct=Decimal("0.02"),
        max_portfolio_risk_pct=Decimal("0.10"),
        max_daily_drawdown_pct=Decimal("0.04"),
        max_open_positions=5,
    )


class FakeStockClient:
    def __init__(self, timestamp: datetime) -> None:
        self.timestamp = timestamp

    def get_stock_latest_quote(self, request: object) -> dict[str, object]:
        assert request.symbol_or_symbols == "SPY"
        assert request.feed == "iex"
        return {
            "SPY": SimpleNamespace(
                timestamp=self.timestamp,
                bid_price="769.21",
                ask_price="769.23",
            )
        }


class FakeOptionClient:
    def __init__(self, timestamp: datetime) -> None:
        self.timestamp = timestamp

    def get_option_chain(self, request: object) -> dict[str, object]:
        assert request.underlying_symbol == "SPY"
        assert request.feed == "indicative"
        assert request.expiration_date.isoformat() == "2026-09-04"

        def snapshot(symbol: str, bid: str, ask: str, delta: str) -> object:
            return SimpleNamespace(
                latest_quote=SimpleNamespace(
                    symbol=symbol,
                    timestamp=self.timestamp,
                    bid_price=bid,
                    ask_price=ask,
                    bid_size=10.0,
                    ask_size=20.0,
                ),
                implied_volatility="0.10",
                greeks=SimpleNamespace(
                    delta=delta,
                    gamma="0.03",
                    theta="-0.20",
                    vega="0.40",
                ),
            )

        return {
            "SPY260904C00769000": snapshot("SPY260904C00769000", "4.67", "4.70", "0.52"),
            "SPY260904P00769000": snapshot("SPY260904P00769000", "3.88", "3.99", "-0.47"),
        }


def test_versioned_spy_snapshot_is_strict_and_internally_consistent() -> None:
    summary = summarize_option_snapshot(load_option_snapshot(FIXTURE))

    assert summary.underlying == "SPY"
    assert summary.feed == "indicative"
    assert summary.record_count == 22
    assert summary.call_count == 11
    assert summary.put_count == 11
    assert summary.expiration_dates == ("2026-09-04",)
    assert str(summary.strike_min) == "765"
    assert str(summary.strike_max) == "775"
    assert summary.duplicate_symbols == 0
    assert summary.order_sent is False


def test_snapshot_loader_rejects_naive_timestamps(tmp_path: Path) -> None:
    text = FIXTURE.read_text(encoding="utf-8").replace(
        "2026-08-28T19:47:36.877102+00:00",
        "2026-08-28T19:47:36.877102",
    )
    path = tmp_path / "naive.csv"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(OptionSnapshotError, match="timezone"):
        load_option_snapshot(path)


def test_snapshot_loader_rejects_crossed_quotes(tmp_path: Path) -> None:
    text = FIXTURE.read_text(encoding="utf-8").replace(
        ",7.07,7.38,60,117,",
        ",7.50,7.38,60,117,",
        1,
    )
    path = tmp_path / "crossed.csv"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(OptionSnapshotError, match="non-crossed"):
        load_option_snapshot(path)


def test_capture_option_snapshot_writes_immutable_validated_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = datetime(2026, 8, 28, 19, 50, tzinfo=UTC)
    quote_time = datetime(2026, 8, 28, 19, 49, tzinfo=UTC)
    monkeypatch.chdir(tmp_path)

    report = capture_option_snapshot(
        settings(),
        "SPY",
        "2026-09-04",
        "data/options/snapshot.csv",
        stock_client=FakeStockClient(quote_time),
        option_client=FakeOptionClient(quote_time),
        now=reference,
    )

    assert report.summary.record_count == 2
    assert report.summary.call_count == 1
    assert report.summary.put_count == 1
    assert report.summary.order_sent is False
    assert report.order_sent is False
    assert len(report.sha256) == 64
    assert (tmp_path / "data/options/snapshot.csv").is_file()

    with pytest.raises(OptionSnapshotError, match="already exists"):
        capture_option_snapshot(
            settings(),
            "SPY",
            "2026-09-04",
            "data/options/snapshot.csv",
            stock_client=FakeStockClient(quote_time),
            option_client=FakeOptionClient(quote_time),
            now=reference,
        )


@pytest.mark.parametrize("output_path", ["../outside.csv", "C:\\outside.csv"])
def test_capture_option_snapshot_rejects_unsafe_paths(output_path: str) -> None:
    with pytest.raises(OptionSnapshotError, match="workspace-relative"):
        capture_option_snapshot(
            settings(),
            "SPY",
            "2026-09-04",
            output_path,
            stock_client=FakeStockClient(datetime(2026, 8, 28, 19, 49, tzinfo=UTC)),
            option_client=FakeOptionClient(datetime(2026, 8, 28, 19, 49, tzinfo=UTC)),
            now=datetime(2026, 8, 28, 19, 50, tzinfo=UTC),
        )


def test_capture_option_snapshot_rejects_stale_underlying_quote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = datetime(2026, 8, 28, 19, 50, tzinfo=UTC)
    stale = datetime(2026, 8, 28, 19, 40, tzinfo=UTC)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(OptionSnapshotError, match="stale"):
        capture_option_snapshot(
            settings(),
            "SPY",
            "2026-09-04",
            "snapshot.csv",
            stock_client=FakeStockClient(stale),
            option_client=FakeOptionClient(stale),
            now=reference,
        )
