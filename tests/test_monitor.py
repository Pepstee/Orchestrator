"""Behavioural: the daemon's project monitor finalises a completed project, hardens it, records it."""
from __future__ import annotations

from pathlib import Path

from control.daemon import monitor_projects
from control.project import evaluate_project
from core.models import Event, Task
from dispatch.repository import TaskRepository
from infra.event_store import EventStore
from infra.workspace import resolve_project_dir
from validation.gates import GateResult

PASS = ("python", "-c", "raise SystemExit(0)")


def _finished_project(repo: TaskRepository) -> None:
    repo.create(Task(task_id="b", title="build", task_type="implement", project="demo"))
    repo.create(Task(task_id="v", title="judge", task_type="validate", project="demo", depends_on=["b"]))
    for tid in ("b", "v"):
        repo.apply(tid, Event.CLAIM)
        repo.apply(tid, Event.COMPLETE)


def test_evaluate_project_pending_user(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    resolve_project_dir(tmp_path, "demo")   # ensure the project dir exists for the test gate
    out = evaluate_project(repo, project="demo", projects_root=str(tmp_path), test_command=PASS)
    assert out.gates == {"tests": True, "acceptance": True, "judge": True, "user": False}
    assert out.pending_user


def test_monitor_finalises_hardens_and_records(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    resolve_project_dir(tmp_path, "demo")
    hardened = []
    tiers = [lambda pd: (hardened.append(pd) or GateResult("edge", True))]
    finalised: set[str] = set()
    outs = monitor_projects(repo, finalised, projects_root=str(tmp_path),
                            test_command=PASS, tiers=tiers)
    assert len(outs) == 1 and outs[0].pending_user
    assert "demo" in finalised
    assert hardened, "assurance loop should run on a finalised project"
    # durable pending_user status was recorded
    statuses = [e.data for e in EventStore(str(tmp_path / "e.log")).replay()
                if e.kind == "project_status"]
    assert statuses and statuses[-1]["project"] == "demo" and statuses[-1]["pending_user"]
    # the assurance outcome is now persisted too
    assurance = [e.data for e in EventStore(str(tmp_path / "e.log")).replay()
                 if e.kind == "assurance_result"]
    assert assurance and assurance[-1]["project"] == "demo" and assurance[-1]["fully_hardened"]


def test_monitor_skips_in_progress_project(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="b", title="build", task_type="implement", project="demo"))  # QUEUED
    outs = monitor_projects(repo, set(), projects_root=str(tmp_path), test_command=PASS)
    assert outs == []   # not all-terminal yet


def test_monitor_finalises_each_project_once(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    resolve_project_dir(tmp_path, "demo")
    finalised: set[str] = set()
    assert len(monitor_projects(repo, finalised, projects_root=str(tmp_path), test_command=PASS)) == 1
    assert monitor_projects(repo, finalised, projects_root=str(tmp_path), test_command=PASS) == []


def test_monitor_records_failed_gates_without_hardening(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    resolve_project_dir(tmp_path, "demo")
    hardened = []
    tiers = [lambda pd: (hardened.append(pd) or GateResult("edge", True))]
    # failing tests -> not pending_user -> no assurance
    outs = monitor_projects(repo, set(), projects_root=str(tmp_path),
                            test_command=("python", "-c", "raise SystemExit(1)"), tiers=tiers)
    assert outs and not outs[0].pending_user
    assert not hardened   # assurance does not run on a project that failed its gates
