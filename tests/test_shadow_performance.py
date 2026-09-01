from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from options_alpha_agent.shadow_performance import summarize_shadow_performance


def candidate(
    *,
    long_bid: str = "7.00",
    long_ask: str = "7.50",
    short_bid: str = "2.50",
    short_ask: str = "2.80",
) -> dict[str, object]:
    return {
        "strategy": "call_debit_spread",
        "contract_symbol": "SPY260905C00780000",
        "long_bid_per_share_usd": long_bid,
        "long_ask_per_share_usd": long_ask,
        "short_bid_per_share_usd": short_bid,
        "short_ask_per_share_usd": short_ask,
        "legs": [
            {"symbol": "SPY260905C00780000", "side": "buy", "ratio_qty": 1},
            {"symbol": "SPY260905C00800000", "side": "sell", "ratio_qty": 1},
        ],
    }


def event(
    when: datetime,
    *,
    proposal_id: str = "shadow-001",
    preview_ready: bool = True,
    fresh: bool = True,
    option_candidate: dict[str, object] | None = None,
) -> dict[str, object]:
    selected = option_candidate or candidate()
    return {
        "timestamp": when.astimezone(UTC).isoformat(),
        "event_type": "shadow_risk_decision",
        "order_sent": False,
        "evidence": {
            "underlying": "SPY",
            "source": "alpaca_paper_contracts+indicative_options",
            "data_fresh": fresh,
            "candidate_catalog": {"call_debit_spread": selected},
        },
        "decision": {
            "action": "PROPOSE_TRADE" if preview_ready else "NO_TRADE",
            "strategy": "call_debit_spread" if preview_ready else None,
        },
        "evaluation": {
            "status": "preview_ready" if preview_ready else "no_trade",
            "proposal": (
                {
                    "proposal_id": proposal_id,
                    "underlying": "SPY",
                    "strategy": "call_debit_spread",
                    "quantity": 1,
                    "net_debit_usd": "500.00",
                    "max_loss_usd": "500.00",
                }
                if preview_ready
                else None
            ),
        },
    }


def test_shadow_cohort_closes_at_conservative_exact_leg_mark() -> None:
    opened = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
    mark = event(
        opened + timedelta(hours=25),
        preview_ready=False,
        option_candidate=candidate(long_bid="9.00", short_ask="3.00"),
    )

    summary = summarize_shadow_performance([event(opened), mark], horizon_hours=24)

    assert summary.opened_cohorts == 1
    assert summary.closed_cohorts == 1
    assert summary.marked_cohorts == 1
    assert summary.realized_pnl_usd == Decimal("100.00")
    assert summary.closed_win_rate == 1
    assert summary.marked_return_on_max_loss == Decimal("0.20")
    assert summary.closed_cohort_max_drawdown_usd is None
    assert summary.closed_cohort_expected_shortfall_5pct_usd is None
    assert summary.risk_metrics_status == "insufficient_closed_sample"
    assert summary.order_sent is False
    assert summary.cohorts[0].latest_liquidation_value_usd == Decimal("600.00")


def test_shadow_mark_floors_crossed_liquidation_at_full_loss() -> None:
    opened = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
    mark = event(
        opened + timedelta(hours=25),
        preview_ready=False,
        option_candidate=candidate(long_bid="2.00", short_ask="3.00"),
    )

    summary = summarize_shadow_performance([event(opened), mark])

    assert summary.realized_pnl_usd == Decimal("-500.00")
    assert summary.cohorts[0].latest_liquidation_value_usd == 0


def test_shadow_metrics_report_drawdown_without_fabricating_expected_shortfall() -> None:
    opened = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
    second_opened = opened + timedelta(hours=26)
    summary = summarize_shadow_performance(
        [
            event(opened, proposal_id="shadow-001"),
            event(
                opened + timedelta(hours=25),
                preview_ready=False,
                option_candidate=candidate(long_bid="9.00", short_ask="3.00"),
            ),
            event(second_opened, proposal_id="shadow-002"),
            event(
                second_opened + timedelta(hours=25),
                proposal_id="shadow-002",
                preview_ready=False,
                option_candidate=candidate(long_bid="3.00", short_ask="2.00"),
            ),
        ]
    )

    assert summary.closed_cohort_sample_size == 2
    assert summary.total_marked_pnl_usd == Decimal("-300.00")
    assert summary.marked_return_on_max_loss == Decimal("-0.30")
    assert summary.closed_cohort_max_drawdown_usd == Decimal("400.00")
    assert summary.closed_cohort_expected_shortfall_5pct_usd is None


def test_shadow_expected_shortfall_requires_and_uses_twenty_closed_cohorts() -> None:
    opened = datetime(2026, 8, 1, 14, 0, tzinfo=UTC)
    events: list[dict[str, object]] = []
    for index in range(20):
        opened_at = opened + timedelta(hours=index * 26)
        events.append(event(opened_at, proposal_id=f"shadow-{index:03d}"))
        events.append(
            event(
                opened_at + timedelta(hours=25),
                proposal_id=f"shadow-{index:03d}",
                preview_ready=False,
                option_candidate=candidate(long_bid=str(index + 1), short_ask="0"),
            )
        )

    summary = summarize_shadow_performance(events)

    assert summary.closed_cohort_sample_size == 20
    assert summary.closed_cohort_expected_shortfall_5pct_usd == Decimal("-400.00")
    assert summary.risk_metrics_status == "available"


def test_stale_or_wrong_leg_events_do_not_create_a_mark() -> None:
    opened = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
    stale = event(opened + timedelta(hours=25), preview_ready=False, fresh=False)
    wrong = candidate()
    wrong["legs"] = [
        {"symbol": "SPY260905C00770000", "side": "buy", "ratio_qty": 1},
        {"symbol": "SPY260905C00790000", "side": "sell", "ratio_qty": 1},
    ]
    wrong_leg = event(
        opened + timedelta(hours=26),
        preview_ready=False,
        option_candidate=wrong,
    )

    summary = summarize_shadow_performance([event(opened), stale, wrong_leg])

    assert summary.opened_cohorts == 1
    assert summary.marked_cohorts == 0
    assert summary.unmarked_cohorts == 1
    assert summary.total_marked_pnl_usd == 0


def test_duplicate_proposal_ids_and_malformed_events_are_ignored() -> None:
    opened = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)

    summary = summarize_shadow_performance(
        [{"timestamp": "invalid"}, event(opened), event(opened, proposal_id="shadow-001")]
    )

    assert summary.opened_cohorts == 1


def test_synthetic_demo_events_are_excluded_from_performance() -> None:
    opened = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
    synthetic = event(opened)
    synthetic["evidence"]["source"] = "synthetic_shadow_fixture"

    summary = summarize_shadow_performance([synthetic])

    assert summary.opened_cohorts == 0


def test_shadow_horizon_is_bounded() -> None:
    with pytest.raises(ValueError, match="horizon_hours"):
        summarize_shadow_performance([], horizon_hours=0)
