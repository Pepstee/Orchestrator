"""Behavioural: the daemon drives the persistent overseer session — pulse, succession, reset."""
from __future__ import annotations

from pathlib import Path

from control.daemon import OVERSEER_PROJECT, tick_overseer_session
from dispatch.repository import TaskRepository
from infra.event_store import EventStore
from memory.overseer import (
    DEFAULT_RESET_INTERVAL_S,
    DEFAULT_SUCCESSION_LEAD_S,
    load_session,
)

PULSE = 3600.0


def _repo(tmp_path: Path) -> TaskRepository:
    return TaskRepository(EventStore(tmp_path / "e.log"))


def _meta_tasks(repo: TaskRepository) -> list:
    return [t for t in repo.list() if t.project == OVERSEER_PROJECT]


def test_boot_starts_session_and_opens_with_observe(tmp_path: Path):
    repo = _repo(tmp_path)
    sp, hp, meta = tmp_path / "s.json", tmp_path / "h.md", {}
    tick_overseer_session(repo, sp, hp, meta, now=0.0, pulse_interval=PULSE)
    sess = load_session(sp)
    tasks = _meta_tasks(repo)
    assert sess is not None and len(tasks) == 1
    p = tasks[0].payload
    assert p["mode"] == "observe" and p["resume"] is False     # first call CREATES the session
    assert p["session_id"] == sess.session_id


def test_fresh_session_is_seeded_from_handoff(tmp_path: Path):
    repo = _repo(tmp_path)
    sp, hp, meta = tmp_path / "s.json", tmp_path / "h.md", {}
    hp.write_text("STATE: deal-sniper passing; WIP: situation-monitor dashboard", encoding="utf-8")
    tick_overseer_session(repo, sp, hp, meta, now=0.0, pulse_interval=PULSE)
    ctx = _meta_tasks(repo)[0].payload["context"]
    assert "Handoff from your previous session" in ctx and "deal-sniper passing" in ctx


def test_pulse_only_after_interval(tmp_path: Path):
    repo = _repo(tmp_path)
    sp, hp, meta = tmp_path / "s.json", tmp_path / "h.md", {}
    tick_overseer_session(repo, sp, hp, meta, now=0.0, pulse_interval=PULSE)        # boot observe
    tick_overseer_session(repo, sp, hp, meta, now=PULSE - 1, pulse_interval=PULSE)  # too soon
    assert len(_meta_tasks(repo)) == 1
    tick_overseer_session(repo, sp, hp, meta, now=PULSE + 1, pulse_interval=PULSE)  # due
    obs = [t for t in _meta_tasks(repo) if t.payload["mode"] == "observe"]
    assert len(obs) == 2 and obs[-1].payload["resume"] is True   # established session -> resume


def test_succession_enqueued_once_within_lead(tmp_path: Path):
    repo = _repo(tmp_path)
    sp, hp, meta = tmp_path / "s.json", tmp_path / "h.md", {}
    tick_overseer_session(repo, sp, hp, meta, now=0.0, pulse_interval=PULSE)
    t_succ = DEFAULT_RESET_INTERVAL_S - DEFAULT_SUCCESSION_LEAD_S
    tick_overseer_session(repo, sp, hp, meta, now=t_succ, pulse_interval=PULSE)
    tick_overseer_session(repo, sp, hp, meta, now=t_succ + PULSE + 1, pulse_interval=PULSE)  # still in lead
    succ = [t for t in _meta_tasks(repo) if t.payload["mode"] == "succession"]
    assert len(succ) == 1 and succ[0].payload["resume"] is True   # not duplicated


def test_reset_rotates_to_a_new_session(tmp_path: Path):
    repo = _repo(tmp_path)
    sp, hp, meta = tmp_path / "s.json", tmp_path / "h.md", {}
    tick_overseer_session(repo, sp, hp, meta, now=0.0, pulse_interval=PULSE)
    first = load_session(sp).session_id
    tick_overseer_session(repo, sp, hp, meta, now=DEFAULT_RESET_INTERVAL_S + 1, pulse_interval=PULSE)
    second = load_session(sp).session_id
    assert second != first                                        # genuinely fresh session
    last = _meta_tasks(repo)[-1].payload
    assert last["mode"] == "observe" and last["resume"] is False and last["session_id"] == second
