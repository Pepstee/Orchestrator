"""Unit + lifecycle: the local pre-screen in front of overseer observe pulses.
The contract under test: only a well-formed QUIET skips a pulse — everything else fails open."""
from __future__ import annotations

from pathlib import Path

from control.daemon import OVERSEER_PROJECT, tick_overseer_session
from control.prescreen import prescreen_pulse
from dispatch.repository import TaskRepository
from infra.event_store import EventStore
from infra.llm import LLMResult

PULSE = 3600.0


def _r(text: str) -> LLMResult:
    return LLMResult(text=text, cost_usd=0.0, model="qwen-test")


def _repo(tmp_path: Path) -> TaskRepository:
    return TaskRepository(EventStore(tmp_path / "e.log"))


def _metas(repo):
    return [t for t in repo.list() if t.project == OVERSEER_PROJECT]


def test_quiet_skips():
    wake, note = prescreen_pulse("all idle", call=lambda *a, **k: _r("QUIET\nnothing moving"))
    assert wake is False and "nothing moving" in note


def test_wake_forwards_briefing():
    wake, note = prescreen_pulse("t9 failed", call=lambda *a, **k: _r("WAKE\ntask t9 stuck 3h"))
    assert wake is True and "t9" in note


def test_garbage_fails_open():
    wake, _ = prescreen_pulse("x", call=lambda *a, **k: _r("hmm, probably fine?"))
    assert wake is True


def test_exception_fails_open():
    def boom(*a, **k):
        raise ConnectionError("refused")
    wake, note = prescreen_pulse("x", call=boom)
    assert wake is True and "unavailable" in note


def test_real_path_is_hermetic_under_pytest():
    wake, note = prescreen_pulse("x")        # default call path: must never touch a network
    assert wake is True and "pytest" in note


def test_tick_quiet_skips_enqueue_but_keeps_cadence(tmp_path: Path):
    repo = _repo(tmp_path)
    sp, hp, meta = tmp_path / "s.json", tmp_path / "h.md", {}
    tick_overseer_session(repo, sp, hp, meta, now=0.0, pulse_interval=PULSE)   # boot observe
    assert len(_metas(repo)) == 1
    tick_overseer_session(repo, sp, hp, meta, now=PULSE + 1, pulse_interval=PULSE,
                          prescreen=lambda ctx: (False, "quiet hour"))
    assert len(_metas(repo)) == 1                        # skipped: no cloud turn spent
    assert meta["screened_quiet"] == ["quiet hour"]
    assert meta["last_pulse"] == PULSE + 1               # cadence advanced - no pulse pile-up
    tick_overseer_session(repo, sp, hp, meta, now=2 * PULSE + 2, pulse_interval=PULSE,
                          prescreen=lambda ctx: (True, "task t1 failed twice"))
    obs = [t for t in _metas(repo) if t.payload["mode"] == "observe"]
    assert len(obs) == 2
    ctx = obs[-1].payload["context"]
    assert "Screened-quiet pulses since your last turn (1)" in ctx and "quiet hour" in ctx
    assert "task t1 failed twice" in ctx
    assert "screened_quiet" not in meta                  # handed over and cleared
