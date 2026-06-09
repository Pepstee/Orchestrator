"""core.models — pure domain types. Defined ONCE (law L1). Stdlib only (no IO, no imports outward).

This is the canonical home of AgentResult and Task — unifying v1's two diverged AgentResult
definitions into a single type that carries the union of fields (including `cause` for
self-explaining failures, law L10, and `intent` for agent communicative intent).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


class Event(str, Enum):
    """The events that drive task state transitions (see core.state_machine)."""
    CLAIM = "claim"
    COMPLETE = "complete"
    FAIL = "fail"
    BLOCK = "block"
    UNBLOCK = "unblock"
    REQUEUE = "requeue"
    RECLAIM = "reclaim"


@dataclass
class AgentResult:
    """The single agent contract: payload in -> exactly one AgentResult out."""
    ok: bool
    summary: str
    artifacts: list[str] = field(default_factory=list)
    spawned_tasks: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    block_reason: str | None = None
    cause: str | None = None          # L10: a failed result MUST explain why
    intent: str = "inform_complete"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AgentResult":
        known = {f for f in AgentResult.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        if "ok" in filtered:
            filtered["ok"] = bool(filtered["ok"])  # normalise truthy strings/ints
        return AgentResult(**filtered)


@dataclass
class Task:
    """A unit of work. Project (Global Task) completion is gated by the 4-gate contract;
    individual tasks complete autonomously."""
    task_id: str
    title: str
    task_type: str
    status: TaskStatus = TaskStatus.QUEUED
    depends_on: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    acceptance_criteria: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    retries: int = 0
    max_retries: int = 3
    parent_task_id: str | None = None
    project: str = "default"          # which project tree under projects/ this builds into
    priority: int = 0                 # higher runs first among ready tasks (set by the overseer)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Task":
        known = {f for f in Task.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        if "status" in filtered and not isinstance(filtered["status"], TaskStatus):
            filtered["status"] = TaskStatus(filtered["status"])
        return Task(**filtered)
