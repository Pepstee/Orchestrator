"""Behavioural: the dispatch cycle runs tasks, gates on dependencies, and persists causes."""
from __future__ import annotations

from pathlib import Path

from core.models import AgentResult, Task, TaskStatus
from dispatch.dispatcher import run_one, run_until_idle, select_next_task
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def _repo(tmp_path: Path) -> TaskRepository:
    return TaskRepository(EventStore(tmp_path / "e.log"))


def _ok(_task: Task) -> AgentResult:
    return AgentResult(ok=True, summary="done")


def _fail(_task: Task) -> AgentResult:
    return AgentResult(ok=False, summary="nope", cause="boom")


def test_runs_a_single_task(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="t1", title="x", task_type="implement"))
    outcome = run_one(repo, _ok)
    assert outcome is not None
    task, result = outcome
    assert task.task_id == "t1" and result.ok
    assert repo.get("t1").status == TaskStatus.DONE


def test_dependency_gated_order(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="a", title="a", task_type="implement"))
    repo.create(Task(task_id="b", title="b", task_type="implement", depends_on=["a"]))
    assert select_next_task(repo).task_id == "a"   # b is not ready yet
    assert run_until_idle(repo, _ok) == 2
    assert repo.get("a").status == TaskStatus.DONE
    assert repo.get("b").status == TaskStatus.DONE


def test_dependent_not_run_when_prereq_fails(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="a", title="a", task_type="implement"))
    repo.create(Task(task_id="b", title="b", task_type="implement", depends_on=["a"]))

    def invoke(task: Task) -> AgentResult:
        return _fail(task) if task.task_id == "a" else _ok(task)

    run_until_idle(repo, invoke)
    assert repo.get("a").status == TaskStatus.FAILED
    assert repo.get("b").status == TaskStatus.QUEUED   # never became ready


def test_run_one_enqueues_bounded_spawned_tasks(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="p1", title="plan", task_type="plan", project="x"))
    spawned = [
        Task(task_id=f"s{i}", title=f"s{i}", task_type="implement", project="x").to_dict()
        for i in range(60)
    ]

    def invoke(_task: Task) -> AgentResult:
        return AgentResult(ok=True, summary="planned", spawned_tasks=spawned)

    run_one(repo, invoke)
    created = [t for t in repo.list() if t.task_id.startswith("s")]
    assert len(created) == 50   # capped by MAX_SPAWNED_PER_TASK (L6)


def test_failure_persists_cause(tmp_path: Path):
    p = tmp_path / "e.log"
    repo = TaskRepository(EventStore(p))
    repo.create(Task(task_id="t1", title="x", task_type="implement", max_retries=0))
    run_one(repo, _fail)   # no retries -> straight to escalate/FAIL
    assert repo.get("t1").status == TaskStatus.FAILED
    results = [e.data for e in EventStore(p).replay() if e.kind == "task_result"]
    assert results and results[-1]["cause"] == "boom"   # cause is durable (audit)
