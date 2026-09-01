import json
from decimal import Decimal
from pathlib import Path

from options_alpha_agent.ai import AuditLog
from options_alpha_agent.config import Settings
from options_alpha_agent.dashboard import DEMO_HTML, dashboard_response, dashboard_snapshot


def settings(audit_path: str) -> Settings:
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
        ai_audit_log_path=audit_path,
    )


def test_dashboard_snapshot_is_safe_and_reports_audit_health(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.append(
        {
            "timestamp": "2026-08-29T00:00:00+00:00",
            "event_type": "ai_decision",
            "status": "ok",
            "order_sent": False,
        }
    )

    snapshot = dashboard_snapshot(settings(str(audit.path)), audit_log=audit)

    assert snapshot["paper_mode"] is True
    assert snapshot["execution_enabled"] is False
    assert snapshot["trading_kill_switch"] is True
    assert snapshot["order_sent"] is False
    assert snapshot["audit_chain"] == "ok"
    assert snapshot["audit_event_count"] == 1
    assert snapshot["latest_event"]["event_type"] == "ai_decision"
    assert "worker_lock_path" not in snapshot
    assert snapshot["latest_ai"] == {
        "timestamp": "2026-08-29T00:00:00+00:00",
        "provider_status": "ok",
        "provider_called": False,
        "error_type": None,
        "action": None,
        "strategy": None,
    }
    assert snapshot["shadow_performance"]["opened_cohorts"] == 0
    assert snapshot["shadow_performance"]["cohorts"] == []


def test_dashboard_snapshot_marks_missing_audit_as_not_initialized(tmp_path: Path) -> None:
    snapshot = dashboard_snapshot(settings(str(tmp_path / "missing.jsonl")))

    assert snapshot["audit_chain"] == "not_initialized"
    assert snapshot["audit_event_count"] == 0
    assert snapshot["latest_event"] is None
    assert snapshot["latest_ai"] is None
    assert snapshot["shadow_performance"]["opened_cohorts"] == 0


def test_dashboard_snapshot_allowlists_audit_fields_and_redacts_unexpected_data() -> None:
    class UnexpectedAudit:
        def verify(self) -> str:
            return "test-tail"

        def events(self) -> list[dict[str, object]]:
            return [
                {
                    "timestamp": "2026-08-29T00:00:00+00:00",
                    "event_type": "account_reconciliation",
                    "api_key": "private-api-key-sentinel",
                    "account_id": "private-account-id-sentinel",
                    "snapshot": {
                        "timestamp": "2026-08-29T00:00:00+00:00",
                        "equity_usd": "100000",
                        "day_pnl_usd": "0",
                        "position_count": 0,
                        "open_order_count": 0,
                        "market_open": False,
                        "account_id": "private-snapshot-account-sentinel",
                    },
                },
                {
                    "timestamp": "2026-08-29T00:01:00+00:00",
                    "event_type": "shadow_risk_decision",
                    "evidence": {
                        "underlying": "SPY",
                        "source": "alpaca",
                        "market_open": False,
                        "data_fresh": False,
                        "raw_option_symbol": "private-option-symbol-sentinel",
                        "signal": {"regime": "neutral"},
                    },
                    "decision": {"action": "NO_TRADE", "strategy": None},
                    "risk_decision": {"allowed": False, "reasons": ["market_closed"]},
                    "evaluation": {"status": "risk_denied"},
                },
            ]

    snapshot = dashboard_snapshot(settings("unused.jsonl"), audit_log=UnexpectedAudit())
    serialized = json.dumps(snapshot, sort_keys=True)

    assert snapshot["latest_account"]["equity_usd"] == "100000"
    assert snapshot["latest_cycle"]["underlying"] == "SPY"
    assert "private-api-key-sentinel" not in serialized
    assert "private-account-id-sentinel" not in serialized
    assert "private-snapshot-account-sentinel" not in serialized
    assert "private-option-symbol-sentinel" not in serialized


def test_public_demo_page_is_safe_and_explains_the_control_boundary() -> None:
    assert "AI proposes." in DEMO_HTML
    assert "Deterministic gates decide." in DEMO_HTML
    assert "No live endpoint" in DEMO_HTML
    assert "account ID" in DEMO_HTML
    assert "ALPACA_API_KEY" not in DEMO_HTML
    assert "FEATHERLESS_API_KEY" not in DEMO_HTML
    assert "<script" not in DEMO_HTML


def test_dashboard_http_routes_are_read_only_and_lazy_for_static_pages() -> None:
    calls = 0

    def snapshot() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"paper_mode": True, "order_sent": False, "audit_chain": "ok"}

    status, content_type, body = dashboard_response("/demo", snapshot)

    assert status.value == 200
    assert content_type == "text/html; charset=utf-8"
    assert b"AI proposes." in body
    assert calls == 0

    status, content_type, body = dashboard_response("/api/healthz", snapshot)

    assert status.value == 200
    assert content_type == "application/json"
    assert body == b'{"audit_chain": "ok", "order_sent": false, "paper_mode": true}'
    assert calls == 1

    status, content_type, body = dashboard_response("/unknown", snapshot)

    assert status.value == 404
    assert content_type == "text/plain; charset=utf-8"
    assert body == b"Not found"
    assert calls == 1
