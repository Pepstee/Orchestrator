"""Behavioural: enqueue drops a queued task into the inbox for the daemon to ingest."""
from __future__ import annotations

from pathlib import Path

from control.enqueue import enqueue
from control.inbox import ingest
from core.models import TaskStatus
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def test_enqueue_drops_then_ingests_as_queued(tmp_path: Path):
    inbox = str(tmp_path / "inbox")
    tid = enqueue("Do a thing", task_type="implement", project="demo",
                  acceptance=["works"], inbox=inbox)
    repo = TaskRepository(EventStore(str(tmp_path / "e.log")))
    assert ingest(repo, inbox) == 1
    t = repo.get(tid)
    assert t is not None
    assert t.status == TaskStatus.QUEUED and t.title == "Do a thing"
    assert t.project == "demo" and t.acceptance_criteria == ["works"]


def test_ingest_consumes_the_inbox(tmp_path: Path):
    inbox = str(tmp_path / "inbox")
    enqueue("a", project="demo", inbox=inbox)
    repo = TaskRepository(EventStore(str(tmp_path / "e.log")))
    assert ingest(repo, inbox) == 1
    assert ingest(repo, inbox) == 0   # nothing left after the first ingest
