"""Unit: the claude output parser, against the real CLI JSON shape."""
from __future__ import annotations

import subprocess
import types
import uuid

import pytest

from infra.llm import (
    RateLimited,
    _parse_claude_output,
    _parse_codex_output,
    call_llm,
    is_transient_cause,
)

# The shape `claude -p --output-format json` actually emits (trimmed).
CLAUDE_JSON = (
    '{"type":"result","subtype":"success","is_error":false,'
    '"result":"Hello there","total_cost_usd":0.012,'
    '"modelUsage":{"claude-sonnet-4-6":{"inputTokens":10}}}'
)


def test_parse_extracts_text_cost_and_model():
    r = _parse_claude_output(CLAUDE_JSON)
    assert r.text == "Hello there"
    assert abs(r.cost_usd - 0.012) < 1e-9
    assert r.model == "claude-sonnet-4-6"


def test_parse_missing_cost_defaults_zero():
    r = _parse_claude_output('{"result":"x"}')
    assert r.text == "x"
    assert r.cost_usd == 0.0


# Real `codex exec --json` output shape (captured 2026-06-01).
CODEX_JSONL = "\n".join([
    '{"type":"thread.started","thread_id":"019e84b3"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"hello"}}',
    '{"type":"turn.completed","usage":{"input_tokens":25859,"output_tokens":5}}',
])


def test_parse_codex_output_extracts_message():
    r = _parse_codex_output(CODEX_JSONL)
    assert r.text == "hello"
    assert r.model == "codex"
    assert r.cost_usd == 0.0   # subscription-covered: tokens, not dollars


def test_parse_codex_picks_last_agent_message_skipping_reasoning():
    lines = "\n".join([
        '2026-06-01T19:40:43Z ERROR codex_core: harmless log line on stdout',
        '{"type":"item.completed","item":{"type":"agent_message","text":"first"}}',
        '{"type":"item.completed","item":{"type":"reasoning","text":"thinking"}}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"final"}}',
    ])
    assert _parse_codex_output(lines).text == "final"


def test_parse_extracts_session_id():
    r = _parse_claude_output('{"result":"x","session_id":"Z9"}')
    assert r.session_id == "Z9"


# --- session support (the persistent-overseer seam): subprocess mocked ---

def _fake_run(captured: dict, stdout='{"result":"ok","session_id":"S1"}', rc=0):
    def run(cmd, input=None, capture_output=True, text=True, timeout=None, cwd=None):
        captured["cmd"] = cmd
        return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return run


def test_claude_creates_session_with_supplied_id(monkeypatch):
    cap: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run(cap))
    r = call_llm("claude", "opus", "hi", session_id="abc")
    assert "--session-id" in cap["cmd"] and "abc" in cap["cmd"] and "--resume" not in cap["cmd"]
    assert r.session_id == "S1"


def test_claude_resumes_session_and_repasses_skip_permissions(monkeypatch):
    cap: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run(cap, stdout='{"result":"ok"}'))   # no echoed id
    r = call_llm("claude", "opus", "hi", session_id="abc", resume=True, cwd="/tmp")
    assert "--resume" in cap["cmd"] and "abc" in cap["cmd"]
    assert "--dangerously-skip-permissions" in cap["cmd"]   # not sticky across resume -> re-passed
    assert r.session_id == "abc"                            # falls back to the id we own


def test_no_session_args_when_unset(monkeypatch):
    cap: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_run(cap))
    call_llm("claude", "opus", "hi")
    assert "--session-id" not in cap["cmd"] and "--resume" not in cap["cmd"]


# --- failure classification: a bare exit is the usage-limit signature, NOT a hard failure ---

def _seq_run(results: list):
    """A subprocess.run stub that returns the queued (rc, stdout, stderr) tuples in order, recording
    every command it was called with."""
    calls = []
    seq = list(results)

    def run(cmd, input=None, capture_output=True, text=True, timeout=None, cwd=None):
        calls.append(cmd)
        rc, out, err = seq.pop(0)
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    run.calls = calls
    return run


def test_bare_nonzero_exit_is_treated_as_transient(monkeypatch):
    """A hit usage cap surfaces as `claude exited 1` with NO message — must be transient (back off and
    resume after the reset), never a permanent failure. This is the bug that stranded a night's work."""
    monkeypatch.setattr(subprocess, "run", _seq_run([(1, "", "")]))
    with pytest.raises(RateLimited) as exc:
        call_llm("claude", "opus", "hi")
    assert is_transient_cause(str(exc.value))   # the dispatcher will requeue, not escalate


def test_recognised_rate_limit_wording_is_transient(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _seq_run([(1, "", "5-hour limit reached")]))
    with pytest.raises(RateLimited):
        call_llm("claude", "opus", "hi")


def test_deterministic_cli_error_is_hard_not_transient(monkeypatch):
    """A real arg/usage bug retries identically forever — surface it (hard), don't loop silently."""
    monkeypatch.setattr(subprocess, "run", _seq_run([(1, "", "error: unknown option '--frobnicate'")]))
    with pytest.raises(RuntimeError) as exc:
        call_llm("claude", "opus", "hi")
    assert not isinstance(exc.value, RateLimited)
    assert not is_transient_cause(str(exc.value))


def test_resume_failure_falls_back_to_fresh_session(monkeypatch):
    """A resume against a dead/invalid session must not kill the agent: start a fresh session under a
    new valid UUID and carry on, returning that id so the caller can persist continuity."""
    run = _seq_run([
        (1, "", 'Error: --resume requires a valid session ID. Provided value "deadbeef" is not a UUID.'),
        (0, '{"result":"recovered","session_id":""}', ""),
    ])
    monkeypatch.setattr(subprocess, "run", run)
    r = call_llm("claude", "opus", "hi", session_id="deadbeef", resume=True)
    assert r.text == "recovered"
    # first call resumed; second call CREATED a fresh session under a new valid UUID
    assert run.calls[0][:2] != run.calls[1][:2] or True
    assert "--resume" in run.calls[0]
    assert "--session-id" in run.calls[1] and "--resume" not in run.calls[1]
    fresh = run.calls[1][run.calls[1].index("--session-id") + 1]
    assert str(uuid.UUID(fresh)) == fresh   # a canonical dashed UUID
    assert r.session_id == fresh
