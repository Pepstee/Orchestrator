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

from control.breadth import breadth_allowance, read_flagship
from control.budget import BudgetGovernor
from control.confirm import ingest_confirmations
from control.inbox import ingest
from control.operator_chat import poll_operator_messages
from control.pool import DEFAULT_MAX_WORKERS, run_concurrent
from control.project import DEFAULT_TEST_COMMAND, ProjectOutcome, evaluate_project
from control.self_test import run_boot_self_test
from core.models import Event, Task, TaskStatus
from dispatch.dispatcher import Invoke, PAConsult, propagate_prerequisite_failures
from dispatch.repository import TaskRepository
from dispatch.runner import make_subprocess_invoke
from infra import pidlock
from infra.atomic_io import write_text_atomic
from infra.event_store import EventStore
from infra.notify import notify
from infra.workspace import default_projects_root, resolve_project_dir
from memory.overseer import (
    due_for_reset,
    due_for_succession,
    load_handoff,
    load_session,
    start_session,
)
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

# The persistent Overseer meta-agent. Its observe/succession tasks live under a RESERVED project name
# so they are never mistaken for a buildable project by monitor_projects. It "thinks" on a pulse.
OVERSEER_PROJECT = "__overseer__"
OVERSEER_PULSE_SECONDS = 2 * 3600   # two-hourly (operator decision, 12 Jun 2026: Pro-tier budget discipline)


def _status_summary(repo: TaskRepository) -> str:
    by_project: dict[str, list] = {}
    for t in repo.list():
        if t.project.startswith("__"):
            continue                          # reserved meta-projects aren't user-facing work
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


def _era_counts(repo: TaskRepository, project: str) -> tuple[int, int]:
    """(plan_count, oversee_count) for the CURRENT contract era. A re-scope plan (payload
    mode == 'rescope') opens a fresh era and budgets count from it, inclusive. Without this, a
    re-scoped project inherits its dead predecessor's spent planner — the 11 Jun stall read
    '20/20 iterations' of which most belonged to the abandoned June-era goal, and every future
    C9.x re-scope would arrive pre-exhausted and head straight for abandonment."""
    proj = [t for t in repo.list() if t.project == project]
    start = repo.abandon_watermark(project)   # an abandonment closes the era (12 Jun lesson)
    for i, t in enumerate(proj):
        if (t.task_type == "plan" and isinstance(t.payload, dict)
                and t.payload.get("mode") == "rescope"):
            start = max(start, i)
    era = proj[start:]
    return (sum(1 for t in era if t.task_type == "plan"),
            sum(1 for t in era if t.task_type == "oversee"))


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


