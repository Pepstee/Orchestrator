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

# When a provider usage/rate limit is hit, pause before ending the batch (the daemon then retries
# on its next cycle). Sized for the Claude Max window: long enough not to hammer a limited API,
# short enough to resume promptly once it resets.
RATE_LIMIT_BACKOFF_SECONDS = 300
# Cost-audit C-003 (16 Jul): a FLAT backoff kept re-billing full context through dead quota
# windows — refused calls still cost real money ($0.3–$11 each in cache re-creation). Consecutive
# rate-limited batches now double the pause up to this cap; any non-rate-limited batch resets it.
RATE_LIMIT_BACKOFF_CAP_SECONDS = 1800


class ExponentialBackoff:
    """Doubling sleep for consecutive rate-limit batches; reset() on recovery. Injectable sleep."""

    def __init__(self, base: float = RATE_LIMIT_BACKOFF_SECONDS,
                 cap: float = RATE_LIMIT_BACKOFF_CAP_SECONDS,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.base, self.cap, self._sleep = float(base), float(cap), sleep
        self.current = float(base)

    def __call__(self) -> None:
        self._sleep(self.current)
        self.current = min(self.current * 2, self.cap)

    def reset(self) -> None:
        self.current = self.base


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
