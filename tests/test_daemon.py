"""L8 — the supervised run loop: processes ready work, then stops cleanly on should_stop()."""
from __future__ import annotations

from pathlib import Path

from control.budget import BudgetGovernor
from control.daemon import serve
from core.models import AgentResult, Task, TaskStatus
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def _ok(_task: Task) -> AgentResult:
    return AgentResult(ok=True, summary="ok")


def _gov(tmp_path: Path, cap: float = 0.0) -> BudgetGovernor:
    return BudgetGovernor(EventStore(tmp_path / "b.log"), cap_usd=cap, kill_switch_path=tmp_path / "KILL")


def test_serve_processes_ready_tasks_then_stops(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a", title="a", task_type="implement", project="p"))
    repo.create(Task(task_id="b", title="b", task_type="validate", depends_on=["a"], project="p"))

    def should_stop() -> bool:  # stop once everything is terminal
        return all(t.status in (TaskStatus.DONE, TaskStatus.FAILED) for t in repo.list())

    total = serve(repo, _gov(tmp_path), _ok, should_stop=should_stop, poll_interval=0)
    assert total == 2
    assert repo.get("a").status == TaskStatus.DONE and repo.get("b").status == TaskStatus.DONE


def test_serve_stops_immediately_when_asked(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a", title="a", task_type="implement", project="p"))
    total = serve(repo, _gov(tmp_path), _ok, should_stop=lambda: True, poll_interval=0)
    assert total == 0
    assert repo.get("a").status == TaskStatus.QUEUED   # never ran


def test_serve_halts_on_kill_switch(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a", title="a", task_type="implement", project="p"))
    gov = _gov(tmp_path, cap=100.0)
    gov.engage_kill_switch("operator stop")
    total = serve(repo, gov, _ok, should_stop=lambda: gov.should_stop()[0], poll_interval=0)
    assert total == 0
