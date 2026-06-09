"""dispatch.dispatcher — dependency-gated selection + the run-one-task cycle.

`select_next_task` returns the next QUEUED task whose prerequisites are all DONE; `run_one`
drives it claim -> invoke agent -> complete/fail, persisting every step via the repository.
The agent invocation is INJECTED (subprocess by default), so the whole cycle is testable with
a deterministic stub — no LLM required.
"""
from __future__ import annotations

from typing import Callable

from core.models import AgentResult, Event, Task, TaskStatus
from dispatch.repository import MAX_TRANSIENT_REQUEUES, TaskRepository
from infra.llm import RATE_LIMIT_HINTS, is_transient_cause   # single source of limit/transient classification

# An invoke takes a task and returns its AgentResult (subprocess agent, or a test stub).
Invoke = Callable[[Task], AgentResult]

# A PA consult maps a failure cause to a deterministic action (requeue/escalate/...), or None.
PAConsult = Callable[[str], "str | None"]

# Bound dynamic decomposition: a single task may spawn at most this many sub-tasks (law L6).
MAX_SPAWNED_PER_TASK = 50


def is_rate_limited(result: AgentResult) -> bool:
    """A provider usage/rate limit is transient (it resets) — NOT a task failure. Detected from the
    cause wording (the RateLimited marker, or the provider's own message, e.g. '5-hour limit reached')."""
    cause = (result.cause or "").lower()
    return bool(cause) and any(hint in cause for hint in RATE_LIMIT_HINTS)


def is_transient(result: AgentResult) -> bool:
    """A transient infra condition that is NOT the task's fault (provider limit, or a restart-kill).
    Such a task is requeued and retried, never failed or escalated — otherwise a restart manufactures
    phantom 'needs you' escalations. Classification lives once in infra.llm.is_transient_cause."""
    return is_transient_cause(result.cause or "")


def is_ready(repo: TaskRepository, task: Task) -> bool:
    """A queued task is ready when every prerequisite exists and is DONE."""
    if task.status != TaskStatus.QUEUED:
        return False
    for dep_id in task.depends_on:
        dep = repo.get(dep_id)
        if dep is None or dep.status != TaskStatus.DONE:
            return False
    return True


def select_next_task(repo: TaskRepository) -> Task | None:
    ready = [
        task for task in repo.list(TaskStatus.QUEUED)
        if task.task_type != "control"   # control directives are executed by the daemon, never run as agents
        and is_ready(repo, task)
    ]
    if not ready:
        return None
    # Highest priority first; ties keep creation order (max returns the first maximal element).
    return max(ready, key=lambda t: t.priority)


def run_one(
    repo: TaskRepository,
    invoke: Invoke,
    *,
    pa_consult: PAConsult | None = None,
) -> tuple[Task, AgentResult] | None:
    """Run the next ready task end-to-end. Returns (task, result), or None if nothing is ready.

    On success: enqueue any (bounded) spawned tasks, then COMPLETE. On failure: the ladder —
    consult the PA first (deterministic fast-path: requeue a transient cause, escalate a known
    dead-end), else retry until ``max_retries``, else escalate. Every rung is bounded (L6)."""
    task = select_next_task(repo)
    if task is None:
        return None
    repo.apply(task.task_id, Event.CLAIM)            # QUEUED -> IN_PROGRESS
    result = invoke(task)
    repo.record_result(task.task_id, result)         # persist ok/summary/cause (audit, L10)
    settle(repo, task, result, pa_consult=pa_consult)
    return task, result


