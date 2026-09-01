import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from options_alpha_agent.ai import (
    AIDecision,
    AIDecisionEngine,
    AISchemaError,
    AuditLog,
    AuditLogError,
    EvidenceValidationError,
    sanitize_evidence,
)
from options_alpha_agent.config import Settings


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


def no_trade_json() -> str:
    return json.dumps(
        {
            "action": "NO_TRADE",
            "underlying": "SPY",
            "strategy": None,
            "confidence": 0.91,
            "thesis": "Synthetic evidence cannot support a trade.",
            "evidence": ["market data is unavailable"],
            "rejected_alternatives": ["all option structures"],
            "invalidation_conditions": [],
            "quantity": 0,
            "max_loss_usd": 0,
            "net_debit_usd": 0,
        }
    )


class FakeCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        )


class FakeClient:
    def __init__(self, content: str) -> None:
        self.completions = FakeCompletions(content)
        self.chat = SimpleNamespace(completions=self.completions)


def test_strict_no_trade_schema_accepts_exact_contract() -> None:
    decision = AIDecision.from_json(no_trade_json())

    assert decision.action == "NO_TRADE"
    assert decision.quantity == 0
    assert decision.max_loss_usd == 0


def test_schema_rejects_extra_keys() -> None:
    payload = json.loads(no_trade_json())
    payload["order_payload"] = {"symbol": "must-never-reach-broker"}

    with pytest.raises(AISchemaError, match="keys mismatch"):
        AIDecision.from_json(json.dumps(payload))


def test_sensitive_evidence_fields_are_rejected() -> None:
    with pytest.raises(EvidenceValidationError, match="sensitive evidence field"):
        sanitize_evidence({"underlying": "SPY", "api_key": "must-not-leak"})


def test_sensitive_evidence_text_is_rejected() -> None:
    with pytest.raises(EvidenceValidationError, match="credential-like"):
        sanitize_evidence({"underlying": "SPY", "note": "authorization=private-token-sentinel"})


def test_audit_log_refuses_credential_like_event_without_creating_a_file(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")

    with pytest.raises(AuditLogError, match="unsafe data"):
        audit.append({"api_key": "private-audit-token-sentinel"})

    assert not audit.path.exists()


def test_non_finite_numbers_are_rejected() -> None:
    payload = json.loads(no_trade_json())
    payload["confidence"] = float("nan")

    with pytest.raises(AISchemaError, match="finite"):
        AIDecision.from_json(json.dumps(payload))

    with pytest.raises(EvidenceValidationError, match="non-finite"):
        sanitize_evidence({"value": float("inf")})


def test_engine_validates_and_writes_hash_chained_audit(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    client = FakeClient(no_trade_json())
    engine = AIDecisionEngine(
        settings(),
        client=client,
        audit_log=audit,
        now=lambda: datetime(2026, 8, 29, tzinfo=UTC),
    )

    outcome = engine.decide({"underlying": "SPY", "market_data_available": False})
    event = json.loads(audit.path.read_text(encoding="utf-8").strip())

    assert outcome.provider_status == "ok"
    assert outcome.decision.action == "NO_TRADE"
    assert event["previous_event_sha256"] == "GENESIS"
    assert len(event["event_sha256"]) == 64
    assert audit.verify() == event["event_sha256"]
    assert event["order_sent"] is False
    assert client.completions.calls == 1


def test_invalid_model_output_fails_closed(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    engine = AIDecisionEngine(
        settings(),
        client=FakeClient("not-json"),
        audit_log=audit,
        now=lambda: datetime(2026, 8, 29, tzinfo=UTC),
    )

    outcome = engine.decide({"underlying": "SPY"})

    assert outcome.provider_status == "fail_closed"
    assert outcome.decision.action == "NO_TRADE"
    assert outcome.error_type == "AISchemaError"


def test_credential_like_model_text_fails_closed_without_being_persisted(tmp_path: Path) -> None:
    payload = json.loads(no_trade_json())
    payload["thesis"] = "api_key=private-model-output-sentinel"
    audit = AuditLog(tmp_path / "audit.jsonl")
    engine = AIDecisionEngine(
        settings(),
        client=FakeClient(json.dumps(payload)),
        audit_log=audit,
        now=lambda: datetime(2026, 8, 29, tzinfo=UTC),
    )

    outcome = engine.decide({"underlying": "SPY"})
    stored = audit.path.read_text(encoding="utf-8")

    assert outcome.provider_status == "fail_closed"
    assert outcome.error_type == "AISchemaError"
    assert "private-model-output-sentinel" not in stored
    assert "provider_failure:AISchemaError" in stored


def test_daily_call_limit_prevents_provider_call(tmp_path: Path) -> None:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.append(
        {
            "timestamp": now.isoformat(),
            "provider_called": True,
            "estimated_cost_usd": "0.001",
        }
    )
    limited = replace(settings(), ai_max_daily_calls=1)
    client = FakeClient(no_trade_json())
    engine = AIDecisionEngine(
        limited,
        client=client,
        audit_log=audit,
        now=lambda: now,
    )

    outcome = engine.decide({"underlying": "SPY"})

    assert outcome.provider_status == "fail_closed"
    assert outcome.error_type == "AIBudgetError"
    assert client.completions.calls == 0


def test_audit_chain_detects_middle_record_tampering(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.append({"timestamp": "2026-08-29T00:00:00+00:00", "provider_called": False})
    audit.append({"timestamp": "2026-08-29T00:01:00+00:00", "provider_called": False})
    records = [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]
    records[0]["provider_called"] = True
    audit.path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(AuditLogError, match="audit"):
        audit.verify()
