"""
io_utils.py — Safe filesystem write operations with retry, fallback, and event emission.

For mounted filesystems (e.g. NFS, Docker mounts on macOS), Python's Path.write_text()
can silently fail or behave unexpectedly. This module provides two write helpers:

  safe_write(path, str)            — string content, verify-read, shell-redirect fallback
  write_json_atomic(path, dict)    — dict → JSON, mkstemp+rename with PermissionError retry

Both are safe on Windows FUSE mounts where os.replace() can raise PermissionError briefly
and where Path.write_text() may silently swallow writes.

Events emitted by safe_write:
  - fs_write_fallback  When the primary write fails but the shell fallback succeeds
  - fs_write_failed    When all write attempts fail (both primary and fallback)

Event payload: {"path": str(path), "attempt": int, "errno": int|None}
"""
from __future__ import annotations

import contextlib
import errno
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Avoid circular import: only import paths at call time if needed for event emission
logger = logging.getLogger("io_utils")


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """
    Atomically write *data* as JSON to *path* using mkstemp + rename.

    Uses a temporary file in the same directory as *path* so the rename is
    guaranteed to be on the same filesystem.  On Windows FUSE mounts,
    os.replace() can raise PermissionError briefly when the file is touched
    by the indexer; this function retries up to five times with increasing
    backoff (0 ms, 50 ms, 150 ms, 350 ms, 750 ms) before raising.

    Args:
        path: destination path (created with parents if needed)
        data: any JSON-serialisable dict

    Raises:
        PermissionError: if os.replace() fails on all five attempts
        OSError: if the temporary file cannot be created or written
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{path.stem}.",
        suffix=f"{path.suffix}.tmp",
        dir=str(path.parent),
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())

        last_error: Optional[Exception] = None
        for delay in (0.0, 0.05, 0.15, 0.35, 0.75):
            if delay:
                time.sleep(delay)
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def read_json(path: Path) -> Dict[str, Any]:
    """Read and parse a JSON file. The read counterpart to ``write_json_atomic``.

    Pure helper (stdlib only): opens *path* as UTF-8 and returns the parsed dict.
    Extracted from ``orchestrator.py`` in Stage 2a so JSON read and write live in
    one place.  ``orchestrator`` re-exports it as ``_read_json`` for its callers.
    """
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def safe_write(path: Path, data: str, *, event_emit: bool = True) -> None:
    """
    Atomically write *data* to *path* with retries and shell-redirect fallback.

    Order of attempts:
      1. Path.write_text() — fast path (3 attempts with backoff: 0.1s, 0.5s, 2.0s)
      2. Shell redirect via subprocess — fallback for mounted filesystems
      3. Raise OSError if all attempts fail

    Every fallback or failure emits an event to journal/events.log (if event_emit=True).

    Args:
        path: pathlib.Path object to write to
        data: string content to write
        event_emit: if True, emit fs_write_fallback / fs_write_failed events

    Raises:
        OSError: if all write attempts fail
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # ── Attempt 1: Python write with retries ──────────────────────────────────────
    backoff_delays = [0.1, 0.5, 2.0]
    last_exc: Optional[Exception] = None

    for attempt, delay in enumerate(backoff_delays, start=1):
        try:
            path.write_text(data, encoding="utf-8")
            # Verify the write actually landed (mounted FS may silently swallow it)
            if path.exists() and path.read_text(encoding="utf-8").strip() == data.strip():
                return  # Success — no event needed
        except Exception as exc:
            last_exc = exc
            if attempt < len(backoff_delays):
                time.sleep(delay)

    # ── Attempt 2: Shell redirect fallback ─────────────────────────────────────────
    try:
        escaped = data.replace("'", "'\\''")
        result = subprocess.run(
            ["bash", "-c", f"mkdir -p '{path.parent}' && printf '%s' '{escaped}' > '{path}'"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Verify the shell redirect actually worked
            if path.exists() and path.read_text(encoding="utf-8").strip() == data.strip():
                if event_emit:
                    _emit_event("fs_write_fallback", str(path), 1, None)
                return  # Fallback succeeded
    except Exception as exc:
        last_exc = exc
        logger.warning("Shell fallback for %s failed: %s", path, exc)

    # ── All attempts failed ────────────────────────────────────────────────────────
    errno_val = getattr(last_exc, "errno", None) if isinstance(last_exc, OSError) else None
    if event_emit:
        _emit_event("fs_write_failed", str(path), 3, errno_val)

    raise OSError(
        errno.EIO, f"Failed to write {path} after retries and shell fallback: {last_exc}"
    )


def _emit_event(
    event_type: str, path: str, attempt: int, errno_val: Optional[int]
) -> None:
    """
    Emit a filesystem write event to journal/events.log.

    This is an internal helper. It appends a JSON line and silently ignores
    errors (e.g. if the journal is not writable).

    Args:
        event_type: "fs_write_fallback" or "fs_write_failed"
        path: the file path that failed to write
        attempt: the attempt number (1-3)
        errno_val: OS errno if available (may be None)
    """
    # Import here to avoid circular dependency
    from paths import EVENTS_LOG

    try:
        event_data = {"path": path, "attempt": attempt, "errno": errno_val}
        event_line = json.dumps(
            {
                "timestamp": _utc_now_iso(),
                "event_type": event_type,
                "payload": event_data,
            }
        )
        EVENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(EVENTS_LOG, "a", encoding="utf-8") as f:
            f.write(event_line + "\n")
    except Exception as exc:
        logger.warning("Failed to emit %s event for %s: %s", event_type, path, exc)


def _utc_now_iso() -> str:
    """Return the current UTC time in ISO 8601 format with Z suffix."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
