"""Behavioural: the Da Nang surface — durable read fold + action channels + the real entry path."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from control.confirm import request_confirmation
from control.intake import submit_goal, submit_plan
from edge.server import (
    _cookie_token,
    _lan_ip,
    activity,
    authorised,
    build_state,
    escalations,
    health,
    load_or_create_token,
)
from infra.event_store import EventStore

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_escalation_clears_once_the_project_is_instructed(tmp_path: Path):
    """The 'never disappears' bug: instructing a project (a later oversee task) must drop its
    escalation from the tray — otherwise the card lingers forever after you've acted."""
    s = EventStore(tmp_path / "e.log")
    s.append("task_created", {"task": {"task_id": "b1", "project": "demo",
                                       "task_type": "implement", "status": "failed"}})
    s.append("escalation", {"task_id": "b1", "project": "demo", "cause": "boom", "reason": "stuck"})
    assert any(e["task_id"] == "b1" for e in escalations(s))          # shown while unaddressed
    s.append("task_created", {"task": {"task_id": "o1", "project": "demo",
                                       "task_type": "oversee", "status": "queued"}})
    assert not any(e["task_id"] == "b1" for e in escalations(s))      # cleared once instructed


def test_reserved_project_escalations_are_not_in_the_tray(tmp_path: Path):
    """The overseer's own plumbing failures (__overseer__) are diagnostics for the feed, not user
    decisions — they must never clutter the 'needs you' tray."""
    s = EventStore(tmp_path / "e.log")
    s.append("escalation", {"task_id": "o1", "project": "__overseer__", "reason": "retries exhausted",
                            "cause": "claude exited 1: Invalid session ID"})
    s.append("escalation", {"task_id": "r1", "project": "deal-sniper-v3", "reason": "retries exhausted",
                            "cause": "repository is empty"})
    shown = {e["task_id"] for e in escalations(s)}
    assert shown == {"r1"}                       # the real project escalation stays; the meta one is hidden


def test_transient_cause_escalations_are_never_shown(tmp_path: Path):
    """A restart-kill (KeyboardInterrupt) or rate-limit escalation is never a real defect — it must
    not appear in the tray, even from the historical backlog before the fix."""
    s = EventStore(tmp_path / "e.log")
    s.append("escalation", {"task_id": "k1", "project": "demo", "reason": "pa:escalate",
                            "cause": "Traceback ... selectors.py ... KeyboardInterrupt"})
    s.append("escalation", {"task_id": "r1", "project": "demo", "reason": "pa:escalate",
                            "cause": "claude: 5-hour limit reached"})
    s.append("escalation", {"task_id": "real", "project": "demo", "reason": "stuck",
                            "cause": "AssertionError: expected 5 got 4"})
    shown = {e["task_id"] for e in escalations(s)}
    assert shown == {"real"}                          # only the genuine defect remains


def test_activity_feed_is_readable_newest_first(tmp_path: Path):
    s = EventStore(tmp_path / "e.log")
    s.append("task_created", {"task": {"task_id": "v1", "project": "demo", "task_type": "validate"}})
    s.append("task_created", {"task": {"task_id": "o1", "project": "demo", "task_type": "oversee"}})
    s.append("task_result", {"task_id": "v1", "ok": True, "summary": "judge verdict: pass (0.8)"})
    s.append("task_result", {"task_id": "o1", "ok": True, "summary": "fixed the failing import"})
    s.append("project_confirmed", {"project": "demo"})
    feed = activity(s)
    texts = [a["text"] for a in feed]
    assert texts[0].startswith("you confirmed — demo")          # newest first
    assert any("overseer — fixed the failing import" in t for t in texts)
    assert any("judge — judge verdict: pass" in t for t in texts)
    assert all("ts" in a for a in feed)                          # timestamped


def test_activity_omits_transient_failures(tmp_path: Path):
    s = EventStore(tmp_path / "e.log")
    s.append("task_created", {"task": {"task_id": "b1", "project": "p", "task_type": "implement"}})
    s.append("task_result", {"task_id": "b1", "ok": False, "summary": "killed",
                             "cause": "Traceback ... KeyboardInterrupt"})
    assert activity(s) == []                                     # restart-kill noise excluded


def test_project_overview_shows_in_flight_projects(tmp_path: Path):
    """In-flight projects must appear with live counts — not 'No projects yet' until they drain."""
    from edge.server import project_overview
    s = EventStore(tmp_path / "e.log")
    s.append("task_created", {"task": {"task_id": "a", "project": "edge", "task_type": "implement"}})
    s.append("task_transition", {"task_id": "a", "to": "in_progress"})
    s.append("task_created", {"task": {"task_id": "b", "project": "edge", "task_type": "test"}})
    s.append("task_created", {"task": {"task_id": "m", "project": "__overseer__", "task_type": "oversee"}})
    ov = project_overview(s)
    assert "edge" in ov and "__overseer__" not in ov          # real project shown, meta hidden
    assert ov["edge"]["running"] == 1 and ov["edge"]["queued"] == 1


def test_health_reports_liveness_and_counts(tmp_path: Path):
    log = tmp_path / "e.log"
    s = EventStore(log)
    s.append("task_created", {"task": {"task_id": "a", "project": "p",
                                       "task_type": "implement", "status": "queued"}})
    s.append("task_transition", {"task_id": "a", "to": "in_progress"})
    h = health(log)
    assert h["running"] == 1 and h["queued"] == 0
    assert h["alive"] is True and h["last_activity_s"] is not None
    assert h["status"] == "working"          # a task in progress is WORKING, never 'stopped'


