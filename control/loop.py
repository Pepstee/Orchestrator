"""control.loop — the bounded autonomous driver (law L6).

Wraps the dispatch mechanism: run ready tasks until nothing is ready, max_steps is hit, the
budget cap is reached, or the kill-switch is engaged — whichever comes first. Every task's
reported cost is charged to the governor. This is the ONLY place tasks are driven autonomously,
and it is bounded three ways (cap + budget + kill-switch), so no run can self-amplify.
"""
from __future__ import annotations

from control.budget import BudgetGovernor
from dispatch.dispatcher import Invoke, run_one
from dispatch.repository import TaskRepository


def run(
    repo: TaskRepository,
    invoke: Invoke,
    governor: BudgetGovernor,
    max_steps: int = 1000,
) -> int:
    """Drive ready tasks under the governor. Returns the count processed."""
    processed = 0
    while processed < max_steps:
        stop, _reason = governor.should_stop()
        if stop:
            break
        outcome = run_one(repo, invoke)
        if outcome is None:
            break
        _task, result = outcome
        governor.charge(float(result.metadata.get("cost_usd", 0.0)))
        processed += 1
    return processed
