"""infra.pidlock — single-instance lock (law L8).

Exactly one daemon per repo: a live lock refuses a second start; a stale lock (dead PID) is
reclaimed. Writes and deletes go through infra.atomic_io (law L7). There is no auto-restart, so a
stopped daemon stays stopped — a soft-stop cannot resurrect it (the v1 failure this avoids).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from infra.atomic_io import remove, write_json_atomic


class AlreadyRunning(RuntimeError):
    pass


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire(path: Path | str) -> None:
    path = Path(path)
    if path.exists():
        pid = -1
        try:
            pid = int(json.loads(path.read_text(encoding="utf-8")).get("pid", -1))
        except (OSError, ValueError, json.JSONDecodeError):
            pid = -1
        if _alive(pid):
            raise AlreadyRunning(f"daemon already running with pid {pid}")
        remove(path)  # stale lock from a dead process — reclaim it
    write_json_atomic(path, {"pid": os.getpid()})


def release(path: Path | str) -> None:
    remove(path)
