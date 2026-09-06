from datetime import timedelta

import pytest

from app.core import locks
from app.core.exceptions import LockUnavailable


def test_acquire_then_release_allows_reacquire(db):
    locks.acquire(db, lock_name="discovery", owner="run-1")
    locks.release(db, lock_name="discovery", owner="run-1")
    locks.acquire(db, lock_name="discovery", owner="run-2")


def test_concurrent_run_is_blocked(db):
    locks.acquire(db, lock_name="discovery", owner="run-1")

    with pytest.raises(LockUnavailable):
        locks.acquire(db, lock_name="discovery", owner="run-2")


def test_expired_lock_can_be_taken_over(db):
    """Um worker que morreu no meio não pode travar o workflow para sempre."""
    locks.acquire(db, lock_name="discovery", owner="run-morto", lease=timedelta(seconds=-1))

    locks.acquire(db, lock_name="discovery", owner="run-novo")


def test_context_manager_releases_even_on_error(db):
    with (
        pytest.raises(RuntimeError),
        locks.execution_lock(db, lock_name="discovery", owner="run-1"),
    ):
        raise RuntimeError("falha no meio do workflow")

    locks.acquire(db, lock_name="discovery", owner="run-2")
