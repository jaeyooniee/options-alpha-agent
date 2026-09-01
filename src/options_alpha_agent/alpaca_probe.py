"""Read-only Alpaca connectivity and competition-account checks."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from options_alpha_agent.config import Settings


@dataclass(frozen=True, slots=True)
class AccountProbe:
    account_ref: str
    status: str
    equity_usd: str
    last_equity_usd: str
    cash_usd: str
    buying_power_usd: str
    options_approved_level: int | None
    options_trading_level: int | None
    order_count: int
    filled_order_count: int
    position_count: int
    trading_blocked: bool
    account_blocked: bool
    created_at: str
    paper_mode: bool
    competition_balance_matches: bool
    fresh_for_competition: bool

    def public_dict(self) -> dict[str, Any]:
        """Return diagnostics without exposing the Alpaca account ID."""

        return asdict(self)


def _plain_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _account_ref(account_id: Any) -> str:
    digest = hashlib.sha256(str(account_id).encode()).hexdigest()[:12]
    return f"sha256:{digest}"


def probe_account(settings: Settings, client: Any | None = None) -> AccountProbe:
    """Fetch account metadata only; this function cannot submit orders."""

    if not settings.has_alpaca_credentials:
        raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")

    if client is None:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        client = TradingClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper=True,
        )
        orders_request = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=500)
    else:
        orders_request = SimpleNamespace(status="all", limit=500)

    account = client.get_account()
    orders = client.get_orders(orders_request)
    positions = client.get_all_positions()
    equity = Decimal(str(account.equity))
    filled_order_count = sum(
        1 for order in orders if str(_plain_value(order.status)).lower() == "filled"
    )
    competition_balance_matches = equity == settings.starting_equity_usd
    fresh_for_competition = competition_balance_matches and not orders and not positions

    return AccountProbe(
        account_ref=_account_ref(account.id),
        status=str(_plain_value(account.status)),
        equity_usd=str(equity),
        last_equity_usd=str(account.last_equity),
        cash_usd=str(account.cash),
        buying_power_usd=str(account.buying_power),
        options_approved_level=_plain_value(getattr(account, "options_approved_level", None)),
        options_trading_level=_plain_value(getattr(account, "options_trading_level", None)),
        order_count=len(orders),
        filled_order_count=filled_order_count,
        position_count=len(positions),
        trading_blocked=bool(account.trading_blocked),
        account_blocked=bool(account.account_blocked),
        created_at=str(account.created_at),
        paper_mode=True,
        competition_balance_matches=competition_balance_matches,
        fresh_for_competition=fresh_for_competition,
    )
