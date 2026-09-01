"""Fail-closed local lock for one-shot worker invocations."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4


class RunLockError(RuntimeError):
    """Raised when another worker already owns the lock."""


class RunLock:
    """Acquire an atomic filesystem lock and release only the owning token."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._token: str | None = None

    def __enter__(self) -> RunLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = uuid4().hex
        payload = json.dumps(
            {
                "acquired_at": datetime.now(UTC).isoformat(),
                "lock_token": token,
            },
            sort_keys=True,
        )
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise RunLockError("another worker already holds the run lock") from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
        except Exception:
            with suppress(OSError):
                self.path.unlink()
            raise
        self._token = token
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._token is None:
            return
        try:
            record = json.loads(self.path.read_text(encoding="utf-8"))
            owns_lock = record.get("lock_token") == self._token
        except (OSError, ValueError, TypeError):
            owns_lock = False
        if owns_lock:
            with suppress(FileNotFoundError):
                self.path.unlink()
        self._token = None


class GCSRunLock:
    """Distributed GCS lock using create/delete generation preconditions.

    Stale locks can be reclaimed only after their explicit expiry. Any storage
    error is a lock failure, so a scheduled worker cannot run concurrently by
    accident when its durability dependency is unavailable.
    """

    def __init__(
        self,
        bucket_name: str,
        object_name: str,
        *,
        ttl_seconds: int,
        client: Any | None = None,
        now: Any | None = None,
    ) -> None:
        self.bucket_name = bucket_name
        self.object_name = object_name
        self.ttl_seconds = ttl_seconds
        self._client = client
        self._now = now or (lambda: datetime.now(UTC))
        self._token: str | None = None

    def _bucket(self) -> Any:
        if self._client is None:
            try:
                from google.cloud import storage

                self._client = storage.Client()
            except Exception as exc:  # noqa: BLE001 - absent ADC/library blocks the worker
                raise RunLockError("GCS run lock client is unavailable") from exc
        return self._client.bucket(self.bucket_name)

    def _payload(self, token: str) -> str:
        acquired_at = self._now().astimezone(UTC)
        return json.dumps(
            {
                "acquired_at": acquired_at.isoformat(),
                "expires_at": (acquired_at + timedelta(seconds=self.ttl_seconds)).isoformat(),
                "lock_token": token,
            },
            sort_keys=True,
        )

    def _try_create(self, token: str) -> bool:
        try:
            self._bucket().blob(self.object_name).upload_from_string(
                self._payload(token),
                content_type="application/json; charset=utf-8",
                if_generation_match=0,
            )
            return True
        except Exception:
            return False

    def _reclaim_if_expired(self) -> bool:
        try:
            blob = self._bucket().get_blob(self.object_name)
            if blob is None:
                return True
            record = json.loads(blob.download_as_text(encoding="utf-8"))
            expiry = datetime.fromisoformat(str(record["expires_at"])).astimezone(UTC)
            if expiry > self._now().astimezone(UTC):
                return False
            blob.delete(if_generation_match=int(blob.generation))
            return True
        except Exception:
            return False

    def __enter__(self) -> GCSRunLock:
        token = uuid4().hex
        if not self._try_create(token) and not (
            self._reclaim_if_expired() and self._try_create(token)
        ):
            raise RunLockError("another worker already holds the distributed run lock")
        self._token = token
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._token is None:
            return
        try:
            blob = self._bucket().get_blob(self.object_name)
            if blob is not None:
                record = json.loads(blob.download_as_text(encoding="utf-8"))
                if record.get("lock_token") == self._token:
                    blob.delete(if_generation_match=int(blob.generation))
        except Exception:
            # A failed release leaves a time-bounded lock rather than deleting another owner's lock.
            pass
        self._token = None


def run_lock_for_settings(settings: Any) -> RunLock | GCSRunLock:
    """Return a local or distributed lock according to the validated settings."""

    if settings.durable_state_backend == "gcs":
        if not settings.gcs_state_bucket:
            raise RunLockError("GCS run lock bucket is not configured")
        return GCSRunLock(
            settings.gcs_state_bucket,
            settings.gcs_lock_object,
            ttl_seconds=settings.gcs_lock_ttl_seconds,
        )
    return RunLock(settings.worker_lock_path)