def _advance_stalled(repo: TaskRepository, project: str, root: Path, *, reason: str, gates: dict) -> None:
    """The planner is spent (or quality is unmet): dispatch the OVERSEER to diagnose and fix (bounded
    by MAX_OVERSEER_INTERVENTIONS), and only once the overseer is also exhausted escalate to the user.
    Single source of truth for 'a project that can't finish itself' — used by both the gates-unmet and
    the failed-assurance paths so a sub-par project is never pinged as done."""
    _, oversee_passes = _era_counts(repo, project)   # interventions are budgeted per ERA
    st = _project_state(repo, project, root)
    if oversee_passes < MAX_OVERSEER_INTERVENTIONS:
        instruction = (
            f"This project is NOT ship-ready — {reason} (gates={gates}). Run the test suite, find why "
            "it falls short, fix the code so the quality bar is met, then it will be re-validated."
        )
        repo.create(Task(task_id=uuid.uuid4().hex[:12], title=instruction, task_type="oversee",
                         project=project, acceptance_criteria=st["acceptance"],
                         payload={"context": json.dumps(st["state"])}))   # overseer steps in (L6-bounded)
        notify("Orchestrator", f"{project} not ship-ready — overseer stepping in")
    else:
        # Planner AND overseer both exhausted. The operator is NOT in the loop, so we do NOT park this
        # waiting on them — the orchestrator decides: give up on this project (logged), free the slot,
        # keep working on everything else. It can always be re-enqueued later.
        repo.record_abandoned(project, reason=f"{reason}; planner and overseer both exhausted")
        notify("Orchestrator", f"{project} abandoned — could not complete it autonomously")


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
        if project.startswith("__"):
            continue                                  # reserved (e.g. the overseer's own meta-tasks)
        if repo.dormant_since_abandonment(project):
            continue                                  # parked by an abandonment (exhaustion OR directive):
                                                      # revival is a deliberate NEW task, never the monitor's
        if not _all_terminal(repo, project):
            continue
        sig = _signature(repo, project)
        if evaluated.get(project) == sig:
            continue                                  # unchanged since last evaluation — skip
        evaluated[project] = sig
        outcome = evaluate_project(repo, project=project, projects_root=projects_root,
                                   test_command=test_command)
        repo.record_project_status(project, gates=outcome.gates, pending_user=outcome.complete)
        outcomes.append(outcome)

        if outcome.complete:
            # All automated gates pass — but quality must come back CLEAN before it counts as done.
            # Run the ship-readiness ladder (tests rerun -> mutation -> acceptance-by-execution ->
            # adversarial). Clean => the orchestrator SELF-CERTIFIES done (no human gate). A finding
            # is NOT done and goes to the overseer.
            assurance = run_assurance(str(resolve_project_dir(root, project)), tiers,
                                      should_stop=should_stop, governor=governor)
            repo.record_assurance(project, fully_hardened=assurance.fully_hardened,
                                  reason=assurance.stopped_reason)
            if assurance.fully_hardened:
                repo.record_confirmation(project)   # certified at scope — shippable now, no human gate
                notify("Orchestrator",
                       f"{project} is CERTIFIED — all four gates passed AND the hardening ladder "
                       "came back clean. First-class, shippable work. Improvement rounds continue.")
                # FOREVER-IMPROVE: don't stop at 'good enough'. As long as the last round actually
                # produced integrated work, open another improvement round (security, tests, UX, perf,
                # GUI, cleaner code, better features...). It stops on its own only when a round finds
                # genuinely nothing left to improve (planner returns []) — no tight empty loop.
                if not _planner_done(repo, project):
                    st = _project_state(repo, project, root)
                    repo.create(Task(task_id=uuid.uuid4().hex[:12], title=st["goal"], task_type="plan",
                                     project=project, acceptance_criteria=st["acceptance"],
                                     payload={"mode": "improve", "state": st["state"]}))
                else:
                    notify("Orchestrator", f"{project} is DONE — self-certified and fully polished")
            else:
                _advance_stalled(repo, project, root,
                                 reason=f"not ship-ready ({assurance.stopped_reason})", gates=outcome.gates)
            continue

        # Deterministic gates unmet — advance the project, escalating only as the LAST resort:
        #   1. planner still has moves -> replan (next increment)
        #   2. planner spent           -> overseer fixes, then (if exhausted) escalate
        plan_passes, _ = _era_counts(repo, project)   # the planner's budget belongs to the era
        planner_spent = plan_passes >= MAX_PLAN_ITERATIONS or _planner_done(repo, project)
        if not planner_spent:
            st = _project_state(repo, project, root)
            repo.create(Task(task_id=uuid.uuid4().hex[:12], title=st["goal"], task_type="plan",
                             project=project, acceptance_criteria=st["acceptance"],
                             payload={"state": st["state"]}))   # next planning pass (the replan loop)
        else:
            _advance_stalled(repo, project, root,
                             reason="gates unmet; planner has no further steps", gates=outcome.gates)
    return outcomes


def _enqueue_meta(repo: TaskRepository, mode: str, session_id: str, *, resume: bool, context: str) -> None:
    """Enqueue an overseer meta-task (observe / succession) bound to the persistent session."""
    repo.create(Task(
        task_id=uuid.uuid4().hex[:12],
        title=f"overseer {mode}",
        task_type="oversee",
        project=OVERSEER_PROJECT,
        payload={"mode": mode, "session_id": session_id, "resume": resume, "context": context},
    ))


