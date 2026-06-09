"""
task_checkpoint.py — Per-task mid-run progress snapshots for crash recovery.

Agents write a checkpoint at each meaningful milestone (e.g. after analysing
files, after writing tests, after applying a patch).  If the agent subprocess
crashes or is killed, the orchestrator passes the last snapshot back to the
next retry invocation so the agent can resume from a known state rather than
starting over.

Checkpoints live at:
    state/task_checkpoints/{task_id}.json

Lifecycle
---------
1. Agent calls ``write_task_checkpoint()`` at key milestones.
2. Orchestrator reads the checkpoint in ``_write_agent_input()`` and injects
   it under ``payload["checkpoint"]``.
3. On the retry the agent receives the snapshot and can skip completed work.
4. ``clear_task_checkpoint()`` is called by the orchestrator on successful
   task completion so stale checkpoints never bleed into unrelated runs.

Public API
----------
write_task_checkpoint(root, task_id, *, step, progress, metadata) → Path
read_task_checkpoint(root, task_id) → Optional[TaskCheckpoint]
clear_task_checkpoint(root, task_id) → None
format_checkpoint_context(checkpoint) → str
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Constants ──────────────────────────────────────────────────────────────────

CHECKPOINT_DIR = Path("state") / "task_checkpoints"

# Checkpoints older than this are ignored (treat crash as cold start).
MAX_CHECKPOINT_AGE_H = 48.0


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class TaskCheckpoint:
    task_id:      str
    timestamp:    str                    # ISO-8601 UTC
    step:         str                    # human-readable milestone name
    step_number:  int                    # monotonically increasing counter
    progress:     Dict[str, Any]         = field(default_factory=dict)
    completed_steps: List[str]           = field(default_factory=list)
    metadata:     Dict[str, Any]         = field(default_factory=dict)

    # ── age ───────────────────────────────────────────────────────────────────

    def age_h(self) -> float:
        """Hours since this checkpoint was written."""
        try:
            ts = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
        except Exception:
            return float("inf")

    def is_fresh(self, max_age_h: float = MAX_CHECKPOINT_AGE_H) -> bool:
        return self.age_h() <= max_age_h

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TaskCheckpoint":
        return TaskCheckpoint(
            task_id         = str(d.get("task_id", "")),
            timestamp       = str(d.get("timestamp", "")),
            step            = str(d.get("step", "")),
            step_number     = int(d.get("step_number", 0)),
            progress        = dict(d.get("progress", {})),
            completed_steps = list(d.get("completed_steps", [])),
            metadata        = dict(d.get("metadata", {})),
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _checkpoint_path(root: Path, task_id: str) -> Path:
    return root / CHECKPOINT_DIR / f"{task_id}.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Public API ─────────────────────────────────────────────────────────────────

def write_task_checkpoint(
    root: Path,
    task_id: str,
    *,
    step: str,
    step_number: int = 0,
    progress: Optional[Dict[str, Any]] = None,
    completed_steps: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write a per-task progress snapshot.

    Safe to call from any agent subprocess.  Writes atomically (tmp → rename)
    so a crash mid-write never leaves a corrupt checkpoint.

    Args:
        root:            Repo root (Path).
        task_id:         The task being checkpointed.
        step:            Human-readable name of the current milestone.
        step_number:     Monotonically increasing counter (caller manages).
        progress:        Agent-specific key/value progress data.
        completed_steps: List of step names already finished.
        metadata:        Extra diagnostic data.

    Returns:
        Path to the written checkpoint file.
    """
    ckpt_dir = root / CHECKPOINT_DIR
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    data = TaskCheckpoint(
        task_id         = task_id,
        timestamp       = _utc_now(),
        step            = step,
        step_number     = step_number,
        progress        = progress or {},
        completed_steps = completed_steps or [],
        metadata        = metadata or {},
    )

    out_path = _checkpoint_path(root, task_id)
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(out_path)
    return out_path


def read_task_checkpoint(root: Path, task_id: str) -> Optional[TaskCheckpoint]:
    """Read the checkpoint for *task_id*.

    Returns None when:
    - the checkpoint file does not exist,
    - the file is empty or corrupt,
    - the checkpoint is older than MAX_CHECKPOINT_AGE_H.
    """
    path = _checkpoint_path(root, task_id)
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        ckpt = TaskCheckpoint.from_dict(d)
        if not ckpt.is_fresh():
            return None
        return ckpt
    except Exception:
        return None


def clear_task_checkpoint(root: Path, task_id: str) -> None:
    """Remove the checkpoint for *task_id* (best-effort; never raises)."""
    try:
        _checkpoint_path(root, task_id).unlink(missing_ok=True)
    except Exception:
        pass


def format_checkpoint_context(checkpoint: TaskCheckpoint) -> str:
    """Return a prompt-ready block describing the checkpoint state.

    Suitable for injection into an agent's prompt so it can resume from
    where the previous (crashed) attempt left off.
    """
    completed = (
        "\n".join(f"  - {s}" for s in checkpoint.completed_steps)
        if checkpoint.completed_steps
        else "  (none recorded)"
    )
    progress_lines = (
        "\n".join(f"  {k}: {v}" for k, v in checkpoint.progress.items())
        if checkpoint.progress
        else "  (none recorded)"
    )
    return (
        f"## Crash-recovery checkpoint (age: {checkpoint.age_h():.1f} h)\n\n"
        f"The previous attempt for task `{checkpoint.task_id}` saved a progress\n"
        f"snapshot at step **{checkpoint.step!r}** (step #{checkpoint.step_number}).\n"
        f"Resume from this point to avoid repeating completed work.\n\n"
        f"### Completed steps\n{completed}\n\n"
        f"### Progress snapshot\n{progress_lines}\n\n"
        "Skip any work already listed above. Continue from the current step.\n"
    )
