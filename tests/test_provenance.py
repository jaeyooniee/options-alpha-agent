from pathlib import Path

import pytest

from options_alpha_agent.provenance import ProvenanceError, file_sha256


def test_file_sha256_is_stable_and_content_based(tmp_path: Path) -> None:
    path = tmp_path / "dataset.csv"
    path.write_bytes(b"timestamp,close\n")

    first = file_sha256(path)
    second = file_sha256(path)

    assert first == second
    assert len(first) == 64


def test_file_sha256_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ProvenanceError, match="does not exist"):
        file_sha256(tmp_path / "missing.csv")
