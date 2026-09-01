from datetime import UTC, datetime, timedelta
from decimal import Decimal

from options_alpha_agent.short_shadow import summarize_short_horizon_shadow


def candidate(
    long_bid: str = "7.00",
    short_ask: str = "2.80",
    *,
    quote_time: datetime | None = None,
) -> dict[str, object]:
    result = {
        "strategy": "call_debit_spread",
        "long_bid_per_share_usd": long_bid,
        "short_ask_per_share_usd": short_ask,
        "legs": [
            {"symbol": "SPY260905C00780000", "side": "buy", "ratio_qty": 1},
            {"symbol": "SPY260905C00800000", "side": "sell", "ratio_qty": 1},
        ],
    }
    if quote_time is not None:
        timestamp = quote_time.astimezone(UTC).isoformat()
        result["long_quote_timestamp"] = timestamp
        result["short_quote_timestamp"] = timestamp
    return result


def event(when: datetime, *, proposal_id: str = "shadow-001", preview: bool = True):
    return {
        "timestamp": when.astimezone(UTC).isoformat(),
        "event_type": "shadow_risk_decision",
        "order_sent": False,
        "evidence": {
            "source": "alpaca_paper_contracts+indicative_options",
            "data_fresh": True,
            "candidate_catalog": {
                "call_debit_spread": candidate("9.00" if not preview else "7.00", quote_time=when)
            },
        },
        "decision": {"action": "PROPOSE_TRADE" if preview else "NO_TRADE"},
        "evaluation": {
            "status": "preview_ready" if preview else "no_trade",
            "proposal": (
                {
                    "proposal_id": proposal_id,
                    "underlying": "SPY",
                    "strategy": "call_debit_spread",
                    "quantity": 1,
                    "net_debit_usd": "500.00",
                    "max_loss_usd": "500.00",
                }
                if preview
                else None
            ),
        },
    }


def test_short_horizon_uses_exact_leg_mark_and_is_research_only() -> None:
    opened = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)
    summary = summarize_short_horizon_shadow(
        [event(opened), event(opened + timedelta(minutes=16), preview=False)],
        horizons_minutes=(15,),
        minimum_cohorts=1,
    )

    metric = summary.horizons[0]
    assert metric.closed_cohorts == 1
    assert metric.mean_pnl_usd == Decimal("120.00")
    assert metric.mark_coverage == 1
    assert metric.sufficient_sample is True
    assert metric.positive_mean is True
    assert summary.recommended_action == "REVIEW_FOR_NEXT_GATE"
    assert summary.research_only is True
    assert summary.order_sent is False


def test_short_horizon_rejects_late_or_wrong_leg_marks() -> None:
    opened = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)
    late = event(opened + timedelta(minutes=18), preview=False)
    late["evidence"]["candidate_catalog"]["call_debit_spread"]["legs"][0]["symbol"] = (
        "SPY260905C00770000"
    )
    summary = summarize_short_horizon_shadow(
        [event(opened), late], horizons_minutes=(15,), minimum_cohorts=1
    )

    metric = summary.horizons[0]
    assert metric.closed_cohorts == 0
    assert metric.unmarked_cohorts == 1
    assert summary.recommended_action == "CONTINUE_SHADOW"


def test_synthetic_events_are_excluded() -> None:
    opened = event(datetime(2026, 8, 30, 14, 0, tzinfo=UTC))
    opened["evidence"]["source"] = "synthetic_shadow_fixture"
    summary = summarize_short_horizon_shadow([opened])

    assert summary.preview_openings == 0
    assert all(metric.opened_cohorts == 0 for metric in summary.horizons)
