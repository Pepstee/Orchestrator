"""control.loop — the bounded autonomous driver (law L6).

Wraps the dispatch mechanism: run ready tasks until nothing is ready, max_steps is hit, the
budget cap is reached, or the kill-switch is engaged — whichever comes first. Every task's
reported cost is charged to the governor. This is the ONLY place tasks are driven autonomously,
and it is bounded three ways (cap + budget + kill-switch), so no run can self-amplify.
"""
from __future__ import annotations

import time
from typing import Callable

from control.budget import BudgetGovernor
from dispatch.dispatcher import Invoke, PAConsult, is_rate_limited, run_one
from dispatch.repository import TaskRepository

# When a provider usage/rate limit is hit, pause this long before ending the batch (the daemon then
# retries on its next cycle). Sized for the Claude Max window: long enough not to hammer a limited
# API, short enough to resume promptly once it resets.
RATE_LIMIT_BACKOFF_SECONDS = 300


def run(
    repo: TaskRepository,
    invoke: Invoke,
    governor: BudgetGovernor,
    max_steps: int = 1000,
    *,
    pa_consult: PAConsult | None = None,
    backoff: Callable[[], None] | None = None,
) -> int:
    """Drive ready tasks under the governor. Returns the count processed. On a provider rate/usage
    limit the task is requeued (no penalty) and we back off, then end the batch — there's no point
    hammering a limited API; the daemon retries next cycle and resumes when the window resets."""
    backoff = backoff if backoff is not None else (lambda: time.sleep(RATE_LIMIT_BACKOFF_SECONDS))
    processed = 0
    while processed < max_steps:
        stop, _reason = governor.should_stop()
        if stop:
            break
        outcome = run_one(repo, invoke, pa_consult=pa_consult)
        if outcome is None:
            break
        _task, result = outcome
        governor.charge(float(result.metadata.get("cost_usd", 0.0)))
        processed += 1
        if is_rate_limited(result):
            backoff()
            break
    return processed
