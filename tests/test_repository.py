"""Behavioural: the task lifecycle persists, replays (resume-from-step), and is transition-safe."""
from __future__ import annotations

from pathlib import Path

from core.models import Event, Task, TaskStatus
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def _task(tid: str = "t1") -> Task:
    return Task(task_id=tid, title="x", task_type="implement")


def test_lifecycle_persists(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(_task())
    repo.apply("t1", Event.CLAIM)
    assert repo.get("t1").status == TaskStatus.IN_PROGRESS
    repo.apply("t1", Event.COMPLETE)
    assert repo.get("t1").status == TaskStatus.DONE


def test_replay_reconstructs_state(tmp_path: Path):
    p = tmp_path / "e.log"
    repo = TaskRepository(EventStore(p))
    repo.create(_task())
    repo.apply("t1", Event.CLAIM)
    # simulate crash + restart: rebuild from the log alone
    repo2 = TaskRepository.replay(EventStore(p))
    assert repo2.get("t1").status == TaskStatus.IN_PROGRESS


def test_illegal_transition_is_noop(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(_task())  # QUEUED
    repo.apply("t1", Event.COMPLETE)  # illegal from QUEUED -> no-op, no crash
    assert repo.get("t1").status == TaskStatus.QUEUED


def test_queued_can_be_blocked(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(_task())
    repo.apply("t1", Event.BLOCK)  # the v1 bug, now legal
    assert repo.get("t1").status == TaskStatus.BLOCKED
