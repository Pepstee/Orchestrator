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
from infra.llm import LLMResult, call_llm, call_spec
from infra.workspace import default_projects_root, resolve_project_dir
from registry.agents import model_for

SYSTEM_PROMPT = (
    "You are the validator/judge in an autonomous orchestrator, on a different model provider than "
    "the builder for independence. You are the FINAL arbiter of 'done' — there is NO human reviewer "
    "after you, so be thorough and uncompromising. Judge whether the implementation is genuinely "
    "complete, correct, and of a professional, industry-standard quality — actually working software, "
    "not a stub or an imitation that only looks finished. Reward correctness and real functionality, "
    "never plausibility; a passing test suite is NOT proof. You MAY use web search to check current "
    "best practices, library usage, and the quality bar real products in this category meet. Pass "
    "only what you would be proud to ship. Output a single JSON verdict line and nothing else."
)

LLMCall = Callable[..., LLMResult]


def build_prompt(task: Task) -> str:
    crit = "\n".join(f"- {c}" for c in task.acceptance_criteria) or "(none specified)"
    return (
        f"Task that was implemented: {task.title}\n\n"
        f"Acceptance criteria:\n{crit}\n\n"
        "Independently review the implementation in the current working directory against the task "
        "and its acceptance criteria, AND against the standard a real, shippable product in this "
        "category would meet (use web search if it helps you judge that bar). Be strict and skeptical "
        "about correctness, completeness and safety — a passing test suite is not proof. FAIL anything "
        "that is a stub, placeholder, or imitation of working software, or that is merely 'okay' "
        "rather than genuinely finished and impressive. You are the last gate; nothing human follows.\n"
        "If you choose to run the tests yourself, run `pytest -q` from the current directory (it "
        "discovers tests anywhere; do NOT assume a tests/ subdirectory). Base your verdict on whether "
        "the implementation is actually correct and meets the criteria — do NOT fail solely because a "
        "command you picked could not run in this environment; that is a tooling note, not a defect.\n\n"
        'Output ONLY a final JSON line: {"verdict":"pass"|"fail","reasons":[...],"confidence":0.0-1.0}'
    )


def parse_verdict(text: str) -> dict:
    """Extract the LAST JSON object carrying a 'verdict' from anywhere in the text. Tolerates
    markdown code fences, pretty-printed/multi-line JSON, and surrounding prose; fail-safe to fail."""
    cleaned = (text or "").replace("```json", " ").replace("```", " ")
    cands = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    depth = 0
    start = None
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                cands.append(cleaned[start:i + 1])
    for cand in reversed(cands):
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict) and "verdict" in data:
            verdict = "pass" if str(data.get("verdict", "")).lower() == "pass" else "fail"
            raw_conf = data.get("confidence", 0.0)
            try:
                confidence = float(raw_conf)
            except (TypeError, ValueError):
                confidence = {"high": 0.9, "medium": 0.6, "low": 0.3, "none": 0.0}.get(str(raw_conf).strip().lower(), 0.5)
            return {
                "verdict": verdict,
                "reasons": [str(r) for r in (data.get("reasons") or [])][:10],
                "confidence": confidence,
            }
    return {"verdict": "fail", "reasons": ["unparseable verdict from judge"], "confidence": 0.0}


def run(payload: dict, call: LLMCall = call_llm, projects_root: str | None = None) -> AgentResult:
    task = Task.from_dict(payload.get("task", {}))
    spec = model_for("judge")  # different provider from the builder, by the registry
    root = Path(projects_root) if projects_root else default_projects_root()
    project_dir = resolve_project_dir(root, task.project)
    try:
        res = call_spec(
            spec, build_prompt(task), call=call,
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
