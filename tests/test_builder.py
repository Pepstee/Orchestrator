"""Behavioural: the Builder builds into an isolated project tree, reports artifacts, guards L4."""
from __future__ import annotations

from pathlib import Path

from agents.builder import build_prompt, run
from core.models import Task
from infra.llm import LLMResult


def _payload(project: str = "default") -> dict:
    t = Task(
        task_id="t1", title="Build a thing", task_type="implement",
        payload={"spec": "do x"}, acceptance_criteria=["works"], project=project,
    )
    return {"task": t.to_dict()}


def test_build_prompt_includes_task_details():
    t = Task(task_id="t1", title="Build a thing", task_type="implement",
             payload={"spec": "do x"}, acceptance_criteria=["works"])
    p = build_prompt(t)
    assert "Build a thing" in p and "do x" in p and "works" in p


def test_builder_writes_files_and_reports_artifacts(tmp_path: Path):
    def fake(provider, model, prompt, system=None, cwd=None, **_):
        assert provider == "claude" and cwd is not None      # builds in the project dir
        Path(cwd, "out.py").write_text("print('hi')\n", encoding="utf-8")
        return LLMResult(text="created out.py", cost_usd=0.03, model=model)

    r = run(_payload(), call=fake, projects_root=str(tmp_path))
    assert r.ok
    assert "out.py" in r.artifacts
    assert r.metadata["cost_usd"] == 0.03


def test_builder_rejects_polluted_tree(tmp_path: Path):
    def fake(provider, model, prompt, system=None, cwd=None, **_):
        (Path(cwd) / "reports").mkdir()                       # orchestrator scratch — forbidden
        (Path(cwd) / "reports" / "x.md").write_text("scratch", encoding="utf-8")
        return LLMResult(text="did stuff", cost_usd=0.01, model=model)

    r = run(_payload(), call=fake, projects_root=str(tmp_path))
    assert not r.ok and "L4" in r.cause


def test_builder_handles_llm_failure(tmp_path: Path):
    def boom(*_a, **_k):
        raise RuntimeError("cli missing")

    r = run(_payload(), call=boom, projects_root=str(tmp_path))
    assert not r.ok and "cli missing" in r.cause
