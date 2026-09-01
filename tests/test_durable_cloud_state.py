from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from options_alpha_agent.ai import AuditLogError
from options_alpha_agent.config import Settings
from options_alpha_agent.dashboard import dashboard_snapshot
from options_alpha_agent.durable_audit import GCSAuditLog
from options_alpha_agent.run_lock import GCSRunLock, RunLockError


class PreconditionFailed(RuntimeError):
    pass


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[str, int]] = {}
        self.fail_next_write = False

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name, None)

    def get_blob(self, name: str) -> FakeBlob | None:
        if name not in self.objects:
            return None
        return FakeBlob(self, name, self.objects[name][1])


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str, generation: int | None) -> None:
        self.bucket = bucket
        self.name = name
        self.generation = generation

    def download_as_text(self, *, encoding: str) -> str:
        assert encoding == "utf-8"
        return self.bucket.objects[self.name][0]

    def upload_from_string(
        self,
        payload: str,
        *,
        content_type: str,
        if_generation_match: int,
    ) -> None:
        assert content_type in {
            "application/json; charset=utf-8",
            "application/x-ndjson; charset=utf-8",
        }
        if self.bucket.fail_next_write:
            self.bucket.fail_next_write = False
            raise PreconditionFailed("forced generation conflict")
        current = self.bucket.objects.get(self.name)
        current_generation = current[1] if current else 0
        if if_generation_match != current_generation:
            raise PreconditionFailed("generation mismatch")
        self.bucket.objects[self.name] = (payload, current_generation + 1)

    def delete(self, *, if_generation_match: int) -> None:
        current = self.bucket.objects.get(self.name)
        if current is None or if_generation_match != current[1]:
            raise PreconditionFailed("generation mismatch")
        del self.bucket.objects[self.name]


class FakeStorageClient:
    def __init__(self) -> None:
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name: str) -> FakeBucket:
        return self.buckets.setdefault(name, FakeBucket())


def event(timestamp: str = "2026-08-31T12:00:00+00:00") -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "event_type": "shadow_risk_decision",
        "order_sent": False,
    }


def test_gcs_audit_log_appends_and_detects_tampering() -> None:
    client = FakeStorageClient()
    audit = GCSAuditLog("audit-bucket", "audit/events.jsonl", client=client)

    audit.append(event())
    audit.append(event("2026-08-31T12:05:00+00:00"))

    assert len(audit.events()) == 2
    assert audit.verify() != "GENESIS"
    assert audit.daily_usage(datetime(2026, 8, 31, tzinfo=UTC)) == (0, 0)

    bucket = client.bucket("audit-bucket")
    payload, generation = bucket.objects["audit/events.jsonl"]
    bucket.objects["audit/events.jsonl"] = (payload.replace("shadow", "forged", 1), generation)

    with pytest.raises(AuditLogError, match="hash mismatch"):
        audit.verify()


def test_gcs_audit_log_fails_closed_on_generation_conflict() -> None:
    client = FakeStorageClient()
    audit = GCSAuditLog("audit-bucket", "audit/events.jsonl", client=client)
    audit.append(event())
    client.bucket("audit-bucket").fail_next_write = True

    with pytest.raises(AuditLogError, match="generation precondition"):
        audit.append(event("2026-08-31T12:05:00+00:00"))


def test_gcs_audit_log_refuses_credential_like_event_before_writing() -> None:
    client = FakeStorageClient()
    audit = GCSAuditLog("audit-bucket", "audit/events.jsonl", client=client)

    with pytest.raises(AuditLogError, match="unsafe data"):
        audit.append({"api_key": "private-gcs-audit-token-sentinel"})

    assert client.bucket("audit-bucket").objects == {}


def test_dashboard_reads_gcs_audit_without_local_path() -> None:
    client = FakeStorageClient()
    audit = GCSAuditLog("audit-bucket", "audit/events.jsonl", client=client)
    audit.append(event())
    settings = Settings(
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
        durable_state_backend="gcs",
        gcs_state_bucket="audit-bucket",
    )

    snapshot = dashboard_snapshot(settings, audit_log=audit)

    assert snapshot["audit_chain"] == "ok"
    assert snapshot["audit_event_count"] == 1
    assert snapshot["latest_event"]["event_type"] == "shadow_risk_decision"


def test_gcs_run_lock_blocks_overlap_and_reclaims_only_expired_lock() -> None:
    client = FakeStorageClient()
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    first = GCSRunLock(
        "audit-bucket",
        "locks/worker.json",
        ttl_seconds=300,
        client=client,
        now=lambda: now,
    )
    second = GCSRunLock(
        "audit-bucket",
        "locks/worker.json",
        ttl_seconds=300,
        client=client,
        now=lambda: now,
    )

    with first, pytest.raises(RunLockError, match="distributed run lock"), second:
        pass

    bucket = client.bucket("audit-bucket")
    bucket.objects["locks/worker.json"] = (
        json.dumps(
            {
                "lock_token": "stale",
                "expires_at": "2026-08-31T11:55:00+00:00",
            }
        ),
        42,
    )
    with second:
        assert "locks/worker.json" in bucket.objects
    assert "locks/worker.json" not in bucket.objects
