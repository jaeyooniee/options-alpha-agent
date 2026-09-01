from dataclasses import replace
from decimal import Decimal

from options_alpha_agent.config import Settings
from options_alpha_agent.models import PortfolioState, TradeProposal
from options_alpha_agent.risk import evaluate_trade


def settings() -> Settings:
    return Settings(
        alpaca_api_key=None,
        alpaca_secret_key=None,
        openai_api_key=None,
        alpaca_paper=True,
        trade_execution_enabled=False,
        starting_equity_usd=Decimal("100000"),
        max_risk_per_trade_pct=Decimal("0.02"),
        max_portfolio_risk_pct=Decimal("0.10"),
        max_daily_drawdown_pct=Decimal("0.04"),
        max_open_positions=5,
    )


def portfolio() -> PortfolioState:
    return PortfolioState(
        equity_usd=Decimal("100000"),
        start_of_day_equity_usd=Decimal("100000"),
        deployed_risk_usd=Decimal("1000"),
        open_positions=1,
    )


def proposal() -> TradeProposal:
    return TradeProposal(
        proposal_id="test",
        underlying="SPY",
        strategy="call_debit_spread",
        quantity=1,
        max_loss_usd=Decimal("1000"),
        net_debit_usd=Decimal("1000"),
        days_to_expiry=7,
        bid_ask_spread_pct=Decimal("0.05"),
        min_open_interest=1000,
        defined_risk=True,
        thesis="test",
    )


def test_valid_defined_risk_trade_passes() -> None:
    decision = evaluate_trade(proposal(), portfolio(), settings())

    assert decision.allowed is True
    assert decision.reasons == ()


def test_undefined_risk_and_excess_loss_are_blocked() -> None:
    risky = replace(
        proposal(),
        strategy="naked_short_call",
        defined_risk=False,
        max_loss_usd=Decimal("5000"),
    )

    decision = evaluate_trade(risky, portfolio(), settings())

    assert decision.allowed is False
    assert "undefined_risk_strategy" in decision.reasons
    assert "strategy_not_allowlisted" in decision.reasons
    assert "per_trade_risk_exceeded" in decision.reasons


def test_daily_drawdown_blocks_new_entries() -> None:
    losing_portfolio = replace(portfolio(), equity_usd=Decimal("95999"))

    decision = evaluate_trade(proposal(), losing_portfolio, settings())

    assert decision.allowed is False
    assert "daily_drawdown_limit_reached" in decision.reasons


def test_invalid_risk_numbers_fail_closed() -> None:
    invalid = replace(proposal(), max_loss_usd=Decimal("NaN"))

    decision = evaluate_trade(invalid, portfolio(), settings())

    assert decision.allowed is False
    assert decision.reasons == ("non_finite_risk_input",)


def test_loss_below_debit_is_blocked() -> None:
    invalid = replace(
        proposal(),
        max_loss_usd=Decimal("10"),
        net_debit_usd=Decimal("20"),
    )

    decision = evaluate_trade(invalid, portfolio(), settings())

    assert decision.allowed is False
    assert "max_loss_below_debit" in decision.reasons


def test_short_horizon_dte_above_ten_days_is_rejected() -> None:
    decision = evaluate_trade(replace(proposal(), days_to_expiry=11), portfolio(), settings())

    assert decision.allowed is False
    assert "dte_outside_policy" in decision.reasons
