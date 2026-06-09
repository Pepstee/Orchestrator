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
    "independently-checkable steps — never the whole project at once. Fix failures first. "
    "Separate the work by responsibility: an 'implement' step writes ONLY the implementation code "
    "(it does NOT write its own tests); pair each 'implement' step with a 'test' step that depends "
    "on it — the test-author is a SEPARATE agent so tests are an independent check, not "
    "self-agreement. 'validate' steps are review-only. Output ONLY a JSON array, or [] when the goal "
    "is fully met."
)

LLMCall = Callable[..., LLMResult]


_IMPROVE_INSTRUCTION = (
    "This project ALREADY MEETS its scope and is certified working. Your job now is to make it "
    "genuinely BETTER — plan the next 1-5 improvement steps, thinking like a discerning senior "
    "engineer AND product owner. Pick the highest-leverage improvements from: security hardening; "
    "reliability & error handling; broader, stronger, mutation-resistant tests; performance and lower "
    "token/resource use; cleaner code & architecture; better UX and presentation; a GUI or nicer "
    "interface; documentation; and genuinely useful new or better features. Use common sense about "
    "what a human would be proud to ship. Each 'implement' step writes ONLY code; pair it with a "
    "'test' step; 'validate' is review-only. Output [] ONLY if the project is already exceptional and "
    "you honestly cannot make it meaningfully better.\n"
    '  {"title": str, "task_type": "implement"|"test"|"validate", "acceptance": [str], "depends_on": [int]}\n'
    "depends_on lists indices within THIS array."
)


def build_prompt(goal: str, acceptance: list[str] | None = None, state: dict | None = None,
                 mode: str = "build") -> str:
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
    if mode == "improve":
        parts.append(_IMPROVE_INSTRUCTION)
        return "\n\n".join(parts)
    parts.append(
        "Output ONLY a JSON array of the NEXT 1-5 steps (fix failures first, then the next "
        "increment toward the goal). Split work by responsibility: an 'implement' step writes ONLY "
        "code (no tests); pair it with a 'test' step that depends on it (a separate agent authors the "
        "tests, independently); 'validate' steps are review-only. CONCURRENCY: steps run in parallel, "
        "so any shared foundation (package scaffold, config, shared types/interfaces) MUST be a single "
        "EARLY step that later steps depend_on; parallel 'implement' steps must touch DIFFERENT files "
        "so they never edit the same lines at once. For a RUNNABLE product, ensure an "
        "`acceptance` file exists at the project root with a command that runs it on sample input and "
        "prints real output (used to verify it actually works). Output [] if the goal is fully met "
        "and nothing remains. Each step:\n"
        '  {"title": str, "task_type": "implement"|"test"|"validate", "acceptance": [str], "depends_on": [int]}\n'
        "depends_on lists indices within THIS array (e.g. the test step depends on its implement step)."
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
    pl = task.payload if isinstance(task.payload, dict) else {}
    state = pl.get("state")
    mode = pl.get("mode", "build")   # "improve" -> plan the next round of making a done project better
    spec = model_for("task_manager")
    try:
        res = call(spec["provider"], spec["model"],
                   build_prompt(task.title, task.acceptance_criteria, state, mode=mode), system=SYSTEM_PROMPT)
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
