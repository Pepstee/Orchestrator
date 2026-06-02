"""Behavioural: the Task Manager decomposes a goal into a wired spawned-task graph."""
from __future__ import annotations

from agents.task_manager import build_prompt, parse_plan, run
from core.models import Task
from infra.llm import LLMResult


def _plan_task() -> dict:
    return {"task": Task(task_id="p1", title="Build a thing", task_type="plan", project="demo").to_dict()}


def test_parse_plan_extracts_steps():
    steps = parse_plan(
        '[{"title":"a","task_type":"implement"},{"title":"v","task_type":"validate","depends_on":[0]}]'
    )
    assert len(steps) == 2 and steps[1]["task_type"] == "validate"


def test_parse_plan_garbage_is_empty():
    assert parse_plan("not a plan at all") == []


def test_parse_plan_handles_fences_and_prose():
    # the realistic case: the model wraps its array in ```json fences and chatty text
    text = (
        "Sure! Here's the plan:\n```json\n"
        '[\n  {"title": "build", "task_type": "implement"},\n'
        '  {"title": "review", "task_type": "validate", "depends_on": [0]}\n]\n'
        "```\nLet me know if you want changes."
    )
    steps = parse_plan(text)
    assert len(steps) == 2 and steps[0]["title"] == "build" and steps[1]["task_type"] == "validate"


def test_build_prompt_includes_goal():
    assert "Goal: Build a thing" in build_prompt("Build a thing")


def test_run_decomposes_into_wired_spawned_tasks():
    plan = (
        '[{"title":"build core","task_type":"implement","acceptance":["x"]},'
        '{"title":"review","task_type":"validate","depends_on":[0]}]'
    )

    def fake(provider, model, prompt, system=None, **_):
        assert "Goal:" in prompt
        return LLMResult(text=plan, cost_usd=0.02, model=model)

    r = run(_plan_task(), call=fake)
    assert r.ok and len(r.spawned_tasks) == 2
    build, review = r.spawned_tasks
    assert build["task_type"] == "implement" and build["project"] == "demo"
    assert review["task_type"] == "validate"
    assert review["depends_on"] == [build["task_id"]]   # index 0 rewired to the build's id


def test_run_empty_plan_signals_done():
    # Empty plan is NOT a failure now — it's how the incremental loop terminates (goal met).
    def fake(*_a, **_k):
        return LLMResult(text="[]", cost_usd=0.0, model="sonnet")

    r = run(_plan_task(), call=fake)
    assert r.ok and r.spawned_tasks == [] and r.metadata.get("planner_done") is True


def test_run_uses_current_state_for_replan():
    seen = {}

    def fake(provider, model, prompt, system=None, **_):
        seen["prompt"] = prompt
        return LLMResult(text='[{"title":"fix the import","task_type":"implement"}]', cost_usd=0.01, model=model)

    payload = {"task": Task(task_id="p2", title="Build a thing", task_type="plan", project="demo",
                            payload={"state": {"failed": [{"title": "config", "cause": "ImportError: missing"}],
                                               "done": ["scaffold"], "files": ["app.py"]}}).to_dict()}
    r = run(payload, call=fake)
    assert r.ok and len(r.spawned_tasks) == 1
    assert "FAILED" in seen["prompt"] and "ImportError" in seen["prompt"]   # failures fed back for replan
