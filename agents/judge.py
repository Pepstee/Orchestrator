"""agents.judge — the independent validator. Subprocess contract: payload(stdin) -> AgentResult(stdout).

Runs on a DIFFERENT provider than the builder (registry assigns it to openai/codex) for true
independence — no shared training, no self-enhancement bias (finding F5). It reviews the built
project against the task + acceptance criteria and emits a structured pass/fail verdict. A
passing test suite is explicitly NOT treated as proof (finding F2). The LLM call is injected, so
the verdict logic is testable without spending tokens.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from agents.common import safe_main
from core.models import AgentResult, Task
from infra.llm import LLMResult, call_llm
from infra.workspace import default_projects_root, resolve_project_dir
from registry.agents import model_for

SYSTEM_PROMPT = (
    "You are the validator/judge in an autonomous orchestrator, running on a different model "
    "provider than the builder for independence. Judge whether the implementation truly meets the "
    "task and its acceptance criteria. Reward correctness and safety, not plausibility — a passing "
    "test suite is not proof. Output a single JSON verdict line and nothing else."
)

LLMCall = Callable[..., LLMResult]


def build_prompt(task: Task) -> str:
    crit = "\n".join(f"- {c}" for c in task.acceptance_criteria) or "(none specified)"
    return (
        f"Task that was implemented: {task.title}\n\n"
        f"Acceptance criteria:\n{crit}\n\n"
        "Independently review the implementation in the current working directory against the task "
        "and its acceptance criteria. Be strict and skeptical about correctness and safety — a "
        "passing test suite is not proof.\n"
        "If you choose to run the tests yourself, run `pytest -q` from the current directory (it "
        "discovers tests anywhere; do NOT assume a tests/ subdirectory). Base your verdict on whether "
        "the implementation is actually correct and meets the criteria — do NOT fail solely because a "
        "command you picked could not run in this environment; that is a tooling note, not a defect.\n\n"
        'Output ONLY a final JSON line: {"verdict":"pass"|"fail","reasons":[...],"confidence":0.0-1.0}'
    )


def parse_verdict(text: str) -> dict:
    """Scan backwards for the last JSON object carrying a `verdict`; fail-safe to a fail verdict."""
    for line in reversed([ln.strip() for ln in text.splitlines() if ln.strip()]):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "verdict" in data:
            verdict = "pass" if str(data.get("verdict", "")).lower() == "pass" else "fail"
            return {
                "verdict": verdict,
                "reasons": [str(r) for r in (data.get("reasons") or [])][:10],
                "confidence": float(data.get("confidence", 0.0) or 0.0),
            }
    return {"verdict": "fail", "reasons": ["unparseable verdict from judge"], "confidence": 0.0}


def run(payload: dict, call: LLMCall = call_llm, projects_root: str | None = None) -> AgentResult:
    task = Task.from_dict(payload.get("task", {}))
    spec = model_for("judge")  # different provider from the builder, by the registry
    root = Path(projects_root) if projects_root else default_projects_root()
    project_dir = resolve_project_dir(root, task.project)
    try:
        res = call(
            spec["provider"], spec["model"], build_prompt(task),
            system=SYSTEM_PROMPT, cwd=str(project_dir),
        )
    except Exception as exc:
        return AgentResult(ok=False, summary="judge call failed", cause=f"{type(exc).__name__}: {exc}")
    verdict = parse_verdict(res.text)
    passed = verdict["verdict"] == "pass"
    return AgentResult(
        ok=passed,
        summary=f"judge verdict: {verdict['verdict']} (confidence {verdict['confidence']:.2f})",
        metadata={"verdict": verdict, "cost_usd": res.cost_usd, "model": res.model or spec["model"]},
        cause=None if passed else ("; ".join(verdict["reasons"]) or "judge: fail"),
    )


if __name__ == "__main__":
    safe_main(run, "judge")
