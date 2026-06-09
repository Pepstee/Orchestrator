"""Behavioural: the end-to-end Global Task lifecycle (build -> judge -> four-gate completion)."""
from __future__ import annotations

from pathlib import Path

from control.budget import BudgetGovernor
from control.project import run_project
from core.models import AgentResult, Task
from dispatch.repository import TaskRepository
from infra.event_store import EventStore

PASS = ("python", "-c", "raise SystemExit(0)")
FAIL = ("python", "-c", "raise SystemExit(1)")


def _setup(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="b1", title="build", task_type="implement", project="demo"))
    repo.create(Task(task_id="v1", title="validate", task_type="validate",
                     depends_on=["b1"], project="demo"))
    gov = BudgetGovernor(EventStore(tmp_path / "spend.log"), cap_usd=0.0,
                         kill_switch_path=tmp_path / "KILL")
    return repo, gov


def _ok(_task: Task) -> AgentResult:
    return AgentResult(ok=True, summary="ok")


def test_self_certifies_when_automated_gates_pass(tmp_path: Path):
    repo, gov = _setup(tmp_path)
    out = run_project(repo, gov, project="demo", invoke=_ok,
                      projects_root=str(tmp_path), test_command=PASS)
    assert out.gates == {"tests": True, "acceptance": True, "judge": True, "authenticity": True}
    assert out.completion.done and out.complete      # no human gate — automated gates alone = done
    assert out.tasks_done == 2


def test_failed_build_blocks_and_judge_never_runs(tmp_path: Path):
    repo, gov = _setup(tmp_path)

    def invoke(task: Task) -> AgentResult:
        return AgentResult(ok=task.task_type != "implement", summary="x", cause="build failed")

    out = run_project(repo, gov, project="demo", invoke=invoke,
                      projects_root=str(tmp_path), test_command=PASS)
    assert not out.gates["acceptance"]      # the build task did not reach DONE
    assert not out.gates["judge"]           # validate stayed gated on the failed prerequisite
    assert not out.complete


def test_judge_rejection_blocks(tmp_path: Path):
    repo, gov = _setup(tmp_path)

    def invoke(task: Task) -> AgentResult:
        return AgentResult(ok=task.task_type != "validate", summary="x", cause="judge rejected")

    out = run_project(repo, gov, project="demo", invoke=invoke,
                      projects_root=str(tmp_path), test_command=PASS)
    assert out.gates["acceptance"] and not out.gates["judge"]
    assert "judge" in out.completion.unmet


def test_failing_tests_block(tmp_path: Path):
    repo, gov = _setup(tmp_path)
    out = run_project(repo, gov, project="demo", invoke=_ok,
                      projects_root=str(tmp_path), test_command=FAIL)
    assert not out.gates["tests"] and "tests" in out.completion.unmet
