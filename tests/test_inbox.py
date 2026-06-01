"""Behavioural: the inbox intake channel — drop a task, daemon ingests it, file consumed."""
from __future__ import annotations

from pathlib import Path

from control.inbox import drop, ingest
from core.models import Task, TaskStatus
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def test_drop_then_ingest(tmp_path: Path):
    inbox = tmp_path / "inbox"
    drop(Task(task_id="t1", title="x", task_type="implement", project="p"), inbox)
    assert (inbox / "t1.json").exists()
    repo = TaskRepository(EventStore(str(tmp_path / "e.log")))
    assert ingest(repo, inbox) == 1
    assert repo.get("t1").status == TaskStatus.QUEUED
    assert not (inbox / "t1.json").exists()   # consumed after ingest


def test_ingest_missing_inbox_is_zero(tmp_path: Path):
    repo = TaskRepository(EventStore(str(tmp_path / "e.log")))
    assert ingest(repo, tmp_path / "does-not-exist") == 0
