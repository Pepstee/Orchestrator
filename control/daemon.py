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

import os
import signal
import time
from pathlib import Path
from typing import Callable

from control.budget import BudgetGovernor
from control.confirm import ingest_confirmations
from control.inbox import ingest
from control.loop import run as run_loop
from control.project import DEFAULT_TEST_COMMAND, ProjectOutcome, evaluate_project
from core.models import TaskStatus
from dispatch.dispatcher import Invoke, PAConsult
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
    """For each project whose graph is fully terminal: if its task signature has changed since the
    last evaluation (so an overseer fix re-opens it), evaluate the gates, record the status durably,
    and — if it passed the automated gates — run the assurance loop."""
    tiers = tiers if tiers is not None else hardening_tiers(governor)
    outcomes: list[ProjectOutcome] = []
    for project in sorted({t.project for t in repo.list()}):
        if not _all_terminal(repo, project):
            continue
        sig = _signature(repo, project)
        if evaluated.get(project) == sig:
            continue                                  # unchanged since last evaluation — skip
        outcome = evaluate_project(repo, project=project, projects_root=projects_root,
                                   test_command=test_command)
        evaluated[project] = sig
        repo.record_project_status(project, gates=outcome.gates, pending_user=outcome.pending_user)
        if outcome.pending_user:
            notify("Orchestrator", f"{project} is ready for your confirmation")  # the Da Nang nudge
            root = Path(projects_root) if projects_root else default_projects_root()
            assurance = run_assurance(str(resolve_project_dir(root, project)), tiers,
                                      should_stop=should_stop, governor=governor)
            repo.record_assurance(project, fully_hardened=assurance.fully_hardened,
                                  reason=assurance.stopped_reason)
        outcomes.append(outcome)
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

    def on_cycle() -> None:
        ingest_confirmations(repo)   # apply any user confirmations (the fourth gate)
        monitor_projects(repo, evaluated, governor=governor, should_stop=should_stop)
        rules = load_rules(pa_path)  # overseer evolves the PA from recurring failures (curated)
        evolve_pa(rules, repo.failure_causes())
        save_rules(pa_path, rules)

    def pa_consult(cause: str) -> str | None:
        return consult(cause, load_rules(pa_path))   # live fast-path over the active PA rules

    try:
        serve(repo, governor, make_subprocess_invoke(), should_stop=should_stop,
              on_cycle=on_cycle, pa_consult=pa_consult)
    finally:
        pidlock.release(lock)


if __name__ == "__main__":
    main()
