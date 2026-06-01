"""Behavioural: the Da Nang surface — durable read fold + action channels + the real entry path."""
from __future__ import annotations

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
from edge.server import _cookie_token, _lan_ip, authorised, build_state, escalations, load_or_create_token
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
