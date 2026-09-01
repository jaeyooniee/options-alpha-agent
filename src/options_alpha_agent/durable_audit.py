"""Optional GCS-backed immutable audit storage for Cloud Run workers.

The normal local JSONL log remains the default. This implementation is selected
only when ``DURABLE_STATE_BACKEND=gcs`` and deliberately fails closed if GCS,
Application Default Credentials, or a generation precondition is unavailable.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from options_alpha_agent.ai import (
    AuditLogError,
    EvidenceValidationError,
    _canonical_json,
    _sha256_text,
    sanitize_evidence,
)


def _verified_events(payload: str) -> tuple[list[dict[str, Any]], str]:
    """Parse and verify one full JSONL chain, returning events and its tail hash."""

    previous_hash = "GENESIS"
    events: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(payload.splitlines(), 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise AuditLogError(f"AI audit record is not an object at line {line_number}")
            record_for_hash = dict(record)
            stored_hash = record_for_hash.pop("event_sha256")
            if record_for_hash.get("previous_event_sha256") != previous_hash:
                raise AuditLogError(f"AI audit chain link mismatch at line {line_number}")
            if _sha256_text(_canonical_json(record_for_hash)) != stored_hash:
                raise AuditLogError(f"AI audit event hash mismatch at line {line_number}")
            previous_hash = stored_hash
            events.append(record)
    except AuditLogError:
        raise
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AuditLogError("AI audit chain is invalid; refusing access") from exc
    return events, previous_hash


class GCSAuditLog:
    """Hash-chained JSONL audit log guarded by GCS generation preconditions.

    Each append reads the current immutable generation, verifies the full chain,
    and writes only if that generation is still current. A concurrent append
    raises ``AuditLogError`` instead of risking a lost event.
    """

    def __init__(self, bucket_name: str, object_name: str, *, client: Any | None = None) -> None:
        self.bucket_name = bucket_name
        self.object_name = object_name
        self._client = client

    def _bucket(self) -> Any:
        if self._client is None:
            try:
                from google.cloud import storage

                self._client = storage.Client()
            except Exception as exc:  # noqa: BLE001 - absent ADC/library must block the cycle
                raise AuditLogError("GCS audit client is unavailable") from exc
        return self._client.bucket(self.bucket_name)

    def _read(self) -> tuple[str, int]:
        try:
            blob = self._bucket().get_blob(self.object_name)
            if blob is None:
                return "", 0
            generation = int(blob.generation)
            return blob.download_as_text(encoding="utf-8"), generation
        except AuditLogError:
            raise
        except Exception as exc:  # noqa: BLE001 - remote storage must fail closed
            raise AuditLogError("GCS audit log is unreadable; refusing access") from exc

    def _write(self, payload: str, generation: int) -> None:
        try:
            self._bucket().blob(self.object_name).upload_from_string(
                payload,
                content_type="application/x-ndjson; charset=utf-8",
                if_generation_match=generation,
            )
        except Exception as exc:  # noqa: BLE001 - concurrent/cloud write must never overwrite
            raise AuditLogError("GCS audit append failed generation precondition") from exc

    def daily_usage(self, now: datetime) -> tuple[int, Decimal]:
        events = self.events()
        calls = 0
        cost = Decimal("0")
        prefix = now.astimezone(UTC).date().isoformat()
        try:
            for event in events:
                if str(event.get("timestamp", "")).startswith(prefix) and event.get(
                    "provider_called"
                ):
                    calls += 1
                    cost += Decimal(str(event.get("estimated_cost_usd", "0")))
        except InvalidOperation as exc:
            raise AuditLogError("GCS audit usage data is invalid; refusing new calls") from exc
        return calls, cost

    def verify(self) -> str:
        _, tail_hash = _verified_events(self._read()[0])
        return tail_hash

    def append(self, event: Mapping[str, Any]) -> None:
        payload, generation = self._read()
        _, previous_hash = _verified_events(payload)
        try:
            record = sanitize_evidence(event)
        except EvidenceValidationError as exc:
            raise AuditLogError("GCS audit event contains unsafe data") from exc
        if not isinstance(record, dict):  # Defensive guard for alternative Mapping implementations.
            raise AuditLogError("GCS audit event must be an object")
        record["previous_event_sha256"] = previous_hash
        record["event_sha256"] = _sha256_text(_canonical_json(record))
        self._write(payload + _canonical_json(record) + "\n", generation)

    def events(self) -> list[dict[str, Any]]:
        events, _ = _verified_events(self._read()[0])
        return events
