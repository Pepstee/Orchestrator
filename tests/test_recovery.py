"""Behavioural: crash/restart recovery — orphaned in-progress tasks are reclaimed, not lost."""
from __future__ import annotations

from pathlib import Path

from core.models import Event, Task, TaskStatus
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def test_reclaim_requeues_orphaned_in_progress(tmp_path: Path):
    log = tmp_path / "e.log"
    repo = TaskRepository(EventStore(log))
    repo.create(Task(task_id="t", title="x", task_type="implement"))
    repo.apply("t", Event.CLAIM)                       # IN_PROGRESS, then the daemon "dies"

    restarted = TaskRepository.replay(EventStore(log))  # a fresh daemon replays the log
    assert restarted.get("t").status == TaskStatus.IN_PROGRESS   # orphaned by the restart
    assert restarted.reclaim_orphans() == 1
    assert restarted.get("t").status == TaskStatus.QUEUED        # re-queued -> will run again


def test_reclaim_is_a_noop_with_nothing_in_flight(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a", title="a", task_type="implement"))
    repo.apply("a", Event.CLAIM)
    repo.apply("a", Event.COMPLETE)                    # terminal, not in-flight
    assert repo.reclaim_orphans() == 0
    assert repo.get("a").status == TaskStatus.DONE
