from datetime import UTC, datetime, timedelta
from decimal import Decimal

from options_alpha_agent.exits import ManagedPosition, evaluate_exit


def position(**overrides: object) -> ManagedPosition:
    values: dict[str, object] = {
        "symbol": "SPY260905C00780000",
        "strategy": "long_call",
        "quantity": 1,
        "entry_debit_usd": Decimal("500"),
        "current_value_usd": Decimal("500"),
        "max_loss_usd": Decimal("500"),
        "days_to_expiry": 7,
        "quote_fresh": True,
    }
    values.update(overrides)
    return ManagedPosition(**values)


def test_exit_policy_is_ai_independent_and_takes_profit() -> None:
    decision = evaluate_exit(position(current_value_usd=Decimal("800")))

    assert decision.action == "EXIT_REVIEW"
    assert decision.reasons == ("take_profit_threshold",)


def test_exit_policy_stops_loss() -> None:
    decision = evaluate_exit(position(current_value_usd=Decimal("100")))

    assert decision.action == "EXIT_REVIEW"
    assert decision.reasons == ("stop_loss_threshold",)


def test_stale_quote_near_expiry_requires_manual_review() -> None:
    decision = evaluate_exit(
        position(days_to_expiry=1, quote_fresh=False, current_value_usd=Decimal("450"))
    )

    assert decision.action == "MANUAL_REVIEW"
    assert decision.reasons == ("stale_quote_near_expiry",)


def test_intraday_exit_policy_flattens_before_session_close() -> None:
    decision = evaluate_exit(
        position(),
        now=datetime(2026, 8, 31, 19, 45, tzinfo=UTC),  # 15:45 New York.
    )

    assert decision.action == "EXIT_REVIEW"
    assert decision.reasons == ("session_close_flatten",)


def test_intraday_exit_policy_limits_holding_time() -> None:
    now = datetime(2026, 8, 31, 17, 0, tzinfo=UTC)
    decision = evaluate_exit(
        position(opened_at=now - timedelta(minutes=241)),
        now=now,
    )

    assert decision.action == "EXIT_REVIEW"
    assert decision.reasons == ("max_intraday_holding_time",)
