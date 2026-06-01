"""agents.task_manager — decompose a goal into a wired graph of sub-tasks (dynamic decomposition).

The 'real' Task Manager: an LLM turns a goal into the smallest ordered set of concrete steps that
completes it, ending with a validation step. Steps are returned as spawned_tasks; the dispatcher
enqueues them (bounded by L6). depends_on is expressed by index into the plan and rewired to task
ids here. The LLM call is injected, so the decomposition logic is testable without spending tokens.
"""
from __future__ import annotations

import json
import uuid
from typing import Callable

from agents.common import safe_main
from core.models import AgentResult, Task
from infra.llm import LLMResult, call_llm
from registry.agents import model_for

SYSTEM_PROMPT = (
    "You are the task manager in an autonomous orchestrator. Decompose the goal into the SMALLEST "
    "ordered set of concrete, independently-checkable steps that completes it, ending with a "
    "validation step. Output ONLY a JSON array of steps."
)

LLMCall = Callable[..., LLMResult]


def build_prompt(goal: str) -> str:
    return (
        f"Goal: {goal}\n\n"
        "Output ONLY a JSON array of steps. Each step is:\n"
        '  {"title": str, "task_type": "implement"|"validate", "acceptance": [str], "depends_on": [int]}\n'
        "depends_on lists indices of earlier steps in this array. Keep it minimal; end with a validate step."
    )


def parse_plan(text: str) -> list[dict]:
    """Extract the step array (a single-line array, else the whole text). Keep only dict steps with a title."""
    candidates = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("[")]
    candidates.append(text)
    for blob in candidates:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return [s for s in data if isinstance(s, dict) and s.get("title")]
    return []


def run(payload: dict, call: LLMCall = call_llm) -> AgentResult:
    task = Task.from_dict(payload.get("task", {}))
    spec = model_for("task_manager")
    try:
        res = call(spec["provider"], spec["model"], build_prompt(task.title), system=SYSTEM_PROMPT)
    except Exception as exc:
        return AgentResult(ok=False, summary="task manager call failed", cause=f"{type(exc).__name__}: {exc}")

    steps = parse_plan(res.text)
    if not steps:
        return AgentResult(ok=False, summary="empty plan", cause="task manager produced no parseable steps")

    ids = [uuid.uuid4().hex[:12] for _ in steps]
    spawned = []
    for i, step in enumerate(steps):
        deps = [ids[j] for j in step.get("depends_on", [])
                if isinstance(j, int) and 0 <= j < len(steps) and j != i]
        spawned.append(Task(
            task_id=ids[i],
            title=str(step.get("title"))[:200],
            task_type=str(step.get("task_type", "implement")),
            project=task.project,
            acceptance_criteria=[str(c) for c in step.get("acceptance", [])],
            depends_on=deps,
        ).to_dict())

    return AgentResult(
        ok=True,
        summary=f"decomposed {task.title[:60]!r} into {len(spawned)} steps",
        spawned_tasks=spawned,
        metadata={"cost_usd": res.cost_usd},
    )


if __name__ == "__main__":
    safe_main(run, "task_manager")
