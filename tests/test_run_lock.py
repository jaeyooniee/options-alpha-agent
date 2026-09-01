from pathlib import Path

import pytest

from options_alpha_agent.run_lock import RunLock, RunLockError


def test_run_lock_is_atomic_and_released_by_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / "worker.lock"

    with RunLock(lock_path):
        assert lock_path.is_file()
        with pytest.raises(RunLockError, match="already holds"), RunLock(lock_path):
            pass

    assert not lock_path.exists()


def test_run_lock_does_not_remove_a_replaced_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "worker.lock"

    with RunLock(lock_path):
        lock_path.write_text('{"lock_token":"another-owner"}', encoding="utf-8")

    assert lock_path.read_text(encoding="utf-8") == '{"lock_token":"another-owner"}'
