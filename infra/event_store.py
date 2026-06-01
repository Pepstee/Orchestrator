"""infra.event_store — append-only, replayable event log (the durable spine).

Every state change is recorded as an event; current state is reconstructed by folding the log
(resume-from-step, never restart from zero — the guarantee v1 lacked). All writes go through
infra.atomic_io (law L7); reads tolerate a truncated final line (crash safety).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from infra.atomic_io import append_jsonl, read_jsonl


@dataclass
class LogEvent:
    seq: int
    ts: float
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


class EventStore:
    """An append-only log file. Monotonic seq per record; replay folds the log into state."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._seq = self._last_seq()

    def _last_seq(self) -> int:
        last = -1
        for rec in read_jsonl(self.path):
            s = rec.get("seq", -1)
            if isinstance(s, int) and s > last:
                last = s
        return last

    def append(self, kind: str, data: dict[str, Any] | None = None) -> LogEvent:
        self._seq += 1
        ev = LogEvent(seq=self._seq, ts=time.time(), kind=kind, data=data or {})
        append_jsonl(self.path, {"seq": ev.seq, "ts": ev.ts, "kind": ev.kind, "data": ev.data})
        return ev

    def replay(self) -> Iterator[LogEvent]:
        for rec in read_jsonl(self.path):
            yield LogEvent(
                seq=rec["seq"], ts=rec["ts"], kind=rec["kind"], data=rec.get("data", {})
            )
