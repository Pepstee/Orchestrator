"""agents.task_manager — the INCREMENTAL planner (recreating the v1 behaviour that kept working).

Given the goal and the CURRENT state of the project (files built, steps done, steps failed with
their causes), it emits only the NEXT small batch of steps — not a big-bang decomposition of the
whole project up front (that behaves unpredictably: it routed test-writing to the judge and
dead-ended). The daemon re-invokes this whenever a project's queue drains and the goal isn't met
yet, feeding back what happened — so the project advances over iterations (the replan loop) instead
of stopping after one cycle. It outputs [] when the goal is fully met (how the loop terminates).

The LLM call is injected, so the planning logic is testable without spending tokens.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Callable

from agents.common import safe_main
from core.models import AgentResult, Task
from infra.llm import LLMResult, call_llm
from registry.agents import model_for

SYSTEM_PROMPT = (
    "You are the task manager in an autonomous orchestrator. You plan INCREMENTALLY: given the goal "
    "and the current project state, output ONLY the NEXT small batch of concrete, "
    "independently-checkable steps — never the whole project at once. Fix failures first. Every "
    "implement step writes its OWN tests; validate steps are review-only — NEVER create a separate "
    "test-writing step typed 'validate'. Output ONLY a JSON array, or [] when the goal is fully met."
)

LLMCall = Callable[..., LLMResult]


def build_prompt(goal: str, acceptance: list[str] | None = None, state: dict | None = None) -> str:
    state = state or {}
    parts = [f"Goal: {goal}"]
    if acceptance:
        parts.append("Acceptance criteria:\n" + "\n".join(f"- {c}" for c in acceptance))
    files = state.get("files") or []
    done = state.get("done") or []
    failed = state.get("failed") or []
    if files:
        parts.append("Files already in the project:\n" + "\n".join(f"- {f}" for f in files[:60]))
    if done:
        parts.append("Steps already completed:\n" + "\n".join(f"- {t}" for t in done[:40]))
    if failed:
        parts.append("Steps that FAILED — fix these FIRST:\n"
                     + "\n".join((f"- {f.get('title', '')}: {f.get('cause', '')}")[:200] for f in failed[:20]))
    parts.append(
        "Output ONLY a JSON array of the NEXT 1-5 steps (fix failures first, then the next "
        "increment toward the goal). Every implement step MUST write its own tests; validate steps "
        "are review-only. Output [] if the goal is fully met and nothing remains. Each step:\n"
        '  {"title": str, "task_type": "implement"|"validate", "acceptance": [str], "depends_on": [int]}\n'
        "depends_on lists indices within THIS array."
    )
    return "\n\n".join(parts)


def parse_plan(text: str) -> list[dict]:
    """Extract the step array, tolerating markdown fences and surrounding prose."""
    cleaned = re.sub(r"```(?:json)?", " ", text)
    candidates: list[str] = []
    start, end = cleaned.find("["), cleaned.rfind("]")
    if 0 <= start < end:
        candidates.append(cleaned[start:end + 1])
    candidates.append(cleaned)
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
    state = task.payload.get("state") if isinstance(task.payload, dict) else None
    spec = model_for("task_manager")
    try:
        res = call(spec["provider"], spec["model"],
                   build_prompt(task.title, task.acceptance_criteria, state), system=SYSTEM_PROMPT)
    except Exception as exc:
        return AgentResult(ok=False, summary="task manager call failed", cause=f"{type(exc).__name__}: {exc}")

    steps = parse_plan(res.text)
    if not steps:
        # The planner judged the goal complete (or had nothing to add). NOT a failure — this is how
        # the replan loop terminates; the daemon reads planner_done to stop iterating.
        return AgentResult(ok=True, summary="planner: no further tasks", spawned_tasks=[],
                           metadata={"cost_usd": res.cost_usd, "planner_done": True})

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
        summary=f"planned {len(spawned)} next task(s)",
        spawned_tasks=spawned,
        metadata={"cost_usd": res.cost_usd},
    )


if __name__ == "__main__":
    safe_main(run, "task_manager")
