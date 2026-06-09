"""Behavioural: the control-plane channel — repository cancel + the daemon's abandon executor."""
from __future__ import annotations

from pathlib import Path

from control.daemon import abandon_project, process_overseer_control
from core.models import Event, Task, TaskStatus
from dispatch.dispatcher import select_next_task
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def _repo(tmp_path: Path) -> TaskRepository:
    return TaskRepository(EventStore(tmp_path / "e.log"))


def test_cancel_task_terminates_a_queued_task(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="q", title="x", task_type="implement", project="p"))
    repo.cancel_task("q", cause="abandoned")
    assert repo.get("q").status == TaskStatus.FAILED                 # QUEUED -> BLOCKED -> FAILED
    kinds = [e.kind for e in EventStore(str(tmp_path / "e.log")).replay()]
    assert "task_cancelled" in kinds


def test_cancel_task_noop_on_terminal(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="d", title="x", task_type="implement", project="p"))
    repo.apply("d", Event.CLAIM)
    repo.apply("d", Event.COMPLETE)                                  # DONE
    repo.cancel_task("d", cause="too late")
    assert repo.get("d").status == TaskStatus.DONE                   # unchanged


def test_abandon_project_cancels_all_non_terminal(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="a", title="x", task_type="implement", project="doomed"))   # QUEUED
    repo.create(Task(task_id="b", title="y", task_type="implement", project="doomed"))
    repo.apply("b", Event.CLAIM)                                     # IN_PROGRESS
    repo.create(Task(task_id="c", title="z", task_type="implement", project="doomed"))
    repo.apply("c", Event.CLAIM)
    repo.apply("c", Event.COMPLETE)                                  # DONE (left alone)
    n = abandon_project(repo, "doomed", reason="unbuildable")
    assert n == 2
    assert repo.get("a").status == TaskStatus.FAILED and repo.get("b").status == TaskStatus.FAILED
    assert repo.get("c").status == TaskStatus.DONE                   # finished work is preserved


def test_control_task_is_not_run_as_an_agent(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="ctl", title="abandon x", task_type="control", project="__overseer__"))
    repo.create(Task(task_id="real", title="build", task_type="implement", project="p"))
    assert select_next_task(repo).task_id == "real"                 # dispatcher skips control tasks


def test_process_control_executes_abandon_and_completes(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="t1", title="x", task_type="implement", project="doomed"))
    repo.create(Task(task_id="ctl", title="abandon doomed", task_type="control", project="__overseer__",
                     payload={"directive": "abandon", "project": "doomed", "reason": "stalled"}))
    process_overseer_control(repo)
    assert repo.get("t1").status == TaskStatus.FAILED               # target cancelled
    assert repo.get("ctl").status == TaskStatus.DONE                # directive consumed (terminal)


def test_process_control_ignores_reserved_target(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="ctl", title="abandon meta", task_type="control", project="__overseer__",
                     payload={"directive": "abandon", "project": "__overseer__", "reason": "x"}))
    process_overseer_control(repo)
    assert repo.get("ctl").status == TaskStatus.DONE                # consumed, but no harm done


# --- reprioritise: persisted priority + selection order ---

def test_set_priority_persists_across_replay(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="t", title="x", task_type="implement", project="p"))
    repo.set_priority("t", 7)
    replayed = TaskRepository.replay(EventStore(str(tmp_path / "e.log")))
    assert replayed.get("t").priority == 7                          # survives restart


def test_select_next_prefers_higher_priority(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="lo", title="x", task_type="implement", project="p"))     # priority 0
    repo.create(Task(task_id="hi", title="y", task_type="implement", project="p"))
    repo.set_priority("hi", 5)
    assert select_next_task(repo).task_id == "hi"                   # higher priority runs first


def test_process_control_reprioritises_queued_tasks(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="a", title="x", task_type="implement", project="urgent"))
    repo.create(Task(task_id="b", title="y", task_type="implement", project="urgent"))
    repo.create(Task(task_id="ctl", title="bump urgent", task_type="control", project="__overseer__",
                     payload={"directive": "reprioritise", "project": "urgent", "priority": 9}))
    process_overseer_control(repo)
    assert repo.get("a").priority == 9 and repo.get("b").priority == 9
    assert repo.get("ctl").status == TaskStatus.DONE
