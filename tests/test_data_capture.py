from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from options_alpha_agent.config import Settings
from options_alpha_agent.data_capture import DataCaptureError, capture_underlying_bars


def settings() -> Settings:
    return Settings(
        alpaca_api_key="key",
        alpaca_secret_key="secret",
        openai_api_key=None,
        alpaca_paper=True,
        trade_execution_enabled=False,
        starting_equity_usd=100000,
        max_risk_per_trade_pct=0.02,
        max_portfolio_risk_pct=0.10,
        max_daily_drawdown_pct=0.04,
        max_open_positions=5,
    )


class FakeBarsClient:
    def get_stock_bars(self, request: object) -> object:
        assert request.symbol_or_symbols == "SPY"
        return SimpleNamespace(
            data={
                "SPY": [
                    {"timestamp": "2026-08-02T04:00:00+00:00", "close": "101"},
                    {"timestamp": "2026-08-01T04:00:00+00:00", "close": "100"},
                ]
            }
        )


def test_capture_writes_normalized_csv_and_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    report = capture_underlying_bars(
        settings(),
        "SPY",
        "bars.csv",
        client=FakeBarsClient(),
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert report.row_count == 2
    assert report.first_timestamp.startswith("2026-08-01")
    assert len(report.sha256) == 64
    assert report.order_sent is False
    assert (tmp_path / "bars.csv").read_text(encoding="utf-8").splitlines() == [
        "timestamp,close",
        "2026-08-01T04:00:00+00:00,100",
        "2026-08-02T04:00:00+00:00,101",
    ]


@pytest.mark.parametrize("output_path", ["..\\outside.csv", "C:\\outside.csv"])
def test_capture_rejects_unsafe_output_path(output_path: str) -> None:
    with pytest.raises(DataCaptureError, match="workspace-relative"):
        capture_underlying_bars(settings(), "SPY", output_path, client=FakeBarsClient())
