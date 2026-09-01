"""Small helpers for reproducible, read-only research dataset provenance."""

from __future__ import annotations

import hashlib
import ntpath
from pathlib import Path


class ProvenanceError(ValueError):
    """Raised when a provenance source cannot be hashed safely."""


def is_unsafe_workspace_path(value: str | Path) -> bool:
    """Reject absolute or parent-traversal paths across Windows and POSIX hosts."""

    raw = str(value)
    normalized = raw.replace("\\", "/")
    candidate = Path(normalized)
    return candidate.is_absolute() or ntpath.isabs(raw) or ".." in candidate.parts


def file_sha256(path: str | Path) -> str:
    """Return a content hash without modifying or exposing the file contents."""

    source = Path(path)
    if not source.is_file():
        raise ProvenanceError("provenance file does not exist")
    digest = hashlib.sha256()
    try:
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ProvenanceError("provenance file could not be read") from exc
    return digest.hexdigest()
