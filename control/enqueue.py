"""control.enqueue — put a task into the daemon's durable queue (the minimal intake).

This is the thin manual intake until the guided "build-your-idea" funnel lands (P1). It appends a
task to the same event log the daemon reads (state/tasks.events.log), so the daemon runs it on
(re)start. Build + independent judge is a two-task graph:

    python -m control.enqueue "Scaffold a hello-world Python CLI with a pytest test" --project demo
    # -> prints the build task id, e.g. enqueued a1b2c3d4e5f6
    python -m control.enqueue "Review the hello-world CLI" --type validate --project demo \\
        --depends-on a1b2c3d4e5f6 --accept "the CLI prints output" "a meaningful test exists"
    python -m control.daemon
"""
from __future__ import annotations

import argparse
import uuid
from pathlib import Path

from core.models import Task
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def _default_store() -> Path:
    return Path(__file__).resolve().parents[1] / "state" / "tasks.events.log"


def enqueue(
    title: str,
    *,
    task_type: str = "implement",
    project: str = "default",
    acceptance: list[str] | None = None,
    depends_on: list[str] | None = None,
    store_path: str | None = None,
) -> str:
    path = Path(store_path) if store_path else _default_store()
    path.parent.mkdir(parents=True, exist_ok=True)
    repo = TaskRepository.replay(EventStore(path))
    task_id = uuid.uuid4().hex[:12]
    repo.create(Task(
        task_id=task_id, title=title, task_type=task_type, project=project,
        acceptance_criteria=list(acceptance or []), depends_on=list(depends_on or []),
    ))
    return task_id


def main() -> None:
    p = argparse.ArgumentParser(description="Enqueue a task for the daemon.")
    p.add_argument("title")
    p.add_argument("--type", default="implement", dest="task_type")
    p.add_argument("--project", default="default")
    p.add_argument("--accept", nargs="*", default=[], dest="acceptance")
    p.add_argument("--depends-on", nargs="*", default=[], dest="depends_on")
    args = p.parse_args()
    task_id = enqueue(
        args.title, task_type=args.task_type, project=args.project,
        acceptance=args.acceptance, depends_on=args.depends_on,
    )
    print(f"enqueued {task_id}: {args.title!r} (type={args.task_type}, project={args.project})")


if __name__ == "__main__":
    main()
