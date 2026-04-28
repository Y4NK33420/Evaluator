"""Unit tests for Firecracker runtime serial lock semantics."""

import threading
import time

import pytest

from app.services.code_eval.firecracker_runtime import _acquire_serial_lock, _release_serial_lock


def test_serial_lock_prevents_parallel_collision(tmp_path):
    lock_path = tmp_path / "firecracker.lock"
    waits: list[float] = []

    def hold_lock_for_a_moment():
        fd = _acquire_serial_lock(lock_path, timeout_seconds=2.0)
        try:
            time.sleep(0.35)
        finally:
            _release_serial_lock(fd, lock_path)

    def acquire_after_wait():
        started = time.monotonic()
        fd = _acquire_serial_lock(lock_path, timeout_seconds=2.0)
        try:
            waits.append(time.monotonic() - started)
        finally:
            _release_serial_lock(fd, lock_path)

    t1 = threading.Thread(target=hold_lock_for_a_moment)
    t2 = threading.Thread(target=acquire_after_wait)

    t1.start()
    time.sleep(0.05)
    t2.start()
    t1.join()
    t2.join()

    assert waits
    assert waits[0] >= 0.25
    assert not lock_path.exists()


def test_serial_lock_times_out_when_not_released(tmp_path):
    lock_path = tmp_path / "firecracker.lock"

    fd = _acquire_serial_lock(lock_path, timeout_seconds=1.0)
    try:
        with pytest.raises(TimeoutError):
            _acquire_serial_lock(lock_path, timeout_seconds=0.2)
    finally:
        _release_serial_lock(fd, lock_path)
