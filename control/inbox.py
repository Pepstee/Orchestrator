"""control.inbox — the intake channel: task files dropped here are ingested by the daemon.

Decouples writers (enqueue/intake — any number, while the daemon runs or not) from the daemon's
authoritative event log, so live enqueue is multi-writer-safe with no shared-log contention. Each
task is one file; the daemon folds it into its log and removes it on the next loop cycle.
"""
from __future__ import annotations

from pathlib import Path

from core.models import Task
from dispatch.repository import TaskRepository
from infra.atomic_io import read_json, remove, write_json_atomic


def default_inbox() -> Path:
    return Path(__file__).resolve().parents[1] / "state" / "inbox"


def drop(task: Task, inbox: Path | str | None = None) -> Path:
    """Write a task into the intake channel (one file per task)."""
    inbox_dir = Path(inbox) if inbox else default_inbox()
    inbox_dir.mkdir(parents=True, exist_ok=True)
    path = inbox_dir / f"{task.task_id}.json"
    write_json_atomic(path, task.to_dict())
    return path


def ingest(repo: TaskRepository, inbox: Path | str | None = None) -> int:
    """Fold all pending intake files into the repo and remove them. Returns the count ingested."""
    inbox_dir = Path(inbox) if inbox else default_inbox()
    if not inbox_dir.exists():
        return 0
    count = 0
    for f in sorted(inbox_dir.glob("*.json")):
        data = read_json(f)
        if isinstance(data, dict):
            repo.create(Task.from_dict(data))
            count += 1
        remove(f)
    return count
