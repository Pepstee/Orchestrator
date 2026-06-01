"""control.project — the Global Task lifecycle: run a project's graph, then judge completion.

Drives a project's task graph (build tasks, then a dependency-gated validate task) through the
budget-bounded run loop, then evaluates the four-gate completion contract:
  - tests:      the project's own suite passes (run_test_gate)
  - acceptance: every build task reached DONE (the planned work completed)
  - judge:      the validate task reached DONE (the independent Judge passed)
  - user:       your confirmation (always pending here — the Da Nang model: it parks for you)
A project that passes the first three lands at pending_user — finished but awaiting your one-tap
confirmation, exactly the two-tier completion model.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from control.budget import BudgetGovernor
from control.loop import run as run_loop
from core.models import TaskStatus
from dispatch.dispatcher import Invoke
from dispatch.repository import TaskRepository
from infra.workspace import default_projects_root, resolve_project_dir
from validation.gates import CompletionResult, evaluate_completion, run_test_gate

DEFAULT_TEST_COMMAND = ("python", "-m", "pytest", "-q")


@dataclass
class ProjectOutcome:
    project: str
    tasks_done: int
    tasks_total: int
    gates: dict[str, bool]
    completion: CompletionResult
    pending_user: bool


def evaluate_project(
    repo: TaskRepository,
    *,
    project: str,
    projects_root: str | None = None,
    test_command: tuple[str, ...] = DEFAULT_TEST_COMMAND,
) -> ProjectOutcome:
    """Evaluate the four-gate contract for a project (no loop). Reused by run_project and the daemon."""
    proj_tasks = [t for t in repo.list() if t.project == project]
    builds = [t for t in proj_tasks if t.task_type != "validate"]
    validates = [t for t in proj_tasks if t.task_type == "validate"]

    acceptance = bool(builds) and all(t.status == TaskStatus.DONE for t in builds)
    judge_ok = bool(validates) and all(t.status == TaskStatus.DONE for t in validates)

    root = Path(projects_root) if projects_root else default_projects_root()
    project_dir = resolve_project_dir(root, project)
    tests_ok = run_test_gate(str(project_dir), command=test_command).passed

    gates = {"tests": tests_ok, "acceptance": acceptance, "judge": judge_ok, "user": False}
    completion = evaluate_completion(gates)
    return ProjectOutcome(
        project=project,
        tasks_done=sum(1 for t in proj_tasks if t.status == TaskStatus.DONE),
        tasks_total=len(proj_tasks),
        gates=gates,
        completion=completion,
        pending_user=(completion.unmet == ["user"]),
    )


def run_project(
    repo: TaskRepository,
    governor: BudgetGovernor,
    *,
    project: str,
    invoke: Invoke,
    projects_root: str | None = None,
    test_command: tuple[str, ...] = DEFAULT_TEST_COMMAND,
    max_steps: int = 1000,
) -> ProjectOutcome:
    run_loop(repo, invoke, governor, max_steps)
    return evaluate_project(repo, project=project, projects_root=projects_root, test_command=test_command)
