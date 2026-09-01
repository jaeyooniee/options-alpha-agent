from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from options_alpha_agent.config import Settings
from options_alpha_agent.option_data import probe_option_data


def settings() -> Settings:
    return Settings(
        alpaca_api_key="paper-key",
        alpaca_secret_key="paper-secret",
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
    def get_stock_latest_quote(self, request: object) -> dict[str, SimpleNamespace]:
        return {"SPY": SimpleNamespace(bid_price=779, ask_price=781)}


class FakeOptionClient:
    def get_option_chain(self, request: object) -> dict[str, SimpleNamespace]:
        quote = SimpleNamespace(
            bid_price=4.50,
            ask_price=4.60,
            bid_size=20,
            ask_size=25,
            timestamp=datetime(2026, 8, 28, 15, 37, tzinfo=UTC),
        )
        return {
            "SPY260902C00772000": SimpleNamespace(
                latest_quote=quote,
                implied_volatility=0.0833,
                greeks=SimpleNamespace(delta=0.64),
            )
        }


def test_indicative_probe_requires_quote_iv_and_greeks() -> None:
    result = probe_option_data(
        settings(),
        as_of=date(2026, 8, 29),
        stock_client=FakeStockClient(),
        option_client=FakeOptionClient(),
    )

    assert result.feed == "indicative"
    assert result.contract_count == 1
    assert result.greeks_available is True
    assert result.spread_pct == "0.0220"
