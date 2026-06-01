"""control.enqueue — drop a task into the daemon's intake channel (the minimal manual intake).

Writes one task file into the inbox; the daemon ingests it on its next loop cycle, whether it is
already running (live enqueue) or started later. This is the thin manual intake until the guided
"build-your-idea" funnel matures (control.intake is the one-goal-to-graph step).

    python -m control.enqueue "Scaffold a hello-world Python CLI with a pytest test" --project demo
"""
from __future__ import annotations

import argparse
import uuid

from control.inbox import drop
from core.models import Task


def enqueue(
    title: str,
    *,
    task_type: str = "implement",
    project: str = "default",
    acceptance: list[str] | None = None,
    depends_on: list[str] | None = None,
    inbox: str | None = None,
) -> str:
    task_id = uuid.uuid4().hex[:12]
    drop(
        Task(
            task_id=task_id, title=title, task_type=task_type, project=project,
            acceptance_criteria=list(acceptance or []), depends_on=list(depends_on or []),
        ),
        inbox,
    )
    return task_id


def main() -> None:
    p = argparse.ArgumentParser(description="Enqueue a task for the daemon (via the inbox).")
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
