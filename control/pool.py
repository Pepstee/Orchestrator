"""control.pool — the CONCURRENT driver: run many agents at once (the throughput + resilience win).

The single-threaded loop ran one agent at a time, so one slow/hung call froze everything and the
token budget sat idle. This driver keeps up to `max_workers` agent calls in flight at once. The
design is deliberately race-free: ONLY the slow `invoke` (the LLM subprocess) runs on worker threads;
every state mutation — claiming, recording, spawning, completing/failing — and every git operation
happens on this one main thread. So there is no shared mutable state to corrupt, even unattended 24/7.

MANY agents may work the SAME project at once: each file-editing task is given its own git worktree
(infra.worktree), so concurrent edits are isolated and merged back rather than clobbered. A real
collision becomes a merge conflict and fails that task (the planner re-sequences). A hung worker ties
up only its own slot (bounded by the agent call timeout); the others keep going.
"""
from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from typing import Callable

from control.budget import BudgetGovernor
from control.loop import RATE_LIMIT_BACKOFF_SECONDS
from core.models import AgentResult, Task
from dispatch.dispatcher import Invoke, PAConsult, is_rate_limited, is_transient, settle
from dispatch.repository import TaskRepository
from infra.notify import notify
from infra.workspace import default_projects_root, resolve_project_dir
from infra.worktree import (
    create_worktree,
    head_rev,
    integrate_worktree,
    remove_worktree,
    selfmod_fence,
)

DEFAULT_MAX_WORKERS = 8
# Task types that edit a project tree -> run in an isolated worktree. Reserved (__) projects (the
# overseer's own observe/succession) and read-only types (plan/validate) need no worktree.
_WORKTREE_TYPES = {"implement", "test", "oversee"}


def _needs_worktree(task: Task) -> bool:
    return task.task_type in _WORKTREE_TYPES and not task.project.startswith("__")


def _settle_one(fut, repo: TaskRepository, task: Task, pa_consult: PAConsult | None,
                governor: BudgetGovernor, root) -> AgentResult:
    """On the MAIN thread: collect the result, merge the task's worktree back (or fail on conflict),
    then record + charge + spawn/complete/fail. All git + state mutation is serialised here."""
    try:
        result = fut.result()
    except Exception as exc:   # an invoke that crashed instead of returning — never lose the task
        result = AgentResult(ok=False, summary="agent invoke crashed", cause=f"{type(exc).__name__}: {exc}")
    workdir = task.payload.get("workdir") if isinstance(task.payload, dict) else None
    if workdir:
        proj = resolve_project_dir(root, task.project)
        if result.ok and not integrate_worktree(proj, task.task_id):
            result = AgentResult(ok=False, summary="merge conflict",
                                 cause=f"merge conflict integrating {task.task_id} into {task.project}"
                                       " (a concurrent task changed the same lines)",
                                 metadata=result.metadata)
        remove_worktree(proj, task.task_id)
    tamper = selfmod_fence()   # L9R: the examined never edit the examiner (12 Jun incident)
    if tamper:
        result = AgentResult(
            ok=False, summary="modified orchestrator source — quarantined and reverted (L9R)",
            cause=f"L9R fence: agent write to orchestrator tree: {tamper}",
            metadata=result.metadata)
        notify("Orchestrator", f"an agent tried to modify the orchestrator's own code "
                               f"({tamper[:120]}) — reverted, quarantined, task failed")
    repo.record_result(task.task_id, result)
    governor.charge(float(result.metadata.get("cost_usd", 0.0)))
    # Burn-rate breaker input — but ONLY quality signals. A transient failure (usage/rate limit,
    # restart-kill, env fault) is quota weather, not evidence the work is bad: counting it poisons
    # the trailing window so the breaker trips the moment real work resumes after a drought
    # (8 Jul fence-storm amnesty; 14 Jul re-trip after six rate-limited hours — second occurrence,
    # so the rule moves into code). Successes always count; only transient failures are excluded.
    if result.ok or not is_transient(result):
        governor.record_outcome(result.ok)
    base_state = ""
    if not result.ok and not task.project.startswith("__"):
        try:
            base_state = head_rev(resolve_project_dir(root, task.project))   # BG-3 fingerprint base
        except Exception:
            base_state = ""
    settle(repo, task, result, pa_consult=pa_consult, base_state=base_state)
    return result


def run_concurrent(
    repo: TaskRepository,
    invoke: Invoke,
    governor: BudgetGovernor,
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    max_steps: int = 200,
    pa_consult: PAConsult | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    backoff: Callable[[], None] | None = None,
    projects_root: str | None = None,
    isolate: bool = True,
    project_cap: int = 1,
    maintenance: Callable[[], None] | None = None,
    maintenance_interval: float = 10.0,
    allowed_projects: "Callable[[], set[str] | None] | None" = None,
) -> int:
    """Drive ready tasks across up to `max_workers` concurrent agents until none are ready, max_steps
    completions, the budget/kill-switch, or should_stop. With `isolate`, each file-editing task runs in
    its own worktree, merged back on success. `project_cap` bounds concurrent agents PER project
    (default 1 = one project tree is only ever touched by one agent at a time, so intra-project merge
    conflicts can't happen; cross-project concurrency is unaffected).

    `maintenance` is the daemon's per-cycle work (ingest, prerequisite-failure cascade, overseer pulse,
    project evaluation). It is run on the MAIN thread here every `maintenance_interval` seconds DURING
    the batch — not only after it drains — so a long-running, never-idle pool can't starve the overseer
    or strand a failed prerequisite. Anything it enqueues (an overseer pulse, an improve-mode plan) is
    picked up by the very next claim, so new cycles start without waiting for all projects to finish.

    On a rate limit, finish what's in flight, back off, and end the batch. Returns the completions count."""
    backoff = backoff if backoff is not None else (lambda: time.sleep(RATE_LIMIT_BACKOFF_SECONDS))
    root = projects_root or str(default_projects_root())
    processed = 0
    rate_limited = False
    last_maint = 0.0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        inflight: dict = {}
        while processed < max_steps and not rate_limited:
            if should_stop() or governor.should_stop()[0]:
                break
            if maintenance is not None and time.monotonic() - last_maint >= maintenance_interval:
                maintenance()                            # runs DURING the batch, on a time cadence
                last_maint = time.monotonic()
            allowed = allowed_projects() if allowed_projects is not None else None   # BG-2
            while len(inflight) < max_workers:           # fill idle slots with newly-claimed work
                task = repo.claim_next(per_project_cap=project_cap, allowed_projects=allowed)
                if task is None:
                    break
                if isolate and _needs_worktree(task):
                    try:
                        wt = create_worktree(resolve_project_dir(root, task.project), task.task_id)
                        task.payload["workdir"] = str(wt)
                    except Exception:
                        pass   # isolation unavailable (e.g. no git) -> run in the project tree, ungated
                inflight[pool.submit(invoke, task)] = task
            if not inflight:
                break                                    # nothing ready and nothing running -> idle
            # Time-bounded wait so maintenance still fires while every agent is mid-call (a settle is
            # not required to make progress on the cadence above).
            done, _pending = wait(set(inflight), return_when=FIRST_COMPLETED, timeout=maintenance_interval)
            for fut in done:
                task = inflight.pop(fut)
                if is_rate_limited(_settle_one(fut, repo, task, pa_consult, governor, root)):
                    rate_limited = True
                processed += 1
        for fut in as_completed(set(inflight)):          # drain whatever is still running
            task = inflight.pop(fut)
            _settle_one(fut, repo, task, pa_consult, governor, root)
            processed += 1
    if rate_limited:
        backoff()
    return processed
