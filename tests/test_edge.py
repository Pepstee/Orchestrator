"""Behavioural: the Da Nang surface — durable read fold + action channels (no sockets needed)."""
from __future__ import annotations

from pathlib import Path

from control.confirm import request_confirmation
from control.intake import submit_goal, submit_plan
from edge.server import build_state, escalations
from infra.event_store import EventStore


def test_build_state_folds_the_da_nang_view(tmp_path: Path):
    tlog, blog = tmp_path / "tasks.log", tmp_path / "budget.log"
    s = EventStore(tlog)
    s.append("project_status", {"project": "demo", "gates": {"tests": True}, "pending_user": True})
    s.append("assurance_result", {"project": "demo", "fully_hardened": True, "reason": "fully hardened"})
    s.append("escalation", {"task_id": "t1", "cause": "compile error", "reason": "retries exhausted"})
    EventStore(blog).append("spend", {"cost": 0.25})

    st = build_state(tasks_log=tlog, budget_log=blog)
    assert st["pending"] == ["demo"]
    assert st["projects"]["demo"]["hardened"] is True
    assert st["escalations"][0]["task_id"] == "t1"
    assert st["budget"]["spent_usd"] == 0.25


def test_escalations_keeps_latest_per_task(tmp_path: Path):
    s = EventStore(tmp_path / "e.log")
    s.append("escalation", {"task_id": "t1", "cause": "x", "reason": "first"})
    s.append("escalation", {"task_id": "t1", "cause": "x", "reason": "retries exhausted"})
    out = escalations(EventStore(tmp_path / "e.log"))
    assert len(out) == 1 and out[0]["reason"] == "retries exhausted"


def test_confirm_action_drops_signal(tmp_path: Path):
    request_confirmation("demo", tmp_path)        # what POST /api/confirm calls
    assert (tmp_path / "demo.json").exists()       # daemon will ingest this on its next cycle


def test_goal_action_drops_inbox_tasks(tmp_path: Path):
    ids = submit_goal("build a thing", project="demo", inbox=str(tmp_path))  # POST /api/goal
    assert len(ids) == 2 and len(list(tmp_path.glob("*.json"))) == 2


def test_plan_action_drops_one_task(tmp_path: Path):
    submit_plan("build a thing", project="demo", inbox=str(tmp_path))   # POST /api/goal {plan:true}
    assert len(list(tmp_path.glob("*.json"))) == 1
