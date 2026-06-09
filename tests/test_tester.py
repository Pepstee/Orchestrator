"""Behavioural: the independent test-author writes a real suite into the project tree, guards L4.

Separating the test-author from the builder is the anti-collusion mechanism (the builder can't write
both the code and its own agreeable tests). The tester must actually PRODUCE tests — producing none
is a failure, not a quiet no-op.
"""
from __future__ import annotations

from pathlib import Path

from agents.tester import build_prompt, run
from core.models import Task
from infra.llm import LLMResult


def _payload(project: str = "default") -> dict:
    t = Task(task_id="t1", title="Test the calculator", task_type="test",
             acceptance_criteria=["add works", "rejects bad input"], project=project)
    return {"task": t.to_dict()}


def test_build_prompt_includes_task_and_acceptance():
    t = Task(task_id="t1", title="Test the calculator", task_type="test",
             acceptance_criteria=["add works"])
    p = build_prompt(t)
    assert "Test the calculator" in p and "add works" in p


def test_tester_writes_tests_and_reports_them(tmp_path: Path):
    def fake(provider, model, prompt, system=None, cwd=None, **_):
        assert cwd is not None and "SEPARATE" in (system or "")   # independent from the builder
        Path(cwd, "test_calc.py").write_text("def test_add():\n    assert 1 + 1 == 2\n", encoding="utf-8")
        return LLMResult(text="wrote test_calc.py", cost_usd=0.01, model=model)

    r = run(_payload(), call=fake, projects_root=str(tmp_path))
    assert r.ok and "test_calc.py" in r.artifacts


def test_tester_fails_if_no_tests_written(tmp_path: Path):
    def writes_nothing(provider, model, prompt, system=None, cwd=None, **_):
        return LLMResult(text="I looked but wrote nothing", cost_usd=0.01, model=model)

    r = run(_payload(), call=writes_nothing, projects_root=str(tmp_path))
    assert not r.ok and "no test" in r.cause.lower()


def test_tester_rejects_polluted_tree(tmp_path: Path):
    def fake(provider, model, prompt, system=None, cwd=None, **_):
        (Path(cwd) / "reports").mkdir()
        (Path(cwd) / "reports" / "x.md").write_text("scratch", encoding="utf-8")
        return LLMResult(text="did stuff", cost_usd=0.01, model=model)

    r = run(_payload(), call=fake, projects_root=str(tmp_path))
    assert not r.ok and "L4" in r.cause


def test_tester_handles_llm_failure(tmp_path: Path):
    def boom(*_a, **_k):
        raise RuntimeError("cli missing")

    r = run(_payload(), call=boom, projects_root=str(tmp_path))
    assert not r.ok and "cli missing" in r.cause
