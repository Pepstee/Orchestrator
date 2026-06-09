"""control.budget — the budget governor + kill-switch (law L6: bounded autonomy).

Tracks cumulative spend durably (as events in the log, so the cap survives restarts), halts when
the cap is reached, and exposes a kill-switch sentinel an operator (or the system) can engage to
stop all dispatch immediately. No autonomous loop may run without consulting `should_stop()`.
The sentinel is written through infra.atomic_io (law L7). cap_usd <= 0 means "no cap".
"""
from __future__ import annotations

import time
from collections import deque
from pathlib import Path

from infra.atomic_io import write_json_atomic
from infra.event_store import EventStore


class BudgetGovernor:
    # Burn-rate breaker (09 hard floor): when the trailing run-success ratio collapses, paid
    # project work pauses — the June burn was 1,513 failures against 52 successes with nothing
    # sensing it. Thresholds, not CUSUM, by design (v1.3: simplest mechanism that bites).
    BURN_WINDOW = 40           # trailing runs examined
    BURN_MIN_RUNS = 20         # never judge a smaller sample
    BURN_MIN_SUCCESS = 0.4     # below this ratio => pause
    BURN_PAUSE_SECONDS = 1800.0

    def __init__(self, store: EventStore, *, cap_usd: float, kill_switch_path: Path | str) -> None:
        self._store = store
        self.cap_usd = float(cap_usd)
        self.kill_path = Path(kill_switch_path)
        self._spent = 0.0
        self._outcomes: deque[bool] = deque(maxlen=self.BURN_WINDOW)
        self._burn_paused_until = 0.0
        for e in store.replay():
            if e.kind == "spend":
                self._spent += float(e.data.get("cost", 0.0))
            elif e.kind == "burn_pause":   # the pause is durable — a restart cannot clear it
                self._burn_paused_until = max(
                    self._burn_paused_until, float(e.data.get("until", 0.0)))

    def charge(self, cost_usd: float) -> None:
        if cost_usd <= 0:
            return
        self._spent += float(cost_usd)
        self._store.append("spend", {"cost": float(cost_usd)})
        if self.exhausted():
            self.engage_kill_switch(
                f"budget exhausted: spent {self._spent:.4f} >= cap {self.cap_usd:.4f}"
            )

    def record_outcome(self, ok: bool, *, now: float | None = None) -> None:
        """Feed one run outcome into the trailing window; trip the burn breaker on collapse."""
        now = time.time() if now is None else now
        self._outcomes.append(bool(ok))
        if (len(self._outcomes) >= self.BURN_MIN_RUNS
                and sum(self._outcomes) / len(self._outcomes) < self.BURN_MIN_SUCCESS
                and now >= self._burn_paused_until):
            self._burn_paused_until = now + self.BURN_PAUSE_SECONDS
            self._outcomes.clear()   # judge a fresh window after the pause, no instant re-trip
            self._store.append("burn_pause", {"until": self._burn_paused_until, "ts": now})

    def burn_paused(self, *, now: float | None = None) -> bool:
        """While paused, the daemon parks paid project work; the overseer keeps thinking."""
        now = time.time() if now is None else now
        return now < self._burn_paused_until

    def spent(self) -> float:
        return self._spent

    def remaining(self) -> float:
        return max(0.0, self.cap_usd - self._spent) if self.cap_usd > 0 else float("inf")

    def exhausted(self) -> bool:
        return self.cap_usd > 0 and self._spent >= self.cap_usd

    def kill_switch_engaged(self) -> bool:
        return self.kill_path.exists()

    def engage_kill_switch(self, reason: str) -> None:
        write_json_atomic(self.kill_path, {"reason": reason, "ts": time.time()})

    def should_stop(self) -> tuple[bool, str]:
        if self.kill_switch_engaged():
            return True, "kill-switch engaged"
        if self.exhausted():
            return True, f"budget cap reached ({self._spent:.4f}/{self.cap_usd:.4f})"
        return False, ""