def test_health_distinguishes_stalled_from_idle(tmp_path: Path):
    # work queued but nothing running and quiet for >2min -> 'stalled?' (the daemon likely died)
    stalled = tmp_path / "stalled.log"
    s = EventStore(stalled)
    s.append("task_created", {"task": {"task_id": "q", "project": "p",
                                       "task_type": "implement", "status": "queued"}})
    old = time.time() - 300
    os.utime(stalled, (old, old))
    assert health(stalled)["status"] == "stalled?"

    # nothing queued, nothing running, quiet -> just 'idle' (nothing to do, not broken)
    idle = tmp_path / "idle.log"
    s2 = EventStore(idle)
    s2.append("task_created", {"task": {"task_id": "d", "project": "p",
                                        "task_type": "implement", "status": "queued"}})
    s2.append("task_transition", {"task_id": "d", "to": "done"})
    os.utime(idle, (old, old))
    assert health(idle)["status"] == "idle"


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


def test_instruct_enqueues_an_oversee_task(tmp_path: Path):
    from control.enqueue import enqueue                                  # what POST /api/instruct calls
    enqueue("fix the import", task_type="oversee", project="demo",
            payload={"context": "ImportError"}, inbox=str(tmp_path))
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["task_type"] == "oversee" and data["project"] == "demo"
    assert data["payload"]["context"] == "ImportError"


def test_escalations_carry_project(tmp_path: Path):
    s = EventStore(tmp_path / "e.log")
    s.append("escalation", {"task_id": "t1", "cause": "boom", "reason": "pa:escalate", "project": "roman"})
    out = escalations(EventStore(tmp_path / "e.log"))
    assert out[0]["project"] == "roman"   # the overseer needs this to know which project to act on


def test_escalation_cleared_when_project_confirmed(tmp_path: Path):
    s = EventStore(tmp_path / "e.log")
    s.append("task_created", {"task": {"task_id": "v1", "project": "roman", "task_type": "validate"}})
    s.append("task_transition", {"task_id": "v1", "from": "in_progress", "to": "failed", "event": "fail"})
    s.append("escalation", {"task_id": "v1", "cause": "127", "reason": "retries exhausted", "project": "roman"})
    s.append("project_confirmed", {"project": "roman"})
    assert escalations(EventStore(tmp_path / "e.log")) == []   # project done -> escalation resolved


def test_escalation_cleared_when_retry_supersedes(tmp_path: Path):
    s = EventStore(tmp_path / "e.log")
    s.append("task_created", {"task": {"task_id": "v1", "project": "p", "task_type": "validate"}})
    s.append("task_transition", {"task_id": "v1", "from": "in_progress", "to": "failed", "event": "fail"})
    s.append("escalation", {"task_id": "v1", "cause": "boom", "reason": "retries exhausted", "project": "p"})
    s.append("task_created", {"task": {"task_id": "v2", "project": "p", "task_type": "validate"}})
    s.append("task_transition", {"task_id": "v2", "from": "in_progress", "to": "done", "event": "complete"})
    assert escalations(EventStore(tmp_path / "e.log")) == []   # a later passing validate supersedes it


def test_escalation_kept_while_genuinely_open(tmp_path: Path):
    s = EventStore(tmp_path / "e.log")
    s.append("task_created", {"task": {"task_id": "x", "project": "p", "task_type": "validate"}})
    s.append("task_transition", {"task_id": "x", "from": "in_progress", "to": "failed", "event": "fail"})
    s.append("escalation", {"task_id": "x", "cause": "boom", "reason": "retries exhausted", "project": "p"})
    out = escalations(EventStore(tmp_path / "e.log"))
    assert len(out) == 1 and out[0]["task_id"] == "x"   # unresolved -> still needs the user


def test_authorised_accepts_any_valid_source_and_fails_closed():
    assert authorised("sek", auth_header="sek")
    assert authorised("sek", query_token="sek")
    assert authorised("sek", cookie_header="a=1; gui_token=sek; b=2")
    assert not authorised("sek", auth_header="wrong")
    assert not authorised("sek")                       # no credential at all
    assert not authorised("", query_token="anything")  # unconfigured -> deny


def test_cookie_token_parsing():
    assert _cookie_token("a=1; gui_token=xyz; b=2") == "xyz"
    assert _cookie_token("") is None
    assert _cookie_token("nope=1") is None


def test_token_is_created_once_and_stable(tmp_path: Path):
    first = load_or_create_token(tmp_path)
    second = load_or_create_token(tmp_path)
    assert first and first == second and (tmp_path / "gui_token.json").exists()


def test_lan_ip_returns_a_usable_address():
    ip = _lan_ip()                                  # never 0.0.0.0 (that's unreachable from a phone)
    assert isinstance(ip, str) and ip and ip != "0.0.0.0"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_entrypoint_serves_the_page(tmp_path: Path):
    """Run the REAL entry path (python -m edge.server) and GET '/'. Catches module-ordering bugs
    (e.g. _PAGE defined after the __main__ guard) that importing the module masks."""
    port = _free_port()
    env = {**os.environ, "AGENTIC_GUI_HOST": "127.0.0.1", "AGENTIC_GUI_PORT": str(port),
           "AGENTIC_GUI_TOKEN": "t0k", "PYTHONPATH": str(REPO_ROOT)}
    proc = subprocess.Popen([sys.executable, "-m", "edge.server"], cwd=str(REPO_ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        code, body = None, ""
        for _ in range(50):
            try:
                resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/?token=t0k", timeout=1)
                code, body = resp.status, resp.read().decode()
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.1)
        assert code == 200 and "<title>Orchestrator" in body
    finally:
        proc.terminate()
        proc.wait(timeout=5)
