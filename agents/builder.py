"""agents.builder — the implementation agent. Subprocess contract: payload(stdin) -> AgentResult(stdout).

This first cut produces the requested implementation as text via a real LLM call (claude, per the
registry) and reports its cost in metadata. Writing files into the project tree via tools is the
next slice. The LLM call is injected, so the agent's logic is fully testable without spending tokens.

Run for real (from the repo root, with the claude CLI authenticated):
    echo '{"task": {"task_id":"t1","title":"Write a haiku about orchestration","task_type":"implement"}}' \\
        | python -m agents.builder
"""
from __future__ import annotations

from typing import Callable

from agents.common import safe_main
from core.models import AgentResult, Task
from infra.llm import LLMResult, call_llm
from registry.agents import model_for

SYSTEM_PROMPT = (
    "You are the builder agent in an autonomous orchestrator. Implement exactly what the task "
    "asks, concisely and correctly. Do not invent scope. Output only the implementation."
)

LLMCall = Callable[..., LLMResult]


def build_prompt(task: Task) -> str:
    parts = [f"Task: {task.title}"]
    spec = task.payload.get("spec")
    if spec:
        parts.append(f"\nSpecification:\n{spec}")
    if task.acceptance_criteria:
        crit = "\n".join(f"- {c}" for c in task.acceptance_criteria)
        parts.append(f"\nAcceptance criteria:\n{crit}")
    return "\n".join(parts)


def run(payload: dict, call: LLMCall = call_llm) -> AgentResult:
    task = Task.from_dict(payload.get("task", {}))
    spec = model_for("builder")  # provider + model from the registry (single source of truth)
    try:
        res = call(spec["provider"], spec["model"], build_prompt(task), system=SYSTEM_PROMPT)
    except Exception as exc:
        return AgentResult(
            ok=False, summary="builder LLM call failed", cause=f"{type(exc).__name__}: {exc}"
        )
    text = res.text.strip()
    return AgentResult(
        ok=bool(text),
        summary=(text.splitlines()[0][:200] if text else "builder produced no output"),
        metadata={"cost_usd": res.cost_usd, "model": res.model or spec["model"], "output": res.text},
        cause=None if text else "empty LLM output",
    )


if __name__ == "__main__":
    safe_main(run, "builder")
