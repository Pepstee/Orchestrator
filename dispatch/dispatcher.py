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

# Bound dynamic decomposition: a single task may spawn at most this many sub-tasks (law L6).
MAX_SPAWNED_PER_TASK = 50


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


def run_one(repo: TaskRepository, invoke: Invoke) -> tuple[Task, AgentResult] | None:
    """Run the next ready task end-to-end. Returns (task, result), or None if nothing is ready."""
    task = select_next_task(repo)
    if task is None:
        return None
    repo.apply(task.task_id, Event.CLAIM)            # QUEUED -> IN_PROGRESS
    result = invoke(task)
    repo.record_result(task.task_id, result)         # persist ok/summary/cause (audit, L10)
    if result.ok and result.spawned_tasks:           # dynamic decomposition (bounded, L6)
        for spec in result.spawned_tasks[:MAX_SPAWNED_PER_TASK]:
            try:
                repo.create(Task.from_dict(spec))
            except (KeyError, TypeError, ValueError):
                pass  # malformed spawn spec — skip, never crash the loop
    repo.apply(task.task_id, Event.COMPLETE if result.ok else Event.FAIL)
    return task, result


def run_until_idle(repo: TaskRepository, invoke: Invoke, max_steps: int = 1000) -> int:
    """Run ready tasks until none remain (or max_steps). Returns the count processed."""
    processed = 0
    while processed < max_steps:
        if run_one(repo, invoke) is None:
            break
        processed += 1
    return processed
