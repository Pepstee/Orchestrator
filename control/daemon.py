"""control.daemon — the single supervised entrypoint (law L8).

Resumes the durable task log (resume-from-step), runs ready tasks under the budget-bounded loop,
sleeps when idle, and stops gracefully on SIGTERM/SIGINT or a STOP sentinel. Exactly one instance
(pid lock); there is NO auto-restart wrapper, so a soft-stop cannot resurrect it — the precise v1
failure this avoids. Startup is quiet: nothing escalates or self-repairs on boot.

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
from control.loop import run as run_loop
from dispatch.dispatcher import Invoke
from dispatch.repository import TaskRepository
from dispatch.runner import make_subprocess_invoke
from infra import pidlock
from infra.event_store import EventStore


def serve(
    repo: TaskRepository,
    governor: BudgetGovernor,
    invoke: Invoke,
    *,
    should_stop: Callable[[], bool],
    poll_interval: float = 2.0,
    batch: int = 50,
) -> int:
    """Run ready tasks until should_stop(), sleeping when idle. Returns total tasks processed."""
    total = 0
    while not should_stop():
        processed = run_loop(repo, invoke, governor, max_steps=batch)
        total += processed
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
    governor = BudgetGovernor(
        EventStore(state / "budget.events.log"),
        cap_usd=float(os.environ.get("AGENTIC_BUDGET_USD", "10.0")),
        kill_switch_path=state / "KILL",
    )
    stop_sentinel = root / "STOP"

    def should_stop() -> bool:
        return stopped["flag"] or stop_sentinel.exists() or governor.should_stop()[0]

    try:
        serve(repo, governor, make_subprocess_invoke(), should_stop=should_stop)
    finally:
        pidlock.release(lock)


if __name__ == "__main__":
    main()
