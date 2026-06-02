"""Behavioural: the overseer command agent — acts in the project, optionally spawns re-validation."""
from __future__ import annotations

from pathlib import Path

from agents.overseer import parse_directive, run
from infra.llm import LLMResult


def _stub(text: str, cost: float = 0.02):
    def call(_provider, _model, _prompt, *, system=None, cwd=None, **_kw):
        return LLMResult(text=text, cost_usd=cost, model="opus")
    return call


def _payload(instruction: str, project: str = "demo", context: str = "") -> dict:
    return {"task": {"task_id": "o1", "title": instruction, "task_type": "oversee",
                     "project": project, "payload": {"context": context}}}


def test_overseer_acts_and_spawns_revalidate(tmp_path: Path):
    res = run(_payload("fix the failing import"),
              call=_stub('Fixed it.\n{"action": "fixed the import in app.py", "revalidate": true}'),
              projects_root=str(tmp_path))
    assert res.ok
    assert "fixed the import" in res.summary
    assert len(res.spawned_tasks) == 1 and res.spawned_tasks[0]["task_type"] == "validate"
    assert res.spawned_tasks[0]["project"] == "demo"


def test_overseer_no_revalidate_when_not_directed(tmp_path: Path):
    res = run(_payload("just summarise the code"),
              call=_stub('Looked it over.\n{"action": "inspected", "revalidate": false}'),
              projects_root=str(tmp_path))
    assert res.ok and res.spawned_tasks == []


def test_overseer_llm_failure_is_safe(tmp_path: Path):
    def boom(*_a, **_k):
        raise RuntimeError("no claude on PATH")
    res = run(_payload("do a thing"), call=boom, projects_root=str(tmp_path))
    assert not res.ok and "overseer call failed" in res.summary and "RuntimeError" in (res.cause or "")


def test_parse_directive_tolerates_fences_and_prose():
    assert parse_directive('done\n```json\n{"action": "a", "revalidate": true}\n```')["revalidate"] is True
    assert parse_directive("no json at all") == {}
