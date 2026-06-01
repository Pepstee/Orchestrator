"""control.intake — turn one goal into a runnable task graph (the minimal intake funnel).

Deterministic decomposition for now: a goal becomes a build task + a dependent validate task
(build -> independent judge), enqueued in one call so the daemon runs a goal end to end from a
single prompt. The richer LLM-driven multi-step Task Manager decomposition is the next step (P1).

    python -m control.intake "Scaffold a hello-world CLI with a test" --project demo --accept "runs" "has a test"
    python -m control.daemon
"""
from __future__ import annotations

import argparse

from control.enqueue import enqueue


def submit_goal(
    goal: str,
    *,
    project: str,
    acceptance: list[str] | None = None,
    store_path: str | None = None,
) -> list[str]:
    """Decompose a goal into a build -> judge graph and enqueue it. Returns [build_id, validate_id]."""
    build_id = enqueue(
        goal, task_type="implement", project=project,
        acceptance=acceptance, store_path=store_path,
    )
    validate_id = enqueue(
        f"Independently review: {goal}", task_type="validate", project=project,
        acceptance=acceptance, depends_on=[build_id], store_path=store_path,
    )
    return [build_id, validate_id]


def main() -> None:
    p = argparse.ArgumentParser(
        description="Submit one goal; it is decomposed into a build->judge graph for the daemon."
    )
    p.add_argument("goal")
    p.add_argument("--project", required=True)
    p.add_argument("--accept", nargs="*", default=[], dest="acceptance")
    args = p.parse_args()
    build_id, validate_id = submit_goal(args.goal, project=args.project, acceptance=args.acceptance)
    print(f"submitted to project {args.project!r}: build={build_id} validate={validate_id}")


if __name__ == "__main__":
    main()
