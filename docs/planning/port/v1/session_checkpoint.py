"""
session_checkpoint.py — Lightweight session state persistence.

Writes a compact JSON snapshot of the orchestrator's current progress to
state/session_checkpoint.json every 30 minutes (triggered by the orchestrator
main loop).  On restart, the orchestrator reads this file and, if it is fresh
(< 24 h old), enqueues a warm-start manage task so the task_manager can
re-orient from the last known state rather than planning blind.

This solves the "blank slate" problem: after an overnight restart the queue
may be empty, the task_manager has no memory of what was recently accomplished,
and it may duplicate work or miss obvious next steps.

Public API
----------
write_checkpoint(root, *, done_tasks, queue_tasks, in_progress_tasks,
                 consecutive_failures, velocity_state, session_start)
    → Path   (the checkpoint file that was written)

read_checkpoint(root) → Optional[CheckpointData]

is_fresh(data, max_age_h) → bool
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Constants ─────────────────────────────────────────────────────────────────

CHECKPOINT_FILE  = "state/session_checkpoint.json"
MAX_DONE_IN_CHECKPOINT  = 25
MAX_QUEUE_IN_CHECKPOINT = 20


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class CheckpointData:
    timestamp:            str               # ISO-8601 UTC
    session_start:        str               # ISO-8601 UTC — when orchestrator booted
    elapsed_h:            float             # hours since session_start
    done_count_session:   int               # tasks completed this session
    recent_done:          List[Dict[str, str]]  # [{"title": ..., "task_type": ...}]
    queue_summary:        List[Dict[str, str]]  # [{"title": ..., "task_type": ...}]
    in_progress_summary:  List[Dict[str, str]]  # [{"title": ..., "task_type": ...}]
    consecutive_failures: int
    velocity_state:       str               # HEALTHY / WARNING / STALLED / etc.
    metadata:             Dict[str, Any]    = field(default_factory=dict)

    def age_h(self) -> float:
        """Hours since this checkpoint was written."""
        try:
            ts = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            return (now - ts).total_seconds() / 3600.0
        except Exception:
            return float("inf")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CheckpointData":
        return CheckpointData(
            timestamp            = str(d.get("timestamp", "")),
            session_start        = str(d.get("session_start", "")),
            elapsed_h            = float(d.get("elapsed_h", 0.0)),
            done_count_session   = int(d.get("done_count_session", 0)),
            recent_done          = list(d.get("recent_done", [])),
            queue_summary        = list(d.get("queue_summary", [])),
            in_progress_summary  = list(d.get("in_progress_summary", [])),
            consecutive_failures = int(d.get("consecutive_failures", 0)),
            velocity_state       = str(d.get("velocity_state", "UNKNOWN")),
            metadata             = dict(d.get("metadata", {})),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

# Sub-directories (relative to root) to probe when checking whether a task ID
# still exists on disk.  Done is first because that is the hot path.
_TASK_STATUS_SUBDIRS = (
    "tasks/done",
    "tasks/queue",
    "tasks/in_progress",
    "tasks/blocked",
    "tasks/failed",
)


def _task_done_exists(task_id: str, root: Path) -> bool:
    """Return True if *task_id* resolves to a JSON file under any tasks/ sub-dir.

    Checks ``tasks/done`` first (the common case for ``recent_done`` filtering),
    then the remaining status directories so that a re-queued or still-running
    task is not incorrectly discarded.  Returns ``False`` only when the ID is
    absent from every status directory — i.e. the task has been cleaned up.
    """
    if not task_id:
        return False
    for sub in _TASK_STATUS_SUBDIRS:
        if (root / sub / f"{task_id}.json").exists():
            return True
    return False


def _task_stub(task: Dict[str, Any]) -> Dict[str, str]:
    return {
        "task_id":   str(task.get("task_id") or ""),
        "title":     str(task.get("title") or "(untitled)")[:100],
        "task_type": str(task.get("task_type") or "unknown"),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Public API ────────────────────────────────────────────────────────────────

def write_checkpoint(
    root: Path,
    *,
    done_tasks:           List[Dict[str, Any]],
    queue_tasks:          List[Dict[str, Any]],
    in_progress_tasks:    List[Dict[str, Any]],
    consecutive_failures: int   = 0,
    velocity_state:       str   = "UNKNOWN",
    session_start:        str   = "",
    metadata:             Optional[Dict[str, Any]] = None,
) -> Path:
    """Write a checkpoint to state/session_checkpoint.json.

    Sorts done_tasks by updated_at descending and caps at MAX_DONE_IN_CHECKPOINT.
    Returns the path that was written.
    """
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    out_path = root / CHECKPOINT_FILE

    # Sort done by recency
    sorted_done = sorted(
        done_tasks,
        key=lambda t: t.get("updated_at") or "",
        reverse=True,
    )[:MAX_DONE_IN_CHECKPOINT]

    now = _utc_now()
    elapsed_h = 0.0
    if session_start:
        try:
            start_dt = datetime.fromisoformat(session_start.replace("Z", "+00:00"))
            elapsed_h = (datetime.now(timezone.utc) - start_dt).total_seconds() / 3600.0
        except Exception:
            pass

    data = CheckpointData(
        timestamp            = now,
        session_start        = session_start or now,
        elapsed_h            = round(elapsed_h, 2),
        done_count_session   = len(done_tasks),
        recent_done          = [_task_stub(t) for t in sorted_done],
        queue_summary        = [_task_stub(t) for t in queue_tasks[:MAX_QUEUE_IN_CHECKPOINT]],
        in_progress_summary  = [_task_stub(t) for t in in_progress_tasks],
        consecutive_failures = consecutive_failures,
        velocity_state       = velocity_state,
        metadata             = metadata or {},
    )

    # Atomic write: write to tmp then rename
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(out_path)
    return out_path


def read_checkpoint(root: Path) -> Optional[CheckpointData]:
    """Read state/session_checkpoint.json.  Returns None if absent or corrupt.

    After deserialising, ``recent_done`` is filtered to remove entries whose
    ``task_id`` no longer resolves to any file on disk.  This prevents the
    warm-start prompt from presenting phantom "completed" tasks to the
    task_manager when the tasks/ directory was cleaned between sessions.

    Entries that lack a ``task_id`` field (written by an older checkpoint
    version) are kept unconditionally so that a format upgrade does not
    silently discard all history.
    """
    path = root / CHECKPOINT_FILE
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        data = CheckpointData.from_dict(d)
        # Stale-ID filter: drop recent_done entries whose task_id is known but
        # no longer present anywhere on disk.
        data.recent_done = [
            stub for stub in data.recent_done
            if not stub.get("task_id")
            or _task_done_exists(stub["task_id"], root)
        ]
        return data
    except Exception:
        return None


def is_fresh(data: CheckpointData, max_age_h: float = 24.0) -> bool:
    """Return True if the checkpoint is younger than max_age_h hours."""
    return data.age_h() <= max_age_h


def format_warm_start_context(data: CheckpointData) -> str:
    """Produce a human-readable warm-start block for the task_manager prompt."""
    done_lines  = "\n".join(f"  - [{t['task_type']}] {t['title']}" for t in data.recent_done) or "  (none)"
    queue_lines = "\n".join(f"  - [{t['task_type']}] {t['title']}" for t in data.queue_summary) or "  (none)"
    ip_lines    = "\n".join(f"  - [{t['task_type']}] {t['title']}" for t in data.in_progress_summary) or "  (none)"
    return (
        f"## Previous Session Checkpoint (age: {data.age_h():.1f} h)\n\n"
        f"Session ran for {data.elapsed_h:.1f} h, completing {data.done_count_session} tasks.\n"
        f"Velocity state at checkpoint: **{data.velocity_state}**\n"
        f"Consecutive failures at checkpoint: {data.consecutive_failures}\n\n"
        f"### Recently completed\n{done_lines}\n\n"
        f"### Queue at checkpoint\n{queue_lines}\n\n"
        f"### In-progress at checkpoint\n{ip_lines}\n\n"
        "Use this to avoid duplicating recent work and to continue from where the "
        "previous session left off."
    )
