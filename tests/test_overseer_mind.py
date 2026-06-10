"""DG-8 — the overseer's mind lives on disk (the session is a cache) + BG-5 pulse health.

The June failure was not lack of persistence but its substrate: continuity rented from a
provider's opaque session store, killed silently by one malformed UUID for eleven hours.
These tests pin the replacement: a pulse WAKES with its own beliefs + journal, and WRITES BACK
before it sleeps; a wedged or dying guardian alarms instead of dying silently.
"""
from __future__ import annotations

import json

from agents.overseer import run as overseer_run
from control.daemon import OVERSEER_PROJECT, overseer_pulse_health
from core.models import Event, Task
from dispatch.repository import TaskRepository
from infra.event_store import EventStore
from infra.llm import LLMResult
from memory.overseer import (
    append_journal,
    load_beliefs,
    load_dossier,
    mind_context,
    recent_journal,
    save_beliefs,
    save_dossier,
)


def test_mind_round_trip(tmp_path):
    save_beliefs(tmp_path, "x" * 20000)
    assert len(load_beliefs(tmp_path)) == 12000           # length-capped (a bad write can't bloat)
    append_journal(tmp_path, {"mode": "observe", "note": "first"})
    append_journal(tmp_path, {"mode": "observe", "note": "second"})
    assert [e["note"] for e in recent_journal(tmp_path)] == ["first", "second"]
    save_dossier(tmp_path, "dubbing studio/x", "standing notes")   # name sanitised
    assert load_dossier(tmp_path, "dubbing studio/x") == "standing notes"
    ctx = mind_context(tmp_path)
    assert "Your beliefs" in ctx and "second" in ctx


def _observe_payload():
    return {"task": Task(task_id="o1", title="overseer observe", task_type="oversee",
                         project="__overseer__",
                         payload={"mode": "observe", "context": "2 projects idle"}).to_dict()}


def test_observe_wakes_with_mind_and_writes_back(tmp_path):
    save_beliefs(tmp_path / "overseer", "normal = one green project")
    seen = {}

    def fake_call(provider, model, prompt, **kw):
        seen["prompt"] = prompt
        return LLMResult(text=json.dumps({
            "journal": "All quiet; flagship progressing. No action needed.",
            "beliefs_update": "normal = flagship green, breaker quiet",
        }), cost_usd=0.0, model=model, session_id="s-1")

    res = overseer_run(_observe_payload(), call=fake_call, state_root=str(tmp_path))
    assert res.ok
    assert "YOUR DURABLE MIND" in seen["prompt"], "a pulse must wake with its own memory"
    assert "one green project" in seen["prompt"]
    mind = tmp_path / "overseer"
    assert recent_journal(mind)[-1]["note"].startswith("All quiet")
    assert load_beliefs(mind) == "normal = flagship green, breaker quiet"


def test_observe_without_parseable_json_still_journals(tmp_path):
    def fake_call(provider, model, prompt, **kw):
        return LLMResult(text="everything seems fine, no directives", cost_usd=0.0, model=model)

    res = overseer_run(_observe_payload(), call=fake_call, state_root=str(tmp_path))
    assert res.ok
    entries = recent_journal(tmp_path / "overseer")
    assert entries and "everything seems fine" in entries[-1]["note"], (
        "the thread of thought must have no silent gaps"
    )


def test_failed_pulse_leaves_a_trace(tmp_path):
    def boom(provider, model, prompt, **kw):
        raise RuntimeError("provider down")

    res = overseer_run(_observe_payload(), call=boom, state_root=str(tmp_path))
    assert not res.ok
    assert "pulse failed" in recent_journal(tmp_path / "overseer")[-1]["note"]


def _oversee(repo, tid):
    return repo.create(Task(task_id=tid, title="pulse", task_type="oversee",
                            project=OVERSEER_PROJECT, payload={"mode": "observe"}))


def test_pulse_health_alarms_on_wedge_once_and_clears(tmp_path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    _oversee(repo, "p1")
    _oversee(repo, "p2")
    meta, calls = {}, []
    assert overseer_pulse_health(repo, meta, notifier=lambda t, m: calls.append(m))
    assert len(calls) == 1
    overseer_pulse_health(repo, meta, notifier=lambda t, m: calls.append(m))
    assert len(calls) == 1, "alarm fires once per episode, not per cycle (the 5,384 lesson)"
    for tid in ("p1", "p2"):
        repo.apply(tid, Event.CLAIM)
        repo.apply(tid, Event.COMPLETE)
    assert not overseer_pulse_health(repo, meta, notifier=lambda t, m: calls.append(m))
    assert meta["pulse_alarm"] is False


def test_pulse_health_alarms_on_failed_streak_but_permits_self_heal(tmp_path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    for tid in ("p1", "p2"):
        _oversee(repo, tid)
        repo.apply(tid, Event.CLAIM)
        repo.apply(tid, Event.FAIL)
    meta, calls = {}, []
    wedged = overseer_pulse_health(repo, meta, notifier=lambda t, m: calls.append(m))
    assert calls, "two failed pulses must alarm"
    assert not wedged, "fresh pulses stay permitted — a new session is the self-heal"
