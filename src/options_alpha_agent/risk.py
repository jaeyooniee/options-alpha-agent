"""Deterministic pre-trade risk gates that the AI layer cannot override."""

from __future__ import annotations

from decimal import Decimal

from options_alpha_agent.config import Settings
from options_alpha_agent.models import PortfolioState, RiskDecision, TradeProposal

ALLOWED_DEFINED_RISK_STRATEGIES = frozenset(
    {
        "long_call",
        "long_put",
        "call_debit_spread",
        "put_debit_spread",
    }
)


def evaluate_trade(
    proposal: TradeProposal,
    portfolio: PortfolioState,
    settings: Settings,
) -> RiskDecision:
    """Return all failed gates; an empty failure list means the trade is allowed."""

    numeric_inputs = (
        proposal.max_loss_usd,
        proposal.net_debit_usd,
        proposal.bid_ask_spread_pct,
        portfolio.equity_usd,
        portfolio.start_of_day_equity_usd,
        portfolio.deployed_risk_usd,
    )
    if any(not value.is_finite() for value in numeric_inputs):
        return RiskDecision(False, ("non_finite_risk_input",))

    failures: list[str] = []

    if not settings.alpaca_paper:
        failures.append("paper_mode_required")
    if not proposal.defined_risk:
        failures.append("undefined_risk_strategy")
    if proposal.strategy not in ALLOWED_DEFINED_RISK_STRATEGIES:
        failures.append("strategy_not_allowlisted")
    if proposal.quantity < 1:
        failures.append("quantity_must_be_positive")
    if proposal.max_loss_usd <= 0:
        failures.append("max_loss_must_be_positive")
    if proposal.net_debit_usd <= 0:
        failures.append("net_debit_must_be_positive")
    if proposal.max_loss_usd < proposal.net_debit_usd:
        failures.append("max_loss_below_debit")
    # The production agent is an intraday debit-spread system. Longer-dated
    # structures remain available to research tools, but cannot reach an order
    # preview in the short-horizon execution path.
    if not 2 <= proposal.days_to_expiry <= 10:
        failures.append("dte_outside_policy")
    if proposal.bid_ask_spread_pct > Decimal("0.15"):
        failures.append("spread_too_wide")
    if proposal.min_open_interest < 100:
        failures.append("open_interest_too_low")

    max_trade_risk = portfolio.equity_usd * settings.max_risk_per_trade_pct
    if proposal.max_loss_usd > max_trade_risk:
        failures.append("per_trade_risk_exceeded")

    max_portfolio_risk = portfolio.equity_usd * settings.max_portfolio_risk_pct
    if portfolio.deployed_risk_usd + proposal.max_loss_usd > max_portfolio_risk:
        failures.append("portfolio_risk_exceeded")

    daily_loss_limit = portfolio.start_of_day_equity_usd * settings.max_daily_drawdown_pct
    if portfolio.daily_pnl_usd <= -daily_loss_limit:
        failures.append("daily_drawdown_limit_reached")

    if portfolio.open_positions >= settings.max_open_positions:
        failures.append("max_open_positions_reached")

    return RiskDecision(allowed=not failures, reasons=tuple(failures))
