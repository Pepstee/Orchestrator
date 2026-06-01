"""control.budget — the budget governor + kill-switch (law L6: bounded autonomy).

Tracks cumulative spend durably (as events in the log, so the cap survives restarts), halts when
the cap is reached, and exposes a kill-switch sentinel an operator (or the system) can engage to
stop all dispatch immediately. No autonomous loop may run without consulting `should_stop()`.
The sentinel is written through infra.atomic_io (law L7). cap_usd <= 0 means "no cap".
"""
from __future__ import annotations

import time
from pathlib import Path

from infra.atomic_io import write_json_atomic
from infra.event_store import EventStore


class BudgetGovernor:
    def __init__(self, store: EventStore, *, cap_usd: float, kill_switch_path: Path | str) -> None:
        self._store = store
        self.cap_usd = float(cap_usd)
        self.kill_path = Path(kill_switch_path)
        self._spent = sum(
            float(e.data.get("cost", 0.0)) for e in store.replay() if e.kind == "spend"
        )

    def charge(self, cost_usd: float) -> None:
        if cost_usd <= 0:
            return
        self._spent += float(cost_usd)
        self._store.append("spend", {"cost": float(cost_usd)})
        if self.exhausted():
            self.engage_kill_switch(
                f"budget exhausted: spent {self._spent:.4f} >= cap {self.cap_usd:.4f}"
            )

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
