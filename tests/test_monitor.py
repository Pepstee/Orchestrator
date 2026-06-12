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
OK_TIERS = [lambda _d: GateResult("ok", True)]   # trivial passing assurance for non-assurance tests


def _demo_dir(root: Path) -> Path:
    """The demo project dir WITH a declared acceptance criterion (D25: no default-pass gates)."""
    proj = resolve_project_dir(root, "demo")
    (proj / "acceptance").write_text("echo demo ok\n", encoding="utf-8")
    return proj


def _finished_project(repo: TaskRepository) -> None:
    repo.create(Task(task_id="b", title="build", task_type="implement", project="demo"))
    repo.create(Task(task_id="v", title="judge", task_type="validate", project="demo", depends_on=["b"]))
    for tid in ("b", "v"):
        repo.apply(tid, Event.CLAIM)
        repo.apply(tid, Event.COMPLETE)


def test_evaluate_project_complete(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    _demo_dir(tmp_path)
    out = evaluate_project(repo, project="demo", projects_root=str(tmp_path), test_command=PASS)
    assert out.gates == {"tests": True, "acceptance": True, "judge": True, "authenticity": True}
    assert out.complete   # all automated gates pass -> self-certified, no human gate


def test_monitor_finalises_hardens_and_records(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    _demo_dir(tmp_path)
    hardened = []
    tiers = [lambda pd: (hardened.append(pd) or GateResult("edge", True))]
    evaluated: dict = {}
    outs = monitor_projects(repo, evaluated, projects_root=str(tmp_path),
                            test_command=PASS, tiers=tiers)
    assert len(outs) == 1 and outs[0].complete
    assert "demo" in evaluated
    assert hardened, "assurance loop should run on a finalised project"
    # clean assurance -> the orchestrator SELF-CERTIFIES (no human gate): a confirmation is recorded
    confirmed = [e.data for e in EventStore(str(tmp_path / "e.log")).replay()
                 if e.kind == "project_confirmed"]
    assert confirmed and confirmed[-1]["project"] == "demo"
    assurance = [e.data for e in EventStore(str(tmp_path / "e.log")).replay()
                 if e.kind == "assurance_result"]
    assert assurance and assurance[-1]["project"] == "demo" and assurance[-1]["fully_hardened"]


def test_failed_assurance_blocks_the_ping_and_calls_overseer(tmp_path: Path):
    """The deterministic gates pass, but a failing assurance tier (e.g. mutation) means NOT ship-ready:
    the project goes to the overseer, it does NOT land in your confirmation tray (charter bar 6)."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    _demo_dir(tmp_path)
    fail_tiers = [lambda _d: GateResult("mutation", False, "score 1/5")]
    outs = monitor_projects(repo, {}, projects_root=str(tmp_path), test_command=PASS, tiers=fail_tiers)
    assert outs and outs[0].complete                      # automated gates passed...
    oversee = [t for t in repo.list() if t.project == "demo" and t.task_type == "oversee"]
    assert oversee                                        # ...but quality failed -> overseer, not done
    assurance = [e.data for e in EventStore(str(tmp_path / "e.log")).replay()
                 if e.kind == "assurance_result"]
    assert assurance and not assurance[-1]["fully_hardened"]


def test_self_certify_opens_a_forever_improve_round(tmp_path: Path):
    """Certifying a project at scope must NOT stop it — it opens an 'improve' round so the orchestrator
    keeps making it better (security, tests, UX, perf, features...) instead of going idle."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    _demo_dir(tmp_path)
    monitor_projects(repo, {}, projects_root=str(tmp_path), test_command=PASS, tiers=OK_TIERS)
    confirmed = [e for e in EventStore(str(tmp_path / "e.log")).replay() if e.kind == "project_confirmed"]
    improve = [t for t in repo.list() if t.task_type == "plan"
               and isinstance(t.payload, dict) and t.payload.get("mode") == "improve"]
    assert confirmed and improve   # certified at scope AND a fresh improvement round queued


def test_monitor_skips_in_progress_project(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="b", title="build", task_type="implement", project="demo"))  # QUEUED
    outs = monitor_projects(repo, {}, projects_root=str(tmp_path), test_command=PASS)
    assert outs == []   # not all-terminal yet


def test_monitor_finalises_each_project_once(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    _demo_dir(tmp_path)
    evaluated: dict = {}
    assert len(monitor_projects(repo, evaluated, projects_root=str(tmp_path),
                                test_command=PASS, tiers=OK_TIERS)) == 1
    assert monitor_projects(repo, evaluated, projects_root=str(tmp_path),
                            test_command=PASS, tiers=OK_TIERS) == []


def test_monitor_records_failed_gates_without_hardening(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    _demo_dir(tmp_path)
    hardened = []
    tiers = [lambda pd: (hardened.append(pd) or GateResult("edge", True))]
    # failing tests -> not pending_user -> no assurance
    outs = monitor_projects(repo, {}, projects_root=str(tmp_path),
                            test_command=("python", "-c", "raise SystemExit(1)"), tiers=tiers)
    assert outs and not outs[0].complete
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
    _demo_dir(tmp_path)
    out = evaluate_project(repo, project="demo", projects_root=str(tmp_path), test_command=PASS)
    assert out.gates["judge"] and out.complete


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
    _demo_dir(tmp_path)
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
    _demo_dir(tmp_path)
    monitor_projects(repo, {}, projects_root=str(tmp_path), test_command=PASS,
                     tiers=[lambda _d: GateResult("t", True)])
    oversee = [t for t in repo.list() if t.project == "demo" and t.task_type == "oversee"]
    esc = [e for e in EventStore(str(tmp_path / "e.log")).replay() if e.kind == "escalation"]
    assert len(oversee) == 1 and not esc              # overseer dispatched, user NOT escalated


def test_monitor_abandons_after_overseer_exhausted(tmp_path: Path):
    """Operator is NOT in the loop: once planner AND overseer are both spent, the orchestrator gives
    up on the project (abandons, logged) — it never parks waiting on the user."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="p", title="Build X", task_type="plan", project="demo"))
    repo.apply("p", Event.CLAIM)
    repo.apply("p", Event.COMPLETE)
    for i in range(3):                                # 3 overseer interventions already spent (the cap)
        repo.create(Task(task_id=f"o{i}", title="fix", task_type="oversee", project="demo"))
        repo.apply(f"o{i}", Event.CLAIM)
        repo.apply(f"o{i}", Event.FAIL)
    _demo_dir(tmp_path)
    monitor_projects(repo, {}, projects_root=str(tmp_path), test_command=PASS,
                     tiers=[lambda _d: GateResult("t", True)])
    events = list(EventStore(str(tmp_path / "e.log")).replay())
    abandoned = [e.data for e in events if e.kind == "project_abandoned"]
    assert abandoned and abandoned[-1]["project"] == "demo"        # gave up autonomously
    assert not [e for e in events if e.kind == "escalation"]       # never escalated to a human


def test_improve_loop_continues_then_stops_when_maxed(tmp_path: Path):
    """Forever-improve: certifying opens an improve round; while that round is pending the project is
    NOT re-evaluated; once it drains having produced nothing more, the project re-evaluates and the
    loop STOPS (no tight empty cycling) — exactly the bounded-by-productivity behaviour."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _finished_project(repo)
    _demo_dir(tmp_path)
    evaluated: dict = {}
    assert len(monitor_projects(repo, evaluated, projects_root=str(tmp_path),
                                test_command=PASS, tiers=OK_TIERS)) == 1     # certify + open improve round
    assert monitor_projects(repo, evaluated, projects_root=str(tmp_path),
                            test_command=PASS, tiers=OK_TIERS) == []          # improve round pending -> skip
    improve = [t for t in repo.list() if t.task_type == "plan"
               and isinstance(t.payload, dict) and t.payload.get("mode") == "improve"]
    assert len(improve) == 1
    repo.apply(improve[0].task_id, Event.CLAIM)
    repo.apply(improve[0].task_id, Event.COMPLETE)                           # round drains, spawned nothing
    outs = monitor_projects(repo, evaluated, projects_root=str(tmp_path),
                            test_command=PASS, tiers=OK_TIERS)
    assert len(outs) == 1                                                     # re-evaluated after the round
    again = [t for t in repo.list() if t.task_type == "plan"
             and isinstance(t.payload, dict) and t.payload.get("mode") == "improve"]
    assert len(again) == 1   # no new improve round — planner found nothing more, so the loop halts


# ---- a re-scope opens a fresh planning era (the 11 Jun inherited-exhaustion stall) ----

def test_rescope_resets_plan_and_oversee_budgets(tmp_path: Path):
    from control.daemon import _era_counts
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    for i in range(25):   # the dead predecessor goal burnt its whole planner
        repo.create(Task(task_id=f"old{i}", title="old plan", task_type="plan", project="demo"))
    repo.create(Task(task_id="ov_old", title="old intervention", task_type="oversee", project="demo"))
    plans, oversees = _era_counts(repo, "demo")
    assert plans == 25 and oversees == 1, "no re-scope yet: lifetime counts apply"
    repo.create(Task(task_id="contract", title="re-scope (D2.5)", task_type="plan",
                     project="demo", payload={"mode": "rescope"}))
    repo.create(Task(task_id="p1", title="next increment", task_type="plan", project="demo"))
    repo.create(Task(task_id="ov1", title="intervention", task_type="oversee", project="demo"))
    plans, oversees = _era_counts(repo, "demo")
    assert plans == 2, "the era starts at the contract: rescope + 1, not 27"
    assert oversees == 1, "old-era interventions don't count against the new contract"


def test_abandonment_closes_the_era_for_whoever_resurrects(tmp_path: Path):
    """12 Jun: the overseer's resurrection plan (bare payload — directives can't set
    mode='rescope') inherited the dead era's spent budgets and was abandoned at first failure.
    An abandonment now closes the era; post-abandonment tasks start with a clean ledger."""
    from control.daemon import _era_counts
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    for i in range(25):
        repo.create(Task(task_id=f"old{i}", title="plan", task_type="plan", project="demo"))
    for i in range(4):
        repo.create(Task(task_id=f"ov{i}", title="iv", task_type="oversee", project="demo"))
    repo.record_abandoned("demo", reason="exhausted")
    repo.create(Task(task_id="resurrect", title="MUTATION-HARDENING (bare payload)",
                     task_type="plan", project="demo"))
    repo.create(Task(task_id="ov_new", title="iv", task_type="oversee", project="demo"))
    plans, oversees = _era_counts(repo, "demo")
    assert plans == 1 and oversees == 1, "the resurrection owns a fresh era, no payload magic"
    # and the watermark survives a restart (replayed from the event log)
    revived = TaskRepository.replay(EventStore(tmp_path / "e.log"))
    assert revived.abandon_watermark("demo") == 29
