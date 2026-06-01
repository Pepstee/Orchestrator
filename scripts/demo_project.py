"""Manual end-to-end demo: build -> judge -> four-gate completion, with REAL agents.

Spends a few cents (Builder on Claude sonnet); the Judge is free (Codex on the Go plan). Requires
`claude` and `codex` authenticated. Runs under a $1 budget cap with a kill-switch. This is a
*temporary* manual harness — superseded by the supervised entrypoint (L8). Run from the repo root:

    python3 scripts/demo_project.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control.budget import BudgetGovernor
from control.project import run_project
from core.models import Task
from dispatch.repository import TaskRepository
from dispatch.runner import make_subprocess_invoke
from infra.event_store import EventStore


def main() -> None:
    state = Path(__file__).resolve().parents[1] / "state"
    state.mkdir(exist_ok=True)
    repo = TaskRepository(EventStore(state / "demo.events.log"))
    repo.create(Task(
        task_id="b1", task_type="implement", project="demo",
        title="Scaffold a tiny Python hello-world CLI with a pytest test",
    ))
    repo.create(Task(
        task_id="v1", task_type="validate", project="demo", depends_on=["b1"],
        title="hello-world CLI with a test",
        acceptance_criteria=["the CLI prints output", "a meaningful test exists and passes"],
    ))
    gov = BudgetGovernor(
        EventStore(state / "budget.events.log"), cap_usd=1.0, kill_switch_path=state / "KILL"
    )
    outcome = run_project(repo, gov, project="demo", invoke=make_subprocess_invoke())
    print(outcome)


if __name__ == "__main__":
    main()
