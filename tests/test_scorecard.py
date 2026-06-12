"""The scorecard is deterministic fold over the durable logs (09 §7; A2's measurement floor)."""
from __future__ import annotations

from control.scorecard import render, summarise


def _ev(seq, ts, kind, data):
    return {"seq": seq, "ts": ts, "kind": kind, "data": data}


def _world():
    return [
        _ev(1, 100, "task_created", {"task": {"task_id": "a", "task_type": "implement",
                                              "project": "alpha", "title": "build"}}),
        _ev(2, 110, "task_transition", {"task_id": "a", "event": "claim", "from": "queued", "to": "in_progress"}),
        _ev(3, 710, "task_result", {"task_id": "a", "ok": True, "summary": "done"}),
        _ev(4, 720, "task_transition", {"task_id": "a", "event": "claim", "from": "queued", "to": "in_progress"}),
        _ev(5, 800, "task_result", {"task_id": "a", "ok": False, "cause": "merge conflict integrating a into alpha"}),
        _ev(6, 801, "task_transition", {"task_id": "a", "event": "requeue", "from": "in_progress", "to": "queued"}),
        _ev(7, 900, "escalation", {"task_id": "a", "reason": "identical re-attempt refused (BG-3): x", "cause": "y"}),
        _ev(8, 950, "project_status", {"project": "alpha", "gates": {"tests": True, "acceptance": False,
                                                                     "judge": True, "authenticity": True}}),
        _ev(9, 960, "assurance_result", {"project": "alpha", "fully_hardened": False, "reason": "issue at mutation"}),
        _ev(10, 970, "project_confirmed", {"project": "alpha"}),
    ]


def test_summarise_counts_everything():
    s = summarise(_world(), [_ev(1, 500, "burn_pause", {"until": 999})])
    assert s["runs"] == 2 and s["ok"] == 1 and s["fail"] == 1
    assert s["success_ratio"] == 0.5
    assert abs(s["agent_hours"] - (600 + 80) / 3600) < 1e-6, "claim->result wall-clock paired per attempt"
    assert s["requeues"] == 1 and s["bg3_refusals"] == 1 and s["breaker_trips"] == 1
    assert s["gates"]["alpha"]["judge"] is True
    assert s["confirmations"] == ["alpha"] and s["runs_per_certification"] == 2.0


def test_since_filter_and_render():
    s = summarise(_world(), [], since_ts=10_000)
    assert s["runs"] == 0 and s["success_ratio"] is None
    full = summarise(_world(), [])
    out = render(full, {"alpha": 3})
    assert "SCORECARD" in out and "alpha" in out and "merges   3" in out
    assert "gates[+-++]" in out, "gate string encodes tests/acceptance/judge/authenticity"
    assert "certifications: 1" in out
