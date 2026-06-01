"""Behavioural: the real agent subprocess contract (stdin payload -> one AgentResult line)."""
from __future__ import annotations

import sys
from pathlib import Path

from dispatch.runner import parse_agent_output, run_subprocess_agent


def test_parse_picks_last_agentresult_line():
    out = 'some log line\n{"ok": true, "summary": "hi"}\n'
    r = parse_agent_output(out)
    assert r.ok and r.summary == "hi"


def test_parse_unparseable_yields_cause():
    r = parse_agent_output("garbage not json\n")
    assert not r.ok and r.cause


def test_subprocess_roundtrip(tmp_path: Path):
    stub = tmp_path / "stub_agent.py"
    stub.write_text(
        "import sys, json\n"
        "json.loads(sys.stdin.read())\n"
        "print(json.dumps({'ok': True, 'summary': 'stub did it'}))\n",
        encoding="utf-8",
    )
    r = run_subprocess_agent([sys.executable, str(stub)], {"task": {"task_id": "t1"}})
    assert r.ok and r.summary == "stub did it"


def test_subprocess_unparseable_yields_cause(tmp_path: Path):
    stub = tmp_path / "bad_agent.py"
    stub.write_text("print('not json at all')\n", encoding="utf-8")
    r = run_subprocess_agent([sys.executable, str(stub)], {})
    assert not r.ok and r.cause
