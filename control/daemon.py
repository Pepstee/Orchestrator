"""control.daemon — the single supervised entrypoint (law L8) + autonomous project lifecycle.

Resumes the durable task log, ingests the inbox (live enqueue), runs ready tasks under the
budget-bounded loop, and — once a project's whole graph is terminal — evaluates the four-gate
completion contract, runs the progressive-assurance loop on a finalised project, and records
`pending_user` durably (the signal a confirmation tray reads). Exactly one instance (pid lock);
no auto-restart, so a soft-stop cannot resurrect it.

    Run:   python -m control.daemon
    Stop:  Ctrl-C / SIGTERM, or `touch STOP`
    Budget cap: AGENTIC_BUDGET_USD env var (default 10.0); kill-switch: state/KILL
"""
from __future__ import annotations

import json
import os
import signal
import time
import uuid
from pathlib import Path
from typing import Callable

from control.budget import BudgetGovernor
from control.confirm import ingest_confirmations
from control.inbox import ingest
from control.loop import run as run_loop
from control.project import DEFAULT_TEST_COMMAND, ProjectOutcome, evaluate_project
from core.models import Task, TaskStatus
from dispatch.dispatcher import Invoke, PAConsult, propagate_prerequisite_failures
from dispatch.repository import TaskRepository
from dispatch.runner import make_subprocess_invoke
from infra import pidlock
from infra.event_store import EventStore
from infra.notify import notify
from infra.workspace import default_projects_root, resolve_project_dir
from pa.overseer import evolve as evolve_pa
from pa.rules import consult, load_rules, save_rules
from validation.assurance import Tier, hardening_tiers, run_assurance


def _all_terminal(repo: TaskRepository, project: str) -> bool:
    tasks = [t for t in repo.list() if t.project == project]
    return bool(tasks) and all(t.status in (TaskStatus.DONE, TaskStatus.FAILED) for t in tasks)


def _signature(repo: TaskRepository, project: str) -> frozenset:
    """A project's current (task_id, status) set — changes when the overseer adds/re-runs work."""
    return frozenset((t.task_id, t.status.value) for t in repo.list() if t.project == project)


# Safety bound on the replan loop (L6): at most this many planning passes per project. The NORMAL
# stop is the gates passing; this only stops a project that never converges.
MAX_PLAN_ITERATIONS = 20

# When the planner is out of moves but the gates still fail, the OVERSEER steps in to diagnose and
# fix (run the tests, repair the code) rather than letting the project stall. Bounded (L6): after
# this many overseer interventions with the gates still unmet, escalate to the user.
MAX_OVERSEER_INTERVENTIONS = 3

# Heartbeat: ping a status summary at least this often, regardless of progress.
HEARTBEAT_SECONDS = 12 * 3600


def _status_summary(repo: TaskRepository) -> str:
    by_project: dict[str, list] = {}
    for t in repo.list():
        by_project.setdefault(t.project, []).append(t.status)
    if not by_project:
        return "orchestrator running — no projects yet"
    parts = [f"{p} {sum(1 for s in sts if s == TaskStatus.DONE)}/{len(sts)}"
             for p, sts in sorted(by_project.items())]
    return f"{len(by_project)} project(s): " + "; ".join(parts[:8])


def _planner_done(repo: TaskRepository, project: str) -> bool:
    """True if the most recent plan task completed but spawned no further work (the planner judged
    the goal met / had nothing to add) — so re-planning again would be pointless."""
    proj = [t for t in repo.list() if t.project == project]
    plans = [t for t in proj if t.task_type == "plan"]
    if not plans or plans[-1].status != TaskStatus.DONE:
        return False
    idx = proj.index(plans[-1])
    # Only builder/validator work counts as planner progress — overseer interventions don't.
    return not any(t.task_type in ("implement", "validate") for t in proj[idx + 1:])


def _project_state(repo: TaskRepository, project: str, root: Path) -> dict:
    """The current state the planner reasons over: goal, acceptance, done steps, failures+causes, files."""
    proj = [t for t in repo.list() if t.project == project]
    goal = next((t.title for t in proj if t.task_type == "plan"), project)
    acceptance = next((list(t.acceptance_criteria) for t in proj
                       if t.task_type == "plan" and t.acceptance_criteria), [])
    results = repo.last_results()
    done = [t.title for t in proj if t.status == TaskStatus.DONE and t.task_type != "plan"]
    failed = [{"title": t.title, "cause": (results.get(t.task_id, {}).get("cause") or "")}
              for t in proj if t.status == TaskStatus.FAILED]
    files: list[str] = []
    try:
        pdir = resolve_project_dir(root, project)
        files = sorted(str(p.relative_to(pdir)) for p in pdir.rglob("*")
                       if p.is_file() and "__pycache__" not in p.parts)[:60]
    except (OSError, ValueError):
        pass
    return {"goal": goal, "acceptance": acceptance,
            "state": {"done": done, "failed": failed, "files": files}}


