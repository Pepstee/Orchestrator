"""Unit: the ollama provider — parser, request shape, failure classification — plus the
capability law: ollama is TEXT-ONLY (no file tools, no sessions), so the file-writing roles
(builder, tester) keep a tool-capable provider and the overseer keeps the session-capable one."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

import infra.llm as llm
from infra.llm import RateLimited, _parse_ollama_output, call_llm, is_transient_cause
from registry.agents import AGENT_MODELS

OLLAMA_JSON = json.dumps({
    "model": "qwen2.5-coder:7b",
    "message": {"role": "assistant", "content": "hello from the gpu"},
    "done": True,
})


class _FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_parse_extracts_text_and_model():
    r = _parse_ollama_output(OLLAMA_JSON)
    assert r.text == "hello from the gpu"
    assert r.model == "qwen2.5-coder:7b"
    assert r.cost_usd == 0.0   # house GPU: zero marginal cost


def test_request_carries_system_model_and_loopback(monkeypatch):
    cap: dict = {}

    def fake_urlopen(req, timeout=None):
        cap["url"] = req.full_url
        cap["body"] = json.loads(req.data.decode())
        cap["timeout"] = timeout
        return _FakeResponse(OLLAMA_JSON)

    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(llm, "urlopen", fake_urlopen)
    r = call_llm("ollama", "qwen2.5-coder:7b", "hi", system="be brief")
    assert cap["url"] == "http://127.0.0.1:11434/api/chat"   # loopback by default, never public
    assert cap["body"]["model"] == "qwen2.5-coder:7b"
    assert cap["body"]["stream"] is False
    assert [m["role"] for m in cap["body"]["messages"]] == ["system", "user"]
    assert r.text == "hello from the gpu"


def test_ollama_host_env_override(monkeypatch):
    cap: dict = {}

    def fake_urlopen(req, timeout=None):
        cap["url"] = req.full_url
        return _FakeResponse(OLLAMA_JSON)

    monkeypatch.setenv("OLLAMA_HOST", "gigabyte.tailnet:11434")
    monkeypatch.setattr(llm, "urlopen", fake_urlopen)
    call_llm("ollama", "m", "hi")
    assert cap["url"] == "http://gigabyte.tailnet:11434/api/chat"


def test_server_down_is_transient(monkeypatch):
    def refuse(req, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    monkeypatch.setattr(llm, "urlopen", refuse)
    with pytest.raises(RateLimited) as exc:
        call_llm("ollama", "m", "hi")
    assert is_transient_cause(str(exc.value))   # the dispatcher requeues, never escalates


def test_missing_model_is_hard_not_transient(monkeypatch):
    def notfound(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None,
                                     io.BytesIO(b'{"error":"model not found"}'))

    monkeypatch.setattr(llm, "urlopen", notfound)
    with pytest.raises(RuntimeError) as exc:
        call_llm("ollama", "m", "hi")
    assert not isinstance(exc.value, RateLimited)
    assert not is_transient_cause(str(exc.value))


# --- the capability law, machine-checked ---

def test_file_writing_roles_keep_a_tool_capable_provider():
    """ollama (HTTP) returns text; it cannot create or edit files. Builder and tester exist to
    do exactly that, and the persistent overseer needs sessions (claude path only)."""
    assert AGENT_MODELS["builder"]["provider"] == "claude"
    assert AGENT_MODELS["tester"]["provider"] == "claude"
    assert AGENT_MODELS["overseer"]["provider"] == "claude"


def test_judge_runs_locally_planner_on_claude():
    assert AGENT_MODELS["judge"]["provider"] == "ollama"        # F5 + zero marginal cost
    assert AGENT_MODELS["task_manager"]["provider"] == "claude"  # planning is architecture (13 Jun)
