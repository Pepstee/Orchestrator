"""agents.overseer — the operator's remote command agent (project scope; the "Jarvis").

The point of remote control: the operator declines a pending item or sends a free-text instruction,
and the Overseer (opus) carries it out WITHIN THE NAMED PROJECT — fixing code, adjusting the build —
then optionally asks for re-validation. It acts in the project's own directory (like the builder)
and stays inside the budget + safety perimeter. It does NOT touch the orchestrator's own code: that
is the deliberately-deferred self-modification seam (law L9). The LLM call is injected, so the
control logic is testable without spending tokens.

Run for real (repo root, claude authenticated):
    echo '{"task": {"task_id":"o1","title":"Fix the failing import in app.py","task_type":"oversee","project":"demo"}}' \\
        | python -m agents.overseer
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Callable

from agents.common import safe_main
from core.models import AgentResult, Task
from infra.llm import LLMResult, call_llm
from infra.workspace import default_projects_root, resolve_project_dir
from registry.agents import model_for

SYSTEM_PROMPT = (
    "You are the Overseer: the operator's trusted agent with full command over THIS PROJECT (never "
    "the orchestrator itself). Carry out the operator's instruction precisely by creating/editing "
    "files in your current working directory. Make the smallest change that satisfies it; invent no "
    "extra scope. When finished, output a final line of JSON: "
    '{"action": "<one sentence on what you did>", "revalidate": true|false} '
    "— set revalidate true when the change should be re-checked by the test and judge gates."
)

LLMCall = Callable[..., LLMResult]


def build_prompt(instruction: str, context: str) -> str:
    parts = [f"Operator instruction: {instruction}"]
    if context:
        parts.append(f"\nContext (what failed / current state):\n{context}")
    parts.append("\nAct now in the current working directory, then output the final JSON line.")
    return "\n".join(parts)


def parse_directive(text: str) -> dict:
    """Pull the trailing {action, revalidate} JSON line, tolerating markdown fences and prose."""
    cleaned = re.sub(r"```(?:json)?", " ", text)
    for line in reversed([ln.strip() for ln in cleaned.splitlines() if ln.strip()]):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and ("action" in data or "revalidate" in data):
            return data
    return {}


def run(payload: dict, call: LLMCall = call_llm, projects_root: str | None = None) -> AgentResult:
    task = Task.from_dict(payload.get("task", {}))
    instruction = task.title
    context = str(task.payload.get("context", ""))
    spec = model_for("overseer")
    root = Path(projects_root) if projects_root else default_projects_root()
    project_dir = resolve_project_dir(root, task.project)
    try:
        res = call(
            spec["provider"], spec["model"], build_prompt(instruction, context),
            system=SYSTEM_PROMPT, cwd=str(project_dir),
        )
    except Exception as exc:
        return AgentResult(ok=False, summary="overseer call failed", cause=f"{type(exc).__name__}: {exc}")

    directive = parse_directive(res.text)
    first_line = res.text.strip().splitlines()[0][:200] if res.text.strip() else "acted on instruction"
    action = str(directive.get("action") or first_line)
    spawned: list[dict] = []
    if directive.get("revalidate"):
        spawned.append(Task(
            task_id=uuid.uuid4().hex[:12],
            title=f"Re-validate after overseer: {instruction}"[:200],
            task_type="validate",
            project=task.project,
        ).to_dict())
    return AgentResult(
        ok=True,
        summary=f"overseer: {action}"[:200],
        spawned_tasks=spawned,
        metadata={"cost_usd": res.cost_usd, "model": res.model or spec["model"]},
    )


if __name__ == "__main__":
    safe_main(run, "overseer")