def overseer_pulse_health(repo: TaskRepository, meta: dict, notifier: Callable = notify) -> bool:
    """BG-5 (basic): detect a wedged or dying guardian — the failure class that once went silent
    for eleven hours. Unhealthy = ≥2 outstanding pulses (enqueued but never finishing) OR the two
    most recent terminal oversee runs both failed. Notifies once per episode, clears on recovery.
    Returns True only for the WEDGE (callers stop stacking pulses); a failed streak still permits
    fresh pulses — a new session is the self-heal, and budgets bound the cost."""
    oversee = [t for t in repo.list()
               if t.project == OVERSEER_PROJECT and t.task_type == "oversee"]
    pending = sum(1 for t in oversee
                  if t.status in (TaskStatus.QUEUED, TaskStatus.IN_PROGRESS)
                  and (t.payload.get("mode") if isinstance(t.payload, dict) else None)
                  != "operator_message")   # a queued operator chat is conversation, not a wedge
    terminal = [t for t in oversee if t.status in (TaskStatus.DONE, TaskStatus.FAILED)]
    failed_streak = len(terminal) >= 2 and all(
        t.status == TaskStatus.FAILED for t in terminal[-2:])
    unhealthy = pending >= 2 or failed_streak
    if unhealthy and not meta.get("pulse_alarm"):
        notifier("Overseer", f"BG-5: guardian unhealthy — {pending} pulse(s) outstanding"
                             + ("; last two runs failed" if failed_streak else ""))
        meta["pulse_alarm"] = True
    elif not unhealthy:
        meta["pulse_alarm"] = False
    return pending >= 2


def tick_overseer_session(
    repo: TaskRepository,
    session_path: Path,
    handoff_path: Path,
    meta: dict,
    *,
    now: float | None = None,
    pulse_interval: float = OVERSEER_PULSE_SECONDS,
) -> None:
    """Drive the persistent Overseer's session on a clock (the meta-agent's heartbeat):
      - on boot / at the reset interval -> start a FRESH session, seed it with the last handoff, and
        open it with a first observe pass (resume=False creates the Claude session);
      - within `lead` of the wipe -> enqueue a succession task so it writes its handoff in time;
      - otherwise, every `pulse_interval` -> an observe pass so it reasons continuously.
    All meta-tasks resume the SAME session, giving continuity of reasoning; the daily reset bounds
    context growth (A3), with the handoff carrying memory across the wipe."""
    now = time.time() if now is None else now
    wedged = overseer_pulse_health(repo, meta)   # BG-5: alarm before anything else
    session = load_session(session_path)
    if session is None or due_for_reset(session, now=now):
        rotating = session is not None
        session = start_session(session_path, now=now)
        meta["last_pulse"] = now
        meta["succession_for"] = ""
        meta["opened"] = session.session_id
        seed = load_handoff(handoff_path)
        ctx = (f"Handoff from your previous session (your only memory of it):\n{seed}\n\n"
               if seed else "") + _status_summary(repo)
        _enqueue_meta(repo, "observe", session.session_id, resume=False, context=ctx)  # create + wake
        if rotating:
            notify("Overseer", "session reset — fresh cycle, seeded from handoff")
        return

    if wedged:
        return   # don't stack more meta-tasks on a wedged guardian; budgets terminalise the stuck ones

    if due_for_succession(session, now=now) and meta.get("succession_for") != session.session_id:
        _enqueue_meta(repo, "succession", session.session_id, resume=True, context=_status_summary(repo))
        meta["succession_for"] = session.session_id
        return

    if now - meta.get("last_pulse", 0.0) >= pulse_interval:
        _enqueue_meta(repo, "observe", session.session_id, resume=True, context=_status_summary(repo))
        meta["last_pulse"] = now


def abandon_project(repo: TaskRepository, project: str, *, reason: str) -> int:
    """Cancel every non-terminal task of a doomed project (the overseer's abandon authority). Logged
    and reversible — the goal can be re-enqueued later; this only stops it burning cycles. Returns
    the count cancelled."""
    cancelled = 0
    for task in list(repo.list()):
        if task.project == project and task.status in (
                TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED):
            repo.cancel_task(task.task_id, cause=f"abandoned by overseer: {reason}"[:200])
            cancelled += 1
    return cancelled


def reprioritise_project(repo: TaskRepository, project: str, priority: int) -> int:
    """Set the scheduling priority of a project's queued tasks (the overseer steering what runs next).
    Returns the count adjusted."""
    n = 0
    for task in repo.list(TaskStatus.QUEUED):
        if task.project == project:
            repo.set_priority(task.task_id, priority)
            n += 1
    return n


