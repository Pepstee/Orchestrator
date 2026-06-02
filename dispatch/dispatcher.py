"""dispatch.dispatcher — dependency-gated selection + the run-one-task cycle.

`select_next_task` returns the next QUEUED task whose prerequisites are all DONE; `run_one`
drives it claim -> invoke agent -> complete/fail, persisting every step via the repository.
The agent invocation is INJECTED (subprocess by default), so the whole cycle is testable with
a deterministic stub — no LLM required.
"""
from __future__ import annotations

from typing import Callable

from core.models import AgentResult, Event, Task, TaskStatus
from dispatch.repository import TaskRepository

# An invoke takes a task and returns its AgentResult (subprocess agent, or a test stub).
Invoke = Callable[[Task], AgentResult]

# A PA consult maps a failure cause to a deterministic action (requeue/escalate/...), or None.
PAConsult = Callable[[str], "str | None"]

# Bound dynamic decomposition: a single task may spawn at most this many sub-tasks (law L6).
MAX_SPAWNED_PER_TASK = 50

# A provider usage/rate limit is transient (it resets) — not a task failure. The cause carries the
# RateLimited marker from infra.llm (or the provider's own wording).
_RATE_LIMIT_HINTS = ("ratelimited", "rate limit", "usage limit", "429", "quota",
                     "too many requests", "overloaded")


def is_rate_limited(result: AgentResult) -> bool:
    cause = (result.cause or "").lower()
    return bool(cause) and any(hint in cause for hint in _RATE_LIMIT_HINTS)


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
    for task in repo.list(TaskStatus.QUEUED):
        if is_ready(repo, task):
            return task
    return None


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
    if result.ok:
        if result.spawned_tasks:                     # dynamic decomposition (bounded, L6)
            for spec in result.spawned_tasks[:MAX_SPAWNED_PER_TASK]:
                try:
                    repo.create(Task.from_dict(spec))
                except (KeyError, TypeError, ValueError):
                    pass  # malformed spawn spec — skip, never crash the loop
        repo.apply(task.task_id, Event.COMPLETE)
        return task, result
    _handle_failure(repo, task, result, pa_consult)
    return task, result


def _handle_failure(
    repo: TaskRepository,
    task: Task,
    result: AgentResult,
    pa_consult: PAConsult | None,
) -> None:
    """The failure ladder: rate-limit backoff -> PA fast-path -> retry -> escalate."""
    if is_rate_limited(result):
        repo.apply(task.task_id, Event.REQUEUE)   # transient provider limit: retry later, no penalty, no escalation
        return
    action = pa_consult(result.cause or "") if pa_consult else None
    if action == "requeue":                          # PA: transient — retry without penalty
        task.retries += 1
        repo.apply(task.task_id, Event.REQUEUE)
    elif action == "escalate":                       # PA: known dead-end — straight to the user
        repo.record_escalation(task.task_id, cause=result.cause or "", reason="pa:escalate",
                               project=task.project)
        repo.apply(task.task_id, Event.FAIL)
    elif task.retries < task.max_retries:            # no decisive PA verdict — ordinary retry
        task.retries += 1
        repo.apply(task.task_id, Event.REQUEUE)
    else:                                            # retries exhausted — escalate
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
