"""Behavioural: the Judge's verdict logic + independence (runs on a different provider, F5)."""
from __future__ import annotations

from pathlib import Path

from agents.judge import parse_verdict, run
from core.models import Task
from infra.llm import LLMResult
from registry.agents import AGENT_MODELS


def _payload(project: str = "default") -> dict:
    t = Task(task_id="t1", title="Build X", task_type="validate",
             acceptance_criteria=["does X"], project=project)
    return {"task": t.to_dict()}


def test_parse_verdict_pass():
    v = parse_verdict('reasoning...\n{"verdict":"pass","reasons":[],"confidence":0.9}')
    assert v["verdict"] == "pass" and v["confidence"] == 0.9


def test_parse_verdict_unparseable_is_fail_safe():
    v = parse_verdict("no json here")
    assert v["verdict"] == "fail" and v["confidence"] == 0.0


def test_judge_uses_independent_provider_and_passes(tmp_path: Path):
    seen = {}

    def fake(provider, model, prompt, system=None, cwd=None, **_):
        seen["provider"] = provider
        return LLMResult(text='{"verdict":"pass","reasons":[],"confidence":0.95}',
                         cost_usd=0.01, model=model)

    r = run(_payload(), call=fake, projects_root=str(tmp_path))
    assert seen["provider"] == AGENT_MODELS["judge"]["provider"]   # judge uses its registry provider
    assert r.ok and r.metadata["verdict"]["verdict"] == "pass"


def test_judge_fail_carries_reasons(tmp_path: Path):
    def fake(provider, model, prompt, system=None, cwd=None, **_):
        return LLMResult(text='{"verdict":"fail","reasons":["missing tests"],"confidence":0.8}',
                         cost_usd=0.01, model=model)

    r = run(_payload(), call=fake, projects_root=str(tmp_path))
    assert not r.ok and "missing tests" in r.cause


def test_judge_handles_call_failure(tmp_path: Path):
    def boom(*_a, **_k):
        raise RuntimeError("codex missing")

    r = run(_payload(), call=boom, projects_root=str(tmp_path))
    assert not r.ok and "codex missing" in r.cause


def test_parse_verdict_tolerates_fences_and_multiline():
    from agents.judge import parse_verdict
    fenced = "My assessment:\n```json\n{\n  \"verdict\": \"pass\",\n  \"confidence\": 0.92,\n  \"reasons\": [\"works\"]\n}\n```\n"
    v = parse_verdict(fenced)
    assert v["verdict"] == "pass" and v["confidence"] == 0.92
    assert parse_verdict("no json here at all")["verdict"] == "fail"
    assert parse_verdict('{"verdict":"pass","confidence":"high"}')["confidence"] == 0.9   # word confidence -> float
