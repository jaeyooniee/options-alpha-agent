from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from options_alpha_agent.config import Settings
from options_alpha_agent.replay import ReplayObservation, replay_observations


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


def observation(
    timestamp: str,
    *,
    entry: str = "500",
    exit_value: str = "650",
    strategy: str = "call_debit_spread",
    max_loss: str | None = None,
) -> ReplayObservation:
    resolved_max_loss = entry if max_loss is None else max_loss
    return ReplayObservation(
        timestamp=datetime.fromisoformat(timestamp).replace(tzinfo=UTC),
        underlying="SPY",
        strategy=strategy,
        entry_debit_usd=Decimal(entry),
        exit_value_usd=Decimal(exit_value),
        max_loss_usd=Decimal(resolved_max_loss),
        days_to_expiry=7,
        bid_ask_spread_pct=Decimal("0.05"),
        min_open_interest=1000,
        defined_risk=True,
    )


def test_replay_is_sorted_and_computes_realized_pnl() -> None:
    summary = replay_observations(
        [
            observation("2026-08-29T10:05:00", entry="700", exit_value="500"),
            observation("2026-08-29T10:00:00"),
        ],
        settings(),
    )

    assert summary.total_observations == 2
    assert summary.accepted_trades == 2
    assert summary.net_pnl_usd == Decimal("-50")
    assert summary.results[0].timestamp.startswith("2026-08-29T10:00:00")


def test_replay_applies_safety_gate_before_pnl() -> None:
    summary = replay_observations(
        [observation("2026-08-29T10:00:00", max_loss="2500")],
        settings(),
    )

    assert summary.accepted_trades == 0
    assert summary.rejected_trades == 1
    assert summary.net_pnl_usd == Decimal("0")
    assert "per_trade_risk_exceeded" in summary.results[0].reasons


def test_replay_rejects_live_style_undefined_risk_observation() -> None:
    invalid = observation("2026-08-29T10:00:00")
    invalid = replace(invalid, defined_risk=False)

    summary = replay_observations([invalid], settings())

    assert summary.accepted_trades == 0
    assert "undefined_risk_strategy" in summary.results[0].reasons


def test_replay_applies_adverse_entry_and_exit_slippage() -> None:
    summary = replay_observations(
        [observation("2026-08-29T10:00:00")],
        settings(),
        entry_slippage_pct=Decimal("0.10"),
        exit_slippage_pct=Decimal("0.10"),
    )

    assert summary.accepted_trades == 1
    assert summary.net_pnl_usd == Decimal("35.00")
    assert summary.results[0].effective_entry_debit_usd == Decimal("550.00")
    assert summary.results[0].effective_exit_value_usd == Decimal("585.00")


def test_replay_rejects_stale_entry_or_exit_quote() -> None:
    stale = replace(observation("2026-08-29T10:00:00"), entry_quote_fresh=False)

    summary = replay_observations([stale], settings())

    assert summary.accepted_trades == 0
    assert "stale_entry_quote" in summary.results[0].reasons
