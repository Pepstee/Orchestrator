"""L11 — the task state machine is total (every (status, event) pair defined)."""
from __future__ import annotations

from core.models import Event, TaskStatus
from core.state_machine import TRANSITIONS, transition


def test_transition_table_is_total():
    for status in TaskStatus:
        for event in Event:
            assert (status, event) in TRANSITIONS, (
                f"({status}, {event}) undefined — state machine not total (L11)"
            )
    assert len(TRANSITIONS) == len(TaskStatus) * len(Event)


def test_queued_block_is_legal():
    # The v1 fix: a dep-waiting queued task can be legally parked in blocked.
    assert transition(TaskStatus.QUEUED, Event.BLOCK) == TaskStatus.BLOCKED


def test_terminal_done_is_no_op_on_further_events():
    for event in Event:
        assert transition(TaskStatus.DONE, event) is None
