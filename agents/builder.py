"""agents.builder — the implementation agent. Subprocess contract: payload(stdin) -> AgentResult(stdout).

Builds into an isolated project tree (projects/<name>/) by running the LLM with that directory as
its working directory (file-editing tools). Enforces deliverable purity (L4): if the build leaves
orchestrator scratch in the tree, it fails. The LLM call is injected, so the logic is fully
testable without spending tokens.

Run for real (from the repo root, claude authenticated):
    echo '{"task": {"task_id":"t1","title":"Scaffold a hello-world CLI in python","task_type":"implement","project":"demo"}}' \\
        | python -m agents.builder
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from agents.common import safe_main
from core.models import AgentResult, Task
from infra.llm import LLMResult, call_llm
from infra.workspace import check_pristine, default_projects_root, resolve_project_dir
from registry.agents import model_for

SYSTEM_PROMPT = (
    "You are the builder agent in an autonomous orchestrator. Implement exactly what the task "
    "asks, concisely and correctly, by creating/editing files in your current working directory. "
    "Do not invent scope. Do not create scratch or bookkeeping files."
)

LLMCall = Callable[..., LLMResult]


def build_prompt(task: Task) -> str:
    parts = [f"Task: {task.title}"]
    spec = task.payload.get("spec")
    if spec:
        parts.append(f"\nSpecification:\n{spec}")
    if task.acceptance_criteria:
        parts.append("\nAcceptance criteria:\n" + "\n".join(f"- {c}" for c in task.acceptance_criteria))
    parts.append("\nCreate the necessary files in the current working directory.")
    return "\n".join(parts)


def _list_artifacts(project_dir: Path) -> list[str]:
    return sorted(
        str(p.relative_to(project_dir))
        for p in project_dir.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )


def run(payload: dict, call: LLMCall = call_llm, projects_root: str | None = None) -> AgentResult:
    task = Task.from_dict(payload.get("task", {}))
    spec = model_for("builder")
    root = Path(projects_root) if projects_root else default_projects_root()
    project_dir = resolve_project_dir(root, task.project)
    try:
        res = call(
            spec["provider"], spec["model"], build_prompt(task),
            system=SYSTEM_PROMPT, cwd=str(project_dir),
        )
    except Exception as exc:
        return AgentResult(
            ok=False, summary="builder LLM call failed", cause=f"{type(exc).__name__}: {exc}"
        )
    polluted = check_pristine(project_dir)
    if polluted:
        return AgentResult(
            ok=False, summary="project tree polluted",
            cause=f"orchestrator scratch in deliverable (L4): {polluted}",
            metadata={"cost_usd": res.cost_usd},
        )
    artifacts = _list_artifacts(project_dir)
    text = res.text.strip()
    return AgentResult(
        ok=True,
        summary=(text.splitlines()[0][:200] if text else f"wrote {len(artifacts)} file(s)"),
        artifacts=artifacts,
        metadata={"cost_usd": res.cost_usd, "model": res.model or spec["model"]},
    )


if __name__ == "__main__":
    safe_main(run, "builder")
