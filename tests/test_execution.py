from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from options_alpha_agent.ai import AuditLog
from options_alpha_agent.config import Settings
from options_alpha_agent.execution import submit_paper_order
from options_alpha_agent.models import RiskDecision
from options_alpha_agent.shadow import ShadowEvaluation


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


def evaluation() -> ShadowEvaluation:
    return ShadowEvaluation(
        status="preview_ready",
        proposal=None,
        risk_decision=RiskDecision(True, ()),
        order_preview={
            "client_order_id": "shadow-execution-001",
            "order_class": "mleg",
            "type": "limit",
            "time_in_force": "day",
            "qty": 1,
            "limit_price": "7.50",
            "legs": [
                {"symbol": "SPY260905C00780000", "side": "buy", "ratio_qty": 1},
                {"symbol": "SPY260905C00800000", "side": "sell", "ratio_qty": 1},
            ],
            "paper": True,
            "sent": False,
        },
        error_type=None,
    )


def test_default_execution_gate_never_calls_client(tmp_path: Path) -> None:
    class ExplodingClient:
        def submit_order(self, request: object) -> None:
            raise AssertionError("broker must not be called while execution is disabled")

    result = submit_paper_order(
        settings(),
        evaluation(),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        client=ExplodingClient(),
    )

    assert result.status == "disabled"
    assert result.order_sent is False


def test_execution_requires_two_explicit_flags(tmp_path: Path) -> None:
    approved_but_disabled = replace(settings(), paper_order_approved=True)
    result = submit_paper_order(
        approved_but_disabled,
        evaluation(),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )

    assert result.status == "disabled"
    assert result.error_type == "execution_disabled"


def test_kill_switch_blocks_even_explicitly_approved_paper_execution(tmp_path: Path) -> None:
    approved = replace(
        settings(),
        trade_execution_enabled=True,
        paper_order_approved=True,
        trading_kill_switch=True,
    )
    result = submit_paper_order(
        approved,
        evaluation(),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )

    assert result.status == "blocked"
    assert result.error_type == "trading_kill_switch_enabled"
    assert result.order_sent is False


def test_non_paper_mode_blocks_even_when_every_execution_flag_is_enabled(tmp_path: Path) -> None:
    unsafe = replace(
        settings(),
        alpaca_paper=False,
        trade_execution_enabled=True,
        paper_order_approved=True,
        trading_kill_switch=False,
    )

    result = submit_paper_order(
        unsafe,
        evaluation(),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
    )

    assert result.status == "blocked"
    assert result.error_type == "paper_mode_required"
    assert result.order_sent is False


def test_risk_rejection_blocks_before_preview_or_broker_access(tmp_path: Path) -> None:
    class ExplodingClient:
        def submit_order(self, request: object) -> None:
            raise AssertionError("risk-rejected order must not reach broker")

    approved = replace(
        settings(),
        trade_execution_enabled=True,
        paper_order_approved=True,
        trading_kill_switch=False,
    )
    rejected = replace(
        evaluation(),
        risk_decision=RiskDecision(False, ("daily_drawdown_exceeded",)),
    )

    result = submit_paper_order(
        approved,
        rejected,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        client=ExplodingClient(),
    )

    assert result.status == "blocked"
    assert result.error_type == "risk_preview_required"
    assert result.order_sent is False


def test_invalid_preview_fails_before_broker_access(tmp_path: Path) -> None:
    class ExplodingClient:
        def submit_order(self, request: object) -> None:
            raise AssertionError("invalid preview must not reach broker")

    approved = replace(
        settings(),
        trade_execution_enabled=True,
        paper_order_approved=True,
        trading_kill_switch=False,
    )
    invalid = replace(evaluation(), order_preview={"paper": True})
    result = submit_paper_order(
        approved,
        invalid,
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        client=ExplodingClient(),
    )

    assert result.status == "failed"
    assert result.order_sent is False


def test_enabled_path_uses_fake_client_and_audits_sanitized_broker_reference(
    tmp_path: Path,
) -> None:
    class FakeResponse:
        id = "opaque-paper-broker-order-id"
        status = "accepted"

    class RecordingClient:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def submit_order(self, request: object) -> FakeResponse:
            self.requests.append(request)
            return FakeResponse()

    approved = replace(
        settings(),
        trade_execution_enabled=True,
        paper_order_approved=True,
        trading_kill_switch=False,
    )
    audit = AuditLog(tmp_path / "audit.jsonl")
    client = RecordingClient()

    result = submit_paper_order(approved, evaluation(), audit_log=audit, client=client)

    assert result.status == "submitted"
    assert result.order_sent is True
    assert result.broker_order_ref is not None
    assert result.broker_order_ref.startswith("sha256:")
    assert "opaque-paper-broker-order-id" not in result.broker_order_ref
    assert len(client.requests) == 1
    assert [event["event_type"] for event in audit.events()] == [
        "order_submit_intent",
        "order_submitted",
    ]


def test_duplicate_client_order_id_blocks_before_fake_client_is_called(tmp_path: Path) -> None:
    class ExplodingClient:
        def submit_order(self, request: object) -> None:
            raise AssertionError("duplicate client order must not reach broker")

    approved = replace(
        settings(),
        trade_execution_enabled=True,
        paper_order_approved=True,
        trading_kill_switch=False,
    )
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.append(
        {
            "event_type": "order_submitted",
            "client_order_id": "shadow-execution-001",
            "order_sent": True,
        }
    )

    result = submit_paper_order(approved, evaluation(), audit_log=audit, client=ExplodingClient())

    assert result.status == "duplicate"
    assert result.error_type == "client_order_id_already_submitted"
    assert result.order_sent is False