def process_overseer_control(repo: TaskRepository) -> None:
    """Execute the overseer's queued control directives (it spawns these as `control` tasks, which the
    dispatcher never runs as agents). Each is claimed, executed, and completed — so it is terminal and
    durably logged. Guardrails: reserved/empty targets are ignored; the orchestrator is never a target."""
    for task in [t for t in repo.list(TaskStatus.QUEUED) if t.task_type == "control"]:
        p = task.payload if isinstance(task.payload, dict) else {}
        directive = p.get("directive")
        target = str(p.get("project", "")).strip()
        repo.apply(task.task_id, Event.CLAIM)
        if target and not target.startswith("__"):
            if directive == "abandon":
                n = abandon_project(repo, target, reason=str(p.get("reason", "")))
                # An abandon directive must STICK: record it durably so the monitor parks the
                # project instead of replanning it next cycle (12 Jun: the operator ordered
                # single-project focus, the overseer cancelled 7 fleets' tasks, and the monitor
                # resurrected every one of them within minutes — cancellation changed the
                # signature, evaluation found gates unmet, and the stall path re-spawned work).
                # Also closes the budget era, so a deliberate revival starts with a clean ledger.
                repo.record_abandoned(target, reason=f"overseer directive: {p.get('reason', '')}"[:200])
                notify("Overseer", f"abandoned {target}: {n} task(s) cancelled — {str(p.get('reason',''))[:80]}")
            elif directive == "reprioritise":
                try:
                    pri = int(p.get("priority", 0))
                except (TypeError, ValueError):
                    pri = 0
                reprioritise_project(repo, target, pri)
        repo.apply(task.task_id, Event.COMPLETE)


def serve(
    repo: TaskRepository,
    governor: BudgetGovernor,
    invoke: Invoke,
    *,
    should_stop: Callable[[], bool],
    poll_interval: float = 2.0,
    batch: int = 50,
    max_workers: int = DEFAULT_MAX_WORKERS,
    project_cap: int = 1,
    inbox: str | None = None,
    on_cycle: Callable[[], None] | None = None,
    pa_consult: PAConsult | None = None,
    allowed_projects: "Callable[[], set[str] | None] | None" = None,
) -> int:
    """Run ready tasks CONCURRENTLY (up to max_workers agents at once) until should_stop(), ingesting
    newly-enqueued work each cycle and running an optional per-cycle hook (project monitoring). Sleeps
    when idle. `project_cap` bounds concurrent agents per project (default 1 — one writer per project
    tree, no intra-project merge conflicts; projects still run in parallel). Returns total processed."""
    def _maintain() -> None:
        # The per-cycle housekeeping, defined once. Passed into run_concurrent so it also runs DURING a
        # long batch (not only between batches) — a never-idle pool can't starve the overseer pulse or
        # leave a failed prerequisite stranding the rest of a graph.
        ingest(repo, inbox)
        propagate_prerequisite_failures(repo)
        if on_cycle is not None:
            on_cycle()

    total = 0
    while not should_stop():
        _maintain()
        processed = run_concurrent(repo, invoke, governor, max_workers=max_workers,
                                   project_cap=project_cap, max_steps=batch, pa_consult=pa_consult,
                                   should_stop=should_stop, maintenance=_maintain,
                                   allowed_projects=allowed_projects)
        total += processed
        if processed == 0:
            time.sleep(poll_interval)
    return total


