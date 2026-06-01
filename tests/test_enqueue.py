"""Behavioural: enqueue appends durable, queued tasks the daemon will pick up on replay."""
from __future__ import annotations

from pathlib import Path

from control.enqueue import enqueue
from core.models import TaskStatus
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def test_enqueue_adds_a_queued_task(tmp_path: Path):
    store = str(tmp_path / "tasks.events.log")
    tid = enqueue("Do a thing", task_type="implement", project="demo",
                  acceptance=["works"], store_path=store)
    repo = TaskRepository.replay(EventStore(store))
    t = repo.get(tid)
    assert t is not None
    assert t.status == TaskStatus.QUEUED and t.title == "Do a thing"
    assert t.project == "demo" and t.acceptance_criteria == ["works"]


def test_enqueue_accumulates_and_wires_dependencies(tmp_path: Path):
    store = str(tmp_path / "tasks.events.log")
    b = enqueue("build", project="demo", store_path=store)
    v = enqueue("review", task_type="validate", project="demo",
                depends_on=[b], store_path=store)
    repo = TaskRepository.replay(EventStore(store))
    assert {b, v} <= {t.task_id for t in repo.list()}
    assert repo.get(v).depends_on == [b]
