"""L8 — single-instance lock: live lock refuses a second start; stale lock is reclaimed."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from infra import pidlock
from infra.atomic_io import write_json_atomic


def test_live_lock_refuses_second_acquire(tmp_path: Path):
    lock = tmp_path / "d.pid"
    pidlock.acquire(lock)                      # this (live) process holds it
    with pytest.raises(pidlock.AlreadyRunning):
        pidlock.acquire(lock)
    pidlock.release(lock)


def test_stale_lock_is_reclaimed(tmp_path: Path):
    lock = tmp_path / "d.pid"
    write_json_atomic(lock, {"pid": 2_000_000_000})   # a PID that does not exist
    pidlock.acquire(lock)
    assert json.loads(lock.read_text())["pid"] == os.getpid()
    pidlock.release(lock)


def test_release_allows_reacquire(tmp_path: Path):
    lock = tmp_path / "d.pid"
    pidlock.acquire(lock)
    pidlock.release(lock)
    assert not lock.exists()
    pidlock.acquire(lock)                      # works again after release
    pidlock.release(lock)