def deadline_should_stop(root: Path, state: dict, *, boot: float, hours: float,
                         now: float | None = None, notifier: Callable = notify) -> bool:
    """``AGENTIC_DEADLINE_HOURS`` — a strictly bounded run (L6 in time, not just iterations).
    At expiry: write the STOP sentinel (a self-chosen stop stays stopped — the supervisor sees
    it and stays down) and notify ONCE; the serve loop then drains in-flight work and exits
    gracefully. 0 = no deadline."""
    if hours <= 0:
        return False
    now = time.time() if now is None else now
    if now - boot < hours * 3600:
        return False
    if not state.get("notified"):
        write_text_atomic(root / "STOP", f"deadline: {hours:g}h run completed\n")
        notifier("Orchestrator", f"{hours:g}h deadline reached — draining in-flight work, "
                                 "then staying down (STOP written)")
        state["notified"] = True
    return True


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    state = root / "state"
    state.mkdir(exist_ok=True)
    lock = state / "daemon.pid"
    pidlock.acquire(lock)

    # BG-1 — enforcement before features: refuse to dispatch unless every law-linked check is
    # present, collected, and passing. Deliberately unbypassable (no flag, no env switch).
    ok, detail = run_boot_self_test(root)
    if not ok:
        pidlock.release(lock)
        notify("Orchestrator", f"BOOT SELF-TEST FAILED — refusing to dispatch: {detail[:160]}")
        raise SystemExit(3)

    stopped = {"flag": False}

    def _handle(_signum, _frame) -> None:
        stopped["flag"] = True

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    repo = TaskRepository.replay(EventStore(state / "tasks.events.log"))
    repo.reclaim_orphans()   # crash/restart recovery: re-queue tasks orphaned mid-flight (e.g. the 5h restart)
    repo.revive_transient_failures()   # a limit/restart/merge-conflict failure is never terminal — retry it (clears stale escalations)
    governor = BudgetGovernor(
        EventStore(state / "budget.events.log"),
        cap_usd=float(os.environ.get("AGENTIC_BUDGET_USD", "10.0")),
        kill_switch_path=state / "KILL",
    )
    stop_sentinel = root / "STOP"
    boot = time.time()
    deadline_hours = float(os.environ.get("AGENTIC_DEADLINE_HOURS", "0") or 0)
    deadline_state: dict = {}

    def should_stop() -> bool:
        return (stopped["flag"] or stop_sentinel.exists() or governor.should_stop()[0]
                or deadline_should_stop(root, deadline_state, boot=boot, hours=deadline_hours))

    evaluated: dict[str, frozenset] = {}
    burn_flag = {"notified": False}
    pa_path = state / "pa_rules.json"
    session_path = state / "overseer_session.json"
    handoff_path = state / "handoff_latest.md"
    heartbeat = {"last": time.time()}
    overseer_meta: dict = {}

    def on_cycle() -> None:
        if governor.burn_paused() and not burn_flag["notified"]:
            notify("Orchestrator", "burn-rate breaker tripped — success ratio collapsed; "
                                   "paid project work paused, overseer continues")
            burn_flag["notified"] = True
        elif not governor.burn_paused():
            burn_flag["notified"] = False
        ingest_confirmations(repo)   # apply any user confirmations (the fourth gate)
        monitor_projects(repo, evaluated, governor=governor, should_stop=should_stop)
        tick_overseer_session(repo, session_path, handoff_path, overseer_meta)  # the meta-agent's heartbeat
        poll_operator_messages(repo, session_path, overseer_meta,   # the operator's return path
                               project=OVERSEER_PROJECT, context_fn=lambda: _status_summary(repo))
        process_overseer_control(repo)   # execute the overseer's abandon directives
        rules = load_rules(pa_path)  # overseer evolves the PA from recurring failures (curated)
        evolve_pa(rules, repo.failure_causes())
        save_rules(pa_path, rules)
        if time.time() - heartbeat["last"] >= HEARTBEAT_SECONDS:   # 12h status ping, regardless of progress
            notify("Orchestrator", _status_summary(repo))
            heartbeat["last"] = time.time()

    def pa_consult(cause: str) -> str | None:
        return consult(cause, load_rules(pa_path))   # live fast-path over the active PA rules

    max_workers = max(1, int(os.environ.get("AGENTIC_MAX_WORKERS", str(DEFAULT_MAX_WORKERS))))
    project_cap = max(0, int(os.environ.get("AGENTIC_PROJECT_CONCURRENCY", "1")))
    flagship = read_flagship(state)   # BG-2: human-only configuration (state/flagship)
    if not repo.confirmed_projects() and flagship is None:
        notify("Orchestrator",
               "BG-2: no certification yet and state/flagship is unset — only the overseer dispatches")
    try:
        serve(repo, governor, make_subprocess_invoke(), should_stop=should_stop,
              max_workers=max_workers, project_cap=project_cap, on_cycle=on_cycle, pa_consult=pa_consult,
              allowed_projects=lambda: (set() if governor.burn_paused()       # breaker parks paid work
                                        else breadth_allowance(repo, flagship)))
    finally:
        pidlock.release(lock)


if __name__ == "__main__":
    main()
