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


def test_build_prompt_directs_a_separate_test_pass():
    # The planner must route test-writing to a separate 'test' step, not fold it into implement.
    p = build_prompt("Build a thing")
    assert '"test"' in p and "separate agent authors the tests" in p


def test_build_prompt_steers_parallel_work_off_collisions():
    # To avoid merge conflicts under concurrency: shared foundation first, parallel work on diff files.
    p = build_prompt("Build a thing")
    assert "DIFFERENT files" in p and "depend_on" in p


def test_run_wires_a_separate_test_step_to_its_implement_step():
    plan = (
        '[{"title":"build core","task_type":"implement","acceptance":["x"]},'
        '{"title":"test core","task_type":"test","depends_on":[0]},'
        '{"title":"review","task_type":"validate","depends_on":[1]}]'
    )

    def fake(provider, model, prompt, system=None, **_):
        return LLMResult(text=plan, cost_usd=0.02, model=model)

    r = run(_plan_task(), call=fake)
    assert r.ok and len(r.spawned_tasks) == 3
    impl, test, _val = r.spawned_tasks
    assert test["task_type"] == "test"
    assert impl["task_id"] in test["depends_on"]   # the test pass waits for the code


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


def test_improve_mode_prompts_for_betterment():
    p = build_prompt("X", mode="improve")
    assert "genuinely BETTER" in p and "security" in p and '"test"' in p   # the rich improvement brief


def test_run_in_improve_mode_uses_the_improve_brief():
    plan = ('[{"title":"add input validation","task_type":"implement"},'
            '{"title":"test validation","task_type":"test","depends_on":[0]}]')
    seen = {}

    def fake(provider, model, prompt, system=None, **_):
        seen["prompt"] = prompt
        return LLMResult(text=plan, cost_usd=0.01, model=model)

    payload = {"task": Task(task_id="p", title="X", task_type="plan", project="demo",
                            payload={"mode": "improve", "state": {}}).to_dict()}
    r = run(payload, call=fake)
    assert r.ok and len(r.spawned_tasks) == 2
    assert "genuinely BETTER" in seen["prompt"]        # improve brief drove the plan


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
