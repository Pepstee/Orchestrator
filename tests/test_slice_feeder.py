"""The slice feeder automates the charter ritual (16 §4) without breaking its discipline:
one slice at a time, fed only when the previous is certified AND the graph is drained."""
from __future__ import annotations

from pathlib import Path

from control.slice_feeder import (
    FINAL_SLICE,
    PROJECT,
    SLICES,
    build_slice_task,
    certifications,
    feed_next,
    next_slice_due,
    read_cursor,
)
from core.models import Event, Task
from dispatch.repository import TaskRepository
from infra.atomic_io import read_json
from infra.event_store import EventStore


def _repo(tmp_path: Path) -> TaskRepository:
    return TaskRepository(EventStore(tmp_path / "e.log"))


def _seed_done_task(repo: TaskRepository, tid: str = "s1") -> None:
    repo.create(Task(task_id=tid, title="slice work", task_type="implement", project=PROJECT))
    repo.apply(tid, Event.CLAIM)
    repo.apply(tid, Event.COMPLETE)


def test_all_ten_slices_are_defined_and_gated():
    assert set(SLICES) == set(range(2, FINAL_SLICE + 1))
    for n, (goal, accept) in SLICES.items():
        assert PROJECT in goal or "orchestrator-v3" in goal
        assert len(accept) >= 4, f"slice {n} under-specified"
        assert any("green" in a for a in accept), f"slice {n} missing the gates criterion"


def test_not_due_without_certification(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed_done_task(repo)                       # graph terminal, but zero certifications
    assert certifications(repo) == 0
    assert not next_slice_due(repo, cursor=1)


def test_not_due_while_graph_active(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed_done_task(repo)
    repo.record_confirmation(PROJECT)           # certified...
    repo.create(Task(task_id="live", title="improve", task_type="plan", project=PROJECT))
    assert not next_slice_due(repo, cursor=1)   # ...but an improve round is still open


def test_due_when_certified_and_drained(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed_done_task(repo)
    repo.record_confirmation(PROJECT)
    assert next_slice_due(repo, cursor=1)
    assert not next_slice_due(repo, cursor=2)   # slice 3 needs a SECOND certification


def test_never_due_past_final_slice(tmp_path: Path):
    repo = _repo(tmp_path)
    _seed_done_task(repo)
    for _ in range(FINAL_SLICE):
        repo.record_confirmation(PROJECT)
    assert not next_slice_due(repo, cursor=FINAL_SLICE)


def test_feed_next_drops_task_and_advances_cursor(tmp_path: Path):
    (tmp_path / "state").mkdir()
    new_cursor = feed_next(tmp_path, cursor=1)
    assert new_cursor == 2
    files = list((tmp_path / "state" / "inbox").glob("*.json"))
    assert len(files) == 1
    data = read_json(files[0])
    assert data["task_type"] == "plan" and data["project"] == PROJECT
    assert "Slice 2" in data["title"] and len(data["acceptance_criteria"]) >= 4
    assert read_cursor(tmp_path / "state" / "v3_slice.json") == 2


def test_slice_tasks_are_plan_typed_with_charter_criteria():
    for n in SLICES:
        t = build_slice_task(n)
        assert t.task_type == "plan" and t.project == PROJECT
        assert t.acceptance_criteria == list(SLICES[n][1])