def settle(repo: TaskRepository, task: Task, result: AgentResult, *, pa_consult: PAConsult | None = None) -> None:
    """Apply an agent's result to its task: on success enqueue any (bounded) spawned tasks and
    COMPLETE; on failure run the failure ladder. Shared by the sequential and concurrent drivers so
    decomposition + the failure ladder behave identically whichever drives the loop."""
    if result.ok:
        for spec in result.spawned_tasks[:MAX_SPAWNED_PER_TASK]:
            try:
                repo.create(Task.from_dict(spec))
            except (KeyError, TypeError, ValueError):
                pass  # malformed spawn spec — skip, never crash the loop
        repo.apply(task.task_id, Event.COMPLETE)
    else:
        _handle_failure(repo, task, result, pa_consult)


def _handle_failure(
    repo: TaskRepository,
    task: Task,
    result: AgentResult,
    pa_consult: PAConsult | None,
) -> None:
    """The failure ladder: transient requeue (BUDGETED) -> PA fast-path -> retry -> escalate.
    Every rung is bounded by DURABLE counters (BG-3): record_result counted this failure off the
    event log before we got here, so no budget can be laundered by a restart."""
    if is_transient(result) and repo.transient_count(task.task_id) <= MAX_TRANSIENT_REQUEUES:
        repo.apply(task.task_id, Event.REQUEUE)   # provider limit OR restart-kill: retry, no penalty
        return
    action = pa_consult(result.cause or "") if pa_consult else None
    total = repo.transient_count(task.task_id) + repo.hard_failure_count(task.task_id)
    if action == "requeue" and total <= MAX_TRANSIENT_REQUEUES + task.max_retries:
        task.retries += 1                            # PA requeue — finite combined budget (BG-3)
        repo.apply(task.task_id, Event.REQUEUE)
    elif action == "escalate":                       # PA: known dead-end — terminal
        repo.record_escalation(task.task_id, cause=result.cause or "", reason="pa:escalate",
                               project=task.project)
        repo.apply(task.task_id, Event.FAIL)
    elif (task.retries < task.max_retries
          and repo.hard_failure_count(task.task_id) <= task.max_retries):   # ordinary retry, durable budget
        task.retries += 1
        repo.apply(task.task_id, Event.REQUEUE)
    else:                                            # budgets exhausted — terminal, recorded
        repo.record_escalation(task.task_id, cause=result.cause or "", reason="retries exhausted",
                               project=task.project)
        repo.apply(task.task_id, Event.FAIL)


def propagate_prerequisite_failures(repo: TaskRepository) -> int:
    """Cascade-fail any task whose prerequisite has FAILED — it can never become ready, so leaving it
    QUEUED forever freezes the whole project as non-terminal (the overnight-run stall). Marks such
    tasks FAILED with a self-explaining cause (L10), iterating to a fixpoint for transitive chains.
    Returns the count cascaded."""
    total = 0
    while True:
        failed = {t.task_id for t in repo.list() if t.status == TaskStatus.FAILED}
        cascaded = 0
        for task in repo.list():
            if task.status not in (TaskStatus.QUEUED, TaskStatus.BLOCKED):
                continue
            blockers = [d for d in task.depends_on if d in failed]
            if not blockers:
                continue
            if task.status == TaskStatus.QUEUED:
                repo.apply(task.task_id, Event.BLOCK)        # QUEUED -> BLOCKED
            repo.apply(task.task_id, Event.FAIL)             # BLOCKED -> FAILED (prerequisite cascade)
            repo.record_result(task.task_id, AgentResult(
                ok=False, summary="prerequisite failed",
                cause=f"prerequisite failed: {blockers}"))
            cascaded += 1
        total += cascaded
        if cascaded == 0:
            return total


def run_until_idle(
    repo: TaskRepository,
    invoke: Invoke,
    max_steps: int = 1000,
    *,
    pa_consult: PAConsult | None = None,
) -> int:
    """Run ready tasks until none remain (or max_steps), then cascade any prerequisite failures so a
    stranded graph terminates instead of hanging. Returns the count processed."""
    processed = 0
    while processed < max_steps:
        if run_one(repo, invoke, pa_consult=pa_consult) is None:
            break
        processed += 1
    propagate_prerequisite_failures(repo)
    return processed
