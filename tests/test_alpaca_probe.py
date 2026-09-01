from decimal import Decimal
from types import SimpleNamespace

from options_alpha_agent.alpaca_probe import probe_account
from options_alpha_agent.config import Settings


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


class FakeClient:
    def get_account(self) -> SimpleNamespace:
        return SimpleNamespace(
            id="account-id-must-not-leak",
            status="ACTIVE",
            equity="100000",
            last_equity="100000",
            cash="100000",
            buying_power="400000",
            options_approved_level=3,
            options_trading_level=3,
            trading_blocked=False,
            account_blocked=False,
            created_at="2026-08-28T14:48:05Z",
        )

    def get_orders(self, request: object) -> list[object]:
        return []

    def get_all_positions(self) -> list[object]:
        return []


def test_probe_verifies_fresh_account_without_exposing_id() -> None:
    result = probe_account(settings(), FakeClient())
    public = result.public_dict()

    assert result.fresh_for_competition is True
    assert result.order_count == 0
    assert result.filled_order_count == 0
    assert result.position_count == 0
    assert result.account_ref.startswith("sha256:")
    assert "account-id-must-not-leak" not in str(public)