def monitor_projects(
    repo: TaskRepository,
    evaluated: dict[str, frozenset],
    *,
    projects_root: str | None = None,
    test_command: tuple[str, ...] = DEFAULT_TEST_COMMAND,
    governor: object | None = None,
    tiers: list[Tier] | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> list[ProjectOutcome]:
    """For each drained project (graph fully terminal, signature changed): evaluate the gates, then
    either finalise (3/4 gates -> pending_user: ping + harden, don't stop), RE-PLAN (gates unmet and
    under the iteration cap -> ask the planner for the next increment, feeding back failures), or
    escalate (planner done / cap reached but gates unmet -> the project is stuck)."""
    tiers = tiers if tiers is not None else hardening_tiers(governor)
    root = Path(projects_root) if projects_root else default_projects_root()
    outcomes: list[ProjectOutcome] = []
    for project in sorted({t.project for t in repo.list()}):
        if not _all_terminal(repo, project):
            continue
        sig = _signature(repo, project)
        if evaluated.get(project) == sig:
            continue                                  # unchanged since last evaluation — skip
        evaluated[project] = sig
        outcome = evaluate_project(repo, project=project, projects_root=projects_root,
                                   test_command=test_command)
        repo.record_project_status(project, gates=outcome.gates, pending_user=outcome.pending_user)
        outcomes.append(outcome)

        if outcome.pending_user:                      # 3/4 gates -> instant ping, keep hardening
            notify("Orchestrator", f"{project} is ready for your confirmation")
            assurance = run_assurance(str(resolve_project_dir(root, project)), tiers,
                                      should_stop=should_stop, governor=governor)
            repo.record_assurance(project, fully_hardened=assurance.fully_hardened,
                                  reason=assurance.stopped_reason)
            continue

        # Gates unmet — advance the project, escalating to the user only as the LAST resort:
        #   1. planner still has moves      -> replan (next increment)
        #   2. planner spent, overseer left -> the overseer diagnoses + fixes (don't stall)
        #   3. both spent                   -> escalate (genuinely stuck)
        plan_passes = sum(1 for t in repo.list() if t.project == project and t.task_type == "plan")
        oversee_passes = sum(1 for t in repo.list() if t.project == project and t.task_type == "oversee")
        planner_spent = plan_passes >= MAX_PLAN_ITERATIONS or _planner_done(repo, project)
        st = _project_state(repo, project, root)
        if not planner_spent:
            repo.create(Task(task_id=uuid.uuid4().hex[:12], title=st["goal"], task_type="plan",
                             project=project, acceptance_criteria=st["acceptance"],
                             payload={"state": st["state"]}))   # next planning pass (the replan loop)
        elif oversee_passes < MAX_OVERSEER_INTERVENTIONS:
            instruction = (
                f"This project has STALLED — the automated gates are not all passing (gates={outcome.gates}) "
                "and the planner has no further steps. Run the test suite, find why it fails, fix the code "
                "so the tests pass and the goal is met, then it will be re-validated."
            )
            repo.create(Task(task_id=uuid.uuid4().hex[:12], title=instruction, task_type="oversee",
                             project=project, acceptance_criteria=st["acceptance"],
                             payload={"context": json.dumps(st["state"])}))   # overseer steps in (L6-bounded)
            notify("Orchestrator", f"{project} stalled — overseer stepping in")
        else:
            repo.record_escalation(f"{project}:stuck", cause="gates unmet; planner and overseer both exhausted",
                                   reason="needs you", project=project)
            notify("Orchestrator", f"{project} needs you — overseer couldn't unstick it")
    return outcomes


def serve(
    repo: TaskRepository,
    governor: BudgetGovernor,
    invoke: Invoke,
    *,
    should_stop: Callable[[], bool],
    poll_interval: float = 2.0,
    batch: int = 50,
    inbox: str | None = None,
    on_cycle: Callable[[], None] | None = None,
    pa_consult: PAConsult | None = None,
) -> int:
    """Run ready tasks until should_stop(), ingesting newly-enqueued work each cycle and running an
    optional per-cycle hook (project monitoring). Sleeps when idle. Returns total tasks processed."""
    total = 0
    while not should_stop():
        ingest(repo, inbox)
        processed = run_loop(repo, invoke, governor, max_steps=batch, pa_consult=pa_consult)
        propagate_prerequisite_failures(repo)   # don't let a few failures strand the rest of the graph
        total += processed
        if on_cycle is not None:
            on_cycle()
        if processed == 0:
            time.sleep(poll_interval)
    return total


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    state = root / "state"
    state.mkdir(exist_ok=True)
    lock = state / "daemon.pid"
    pidlock.acquire(lock)

    stopped = {"flag": False}

    def _handle(_signum, _frame) -> None:
        stopped["flag"] = True

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    repo = TaskRepository.replay(EventStore(state / "tasks.events.log"))
    repo.reclaim_orphans()   # crash/restart recovery: re-queue tasks orphaned mid-flight (e.g. the 5h restart)
    governor = BudgetGovernor(
        EventStore(state / "budget.events.log"),
        cap_usd=float(os.environ.get("AGENTIC_BUDGET_USD", "10.0")),
        kill_switch_path=state / "KILL",
    )
    stop_sentinel = root / "STOP"

    def should_stop() -> bool:
        return stopped["flag"] or stop_sentinel.exists() or governor.should_stop()[0]

    evaluated: dict[str, frozenset] = {}
    pa_path = state / "pa_rules.json"
    heartbeat = {"last": time.time()}

    def on_cycle() -> None:
        ingest_confirmations(repo)   # apply any user confirmations (the fourth gate)
        monitor_projects(repo, evaluated, governor=governor, should_stop=should_stop)
        rules = load_rules(pa_path)  # overseer evolves the PA from recurring failures (curated)
        evolve_pa(rules, repo.failure_causes())
        save_rules(pa_path, rules)
        if time.time() - heartbeat["last"] >= HEARTBEAT_SECONDS:   # 12h status ping, regardless of progress
            notify("Orchestrator", _status_summary(repo))
            heartbeat["last"] = time.time()

    def pa_consult(cause: str) -> str | None:
        return consult(cause, load_rules(pa_path))   # live fast-path over the active PA rules

    try:
        serve(repo, governor, make_subprocess_invoke(), should_stop=should_stop,
              on_cycle=on_cycle, pa_consult=pa_consult)
    finally:
        pidlock.release(lock)


if __name__ == "__main__":
    main()
