"""Domain models shared by strategy, risk, and execution layers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TradeProposal:
    proposal_id: str
    underlying: str
    strategy: str
    quantity: int
    max_loss_usd: Decimal
    net_debit_usd: Decimal
    days_to_expiry: int
    bid_ask_spread_pct: Decimal
    min_open_interest: int
    defined_risk: bool
    thesis: str


@dataclass(frozen=True, slots=True)
class PortfolioState:
    equity_usd: Decimal
    start_of_day_equity_usd: Decimal
    deployed_risk_usd: Decimal
    open_positions: int

    @property
    def daily_pnl_usd(self) -> Decimal:
        return self.equity_usd - self.start_of_day_equity_usd


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reasons: tuple[str, ...]
