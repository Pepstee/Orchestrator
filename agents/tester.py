"""agents.tester — the independent test-author. Subprocess contract: payload(stdin) -> AgentResult(stdout).

SEPARATE from the builder that wrote the code (anti-collusion, finding F5 applied to tests): the
agent that writes the implementation must not also write the tests that bless it, or it can make
both agree on a stub. The tester reads the implementation already in the project tree and writes an
adversarial pytest suite that exercises the REAL code paths. Whatever it writes is then held to the
mutation gate (validation/mutation.py), so weak or trivial tests fail the project regardless of who
authored them. The LLM call is injected, so the logic is testable without spending tokens.

Run for real (after the builder has produced code in projects/<name>/):
    echo '{"task": {"task_id":"t1","title":"Test the CLI","task_type":"test","project":"demo"}}' \\
        | python -m agents.tester
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from agents.common import safe_main
from core.models import AgentResult, Task
from infra.llm import LLMResult, call_llm
from infra.workspace import check_pristine, task_workdir
from registry.agents import model_for

SYSTEM_PROMPT = (
    "You are the test-author agent in an autonomous orchestrator, SEPARATE from the builder that "
    "wrote the code — your tests are an independent check, never self-agreement. Read the existing "
    "implementation in your current working directory and write a thorough, adversarial pytest suite "
    "that exercises the REAL code paths: normal cases, edge cases, error handling, and boundaries. "
    "Tests MUST be able to fail — never assert something trivially true, never mock the unit under "
    "test (mocking it proves nothing). Create only test files (test_*.py); do not modify the "
    "implementation and do not create scratch files."
)

LLMCall = Callable[..., LLMResult]


def build_prompt(task: Task) -> str:
    parts = [f"Write tests for: {task.title}"]
    if task.acceptance_criteria:
        parts.append("\nThe code must satisfy these acceptance criteria — test them:\n"
                     + "\n".join(f"- {c}" for c in task.acceptance_criteria))
    parts.append(
        "\nInspect the implementation files already present in the current working directory and "
        "write a pytest suite (test_*.py) that genuinely exercises them. Cover edge cases and error "
        "paths, not just the happy path."
    )
    return "\n".join(parts)


def _test_files(project_dir: Path) -> list[str]:
    return sorted(
        str(p.relative_to(project_dir))
        for p in project_dir.rglob("*.py")
        if "__pycache__" not in p.parts and (p.name.startswith("test_") or p.name.endswith("_test.py"))
    )


def run(payload: dict, call: LLMCall = call_llm, projects_root: str | None = None) -> AgentResult:
    task = Task.from_dict(payload.get("task", {}))
    spec = model_for("tester")
    project_dir = task_workdir(task, projects_root)   # its worktree if isolated, else the project tree
    try:
        res = call(
            spec["provider"], spec["model"], build_prompt(task),
            system=SYSTEM_PROMPT, cwd=str(project_dir),
        )
    except Exception as exc:
        return AgentResult(ok=False, summary="tester LLM call failed", cause=f"{type(exc).__name__}: {exc}")

    polluted = check_pristine(project_dir)
    if polluted:
        return AgentResult(ok=False, summary="project tree polluted",
                           cause=f"orchestrator scratch in deliverable (L4): {polluted}",
                           metadata={"cost_usd": res.cost_usd})

    tests = _test_files(project_dir)
    if not tests:
        # The whole point of this pass is to produce tests; producing none is a failure, not a no-op.
        return AgentResult(ok=False, summary="tester wrote no test files",
                           cause="no test_*.py produced — the test pass must create a real suite",
                           metadata={"cost_usd": res.cost_usd})
    return AgentResult(
        ok=True,
        summary=f"wrote {len(tests)} test file(s): {', '.join(tests[:5])}",
        artifacts=tests,
        metadata={"cost_usd": res.cost_usd, "model": res.model or spec["model"]},
    )


if __name__ == "__main__":
    safe_main(run, "tester")
