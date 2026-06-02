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
    evaluated: dict = {}
    outs = monitor_projects(repo, evaluated, projects_root=str(tmp_path),
                            test_command=PASS, tiers=tiers)
    assert len(outs) == 1 and outs[0].pending_user
    assert "demo" in evaluated
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
    outs = monitor_projects(repo, {}, projects_root=str(tmp_path), test_command=PASS)
    assert outs == []   # not all-terminal yet


def test_monitor_finalises_each_project_once(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    resolve_project_dir(tmp_path, "demo")
    evaluated: dict = {}
    assert len(monitor_projects(repo, evaluated, projects_root=str(tmp_path), test_command=PASS)) == 1
    assert monitor_projects(repo, evaluated, projects_root=str(tmp_path), test_command=PASS) == []


def test_monitor_records_failed_gates_without_hardening(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    resolve_project_dir(tmp_path, "demo")
    hardened = []
    tiers = [lambda pd: (hardened.append(pd) or GateResult("edge", True))]
    # failing tests -> not pending_user -> no assurance
    outs = monitor_projects(repo, {}, projects_root=str(tmp_path),
                            test_command=("python", "-c", "raise SystemExit(1)"), tiers=tiers)
    assert outs and not outs[0].pending_user
    assert not hardened   # assurance does not run on a project that failed its gates


def test_superseded_failed_validate_does_not_poison_judge(tmp_path: Path):
    """A validate that failed (e.g. during an outage) must not block the judge gate forever once a
    fresh validate passes — otherwise a successful retry can never bring the project to the tray."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="b", title="build", task_type="implement", project="demo"))
    repo.apply("b", Event.CLAIM)
    repo.apply("b", Event.COMPLETE)
    repo.create(Task(task_id="v_old", title="validate", task_type="validate", project="demo"))
    repo.apply("v_old", Event.CLAIM)
    repo.apply("v_old", Event.FAIL)                  # the stale failure
    repo.create(Task(task_id="v_new", title="validate", task_type="validate", project="demo"))
    repo.apply("v_new", Event.CLAIM)
    repo.apply("v_new", Event.COMPLETE)              # a fresh pass supersedes it
    resolve_project_dir(tmp_path, "demo")
    out = evaluate_project(repo, project="demo", projects_root=str(tmp_path), test_command=PASS)
    assert out.gates["judge"] and out.pending_user


def test_status_summary_reads_projects(tmp_path: Path):
    from control.daemon import _status_summary
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a", title="a", task_type="implement", project="proj"))
    repo.apply("a", Event.CLAIM)
    repo.apply("a", Event.COMPLETE)
    repo.create(Task(task_id="b", title="b", task_type="implement", project="proj"))
    s = _status_summary(repo)
    assert "proj" in s and "1/2" in s   # 1 of 2 done


def test_monitor_replans_when_gates_unmet_and_under_cap(tmp_path: Path):
    """A drained project with unmet gates must re-invoke the planner for the next increment (the
    replan loop), not stop after one cycle."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="p", title="Build X", task_type="plan", project="demo"))
    repo.apply("p", Event.CLAIM)
    repo.apply("p", Event.COMPLETE)
    repo.create(Task(task_id="b", title="impl", task_type="implement", project="demo"))
    repo.apply("b", Event.CLAIM)
    repo.apply("b", Event.FAIL)                       # build failed -> acceptance gate unmet
    resolve_project_dir(tmp_path, "demo")
    monitor_projects(repo, {}, projects_root=str(tmp_path), test_command=PASS,
                     tiers=[lambda _d: GateResult("t", True)])
    plans = [t for t in repo.list() if t.project == "demo" and t.task_type == "plan"]
    assert len(plans) == 2                            # planner re-invoked for the next increment


def test_monitor_overseer_steps_in_when_planner_stalls(tmp_path: Path):
    """When the planner is out of moves but the gates still fail, the OVERSEER is dispatched to fix it
    — NOT escalated to the user (that's the last resort)."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="p", title="Build X", task_type="plan", project="demo"))
    repo.apply("p", Event.CLAIM)
    repo.apply("p", Event.COMPLETE)                   # plan done, no builder/validator work after -> planner spent
    resolve_project_dir(tmp_path, "demo")
    monitor_projects(repo, {}, projects_root=str(tmp_path), test_command=PASS,
                     tiers=[lambda _d: GateResult("t", True)])
    oversee = [t for t in repo.list() if t.project == "demo" and t.task_type == "oversee"]
    esc = [e for e in EventStore(str(tmp_path / "e.log")).replay() if e.kind == "escalation"]
    assert len(oversee) == 1 and not esc              # overseer dispatched, user NOT escalated


def test_monitor_escalates_only_after_overseer_exhausted(tmp_path: Path):
    """Escalate to the user only once the planner AND the overseer (cap) are both spent."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="p", title="Build X", task_type="plan", project="demo"))
    repo.apply("p", Event.CLAIM)
    repo.apply("p", Event.COMPLETE)
    for i in range(3):                                # 3 overseer interventions already spent (the cap)
        repo.create(Task(task_id=f"o{i}", title="fix", task_type="oversee", project="demo"))
        repo.apply(f"o{i}", Event.CLAIM)
        repo.apply(f"o{i}", Event.FAIL)
    resolve_project_dir(tmp_path, "demo")
    monitor_projects(repo, {}, projects_root=str(tmp_path), test_command=PASS,
                     tiers=[lambda _d: GateResult("t", True)])
    esc = [e.data for e in EventStore(str(tmp_path / "e.log")).replay() if e.kind == "escalation"]
    assert esc and esc[-1]["project"] == "demo"       # now escalated — both planner and overseer spent


def test_monitor_reevaluates_when_signature_changes(tmp_path: Path):
    """An overseer fix adds a fresh task; once it completes, the project must re-finalise (not stay
    stuck on the first evaluation) — this is what returns an overseer-fixed project to the tray."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    resolve_project_dir(tmp_path, "demo")
    evaluated: dict = {}
    assert len(monitor_projects(repo, evaluated, projects_root=str(tmp_path), test_command=PASS)) == 1
    assert monitor_projects(repo, evaluated, projects_root=str(tmp_path), test_command=PASS) == []  # unchanged
    repo.create(Task(task_id="o", title="overseer fix", task_type="oversee", project="demo"))
    repo.apply("o", Event.CLAIM)
    repo.apply("o", Event.COMPLETE)
    outs = monitor_projects(repo, evaluated, projects_root=str(tmp_path), test_command=PASS)
    assert len(outs) == 1   # signature changed -> re-evaluated
