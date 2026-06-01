"""core.state_machine — the TOTAL task state machine (law L11).

Every (status, event) pair is defined. Illegal/irrelevant pairs map to None (no-op) rather
than raising an "invalid transition" — this is the structural fix for v1's `queued -> blocked`
spam, where a dep-waiting task could not be parked legally. Here `QUEUED + BLOCK -> BLOCKED`
is a first-class legal transition.
"""
from __future__ import annotations

from core.models import Event, TaskStatus

# The legal transitions. Everything not listed is a no-op (None), filled in below so the
# table is exhaustive over the full (status x event) product.
_LEGAL: dict[tuple[TaskStatus, Event], TaskStatus] = {
    (TaskStatus.QUEUED,      Event.CLAIM):    TaskStatus.IN_PROGRESS,
    (TaskStatus.QUEUED,      Event.BLOCK):    TaskStatus.BLOCKED,      # dep not ready (legal!)
    (TaskStatus.IN_PROGRESS, Event.COMPLETE): TaskStatus.DONE,
    (TaskStatus.IN_PROGRESS, Event.FAIL):     TaskStatus.FAILED,
    (TaskStatus.IN_PROGRESS, Event.BLOCK):    TaskStatus.BLOCKED,
    (TaskStatus.IN_PROGRESS, Event.REQUEUE):  TaskStatus.QUEUED,      # transient retry
    (TaskStatus.IN_PROGRESS, Event.RECLAIM):  TaskStatus.QUEUED,      # stale reclaim
    (TaskStatus.BLOCKED,     Event.UNBLOCK):  TaskStatus.QUEUED,
    (TaskStatus.BLOCKED,     Event.FAIL):     TaskStatus.FAILED,      # prerequisite cascade
    (TaskStatus.FAILED,      Event.REQUEUE):  TaskStatus.QUEUED,      # manual/auto retry
}

# Exhaustive table over the full product; absent legal pairs -> None (no-op).
TRANSITIONS: dict[tuple[TaskStatus, Event], TaskStatus | None] = {
    (status, event): _LEGAL.get((status, event))
    for status in TaskStatus
    for event in Event
}


def transition(status: TaskStatus, event: Event) -> TaskStatus | None:
    """Return the new status, or None for a no-op. Total: never raises on any defined pair."""
    return TRANSITIONS[(status, event)]
