"""Behavioural: the event store appends, replays in order, survives restart, tolerates a crash."""
from __future__ import annotations

from pathlib import Path

from infra.event_store import EventStore


def test_append_and_replay_in_order(tmp_path: Path):
    s = EventStore(tmp_path / "events.log")
    s.append("a", {"x": 1})
    s.append("b", {"x": 2})
    evs = list(s.replay())
    assert [e.kind for e in evs] == ["a", "b"]
    assert [e.seq for e in evs] == [0, 1]
    assert evs[1].data == {"x": 2}


def test_survives_restart(tmp_path: Path):
    p = tmp_path / "events.log"
    EventStore(p).append("a", {})
    s2 = EventStore(p)  # "restart" over the same file — seq must continue, not reset
    s2.append("b", {})
    assert [e.kind for e in s2.replay()] == ["a", "b"]
    assert [e.seq for e in s2.replay()] == [0, 1]


def test_tolerates_truncated_final_line(tmp_path: Path):
    p = tmp_path / "events.log"
    s = EventStore(p)
    s.append("a", {})
    # simulate a crash mid-append: a partial, invalid-JSON final line
    with open(p, "a", encoding="utf-8") as fh:
        fh.write('{"seq": 1, "ts": 0, "kind": "b"')  # no closing brace, no newline
    evs = list(s.replay())
    assert [e.kind for e in evs] == ["a"]  # the partial line is skipped, not fatal
