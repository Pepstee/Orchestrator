"""Behavioural: the Builder agent's logic, with the LLM call faked (no tokens spent)."""
from __future__ import annotations

from agents.builder import build_prompt, run
from core.models import Task
from infra.llm import LLMResult


def _payload() -> dict:
    t = Task(
        task_id="t1", title="Build a thing", task_type="implement",
        payload={"spec": "do x"}, acceptance_criteria=["works"],
    )
    return {"task": t.to_dict()}


def test_build_prompt_includes_task_details():
    t = Task(task_id="t1", title="Build a thing", task_type="implement",
             payload={"spec": "do x"}, acceptance_criteria=["works"])
    p = build_prompt(t)
    assert "Build a thing" in p and "do x" in p and "works" in p


def test_run_returns_ok_with_cost():
    def fake(provider, model, prompt, system=None, **_):
        assert provider == "claude"           # the registry assigns the builder to claude
        assert "Build a thing" in prompt
        return LLMResult(text="line one\nmore detail", cost_usd=0.02, model=model)

    r = run(_payload(), call=fake)
    assert r.ok
    assert r.summary == "line one"
    assert r.metadata["cost_usd"] == 0.02


def test_run_handles_llm_failure():
    def boom(*_a, **_k):
        raise RuntimeError("cli missing")

    r = run(_payload(), call=boom)
    assert not r.ok and "cli missing" in r.cause


def test_run_empty_output_is_failure():
    def empty(*_a, **_k):
        return LLMResult(text="   ", cost_usd=0.0, model="sonnet")

    r = run(_payload(), call=empty)
    assert not r.ok and r.cause
