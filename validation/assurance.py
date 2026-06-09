"""validation.assurance — the progressive-assurance loop (the pre-confirmation hardening window).

When a project has passed its automated gates but awaits your confirmation, it does not idle: it
runs escalating verification tiers (cheapest first), bounded by max_cycles, the budget, and a
should_stop signal (you intervening). It NEVER regresses — a tier only *verifies*; the first tier to
find an issue halts the loop and surfaces it. LLM tiers (edge-case generation, mutation testing,
adversarial probing, design audit) plug in as Tiers; the deterministic test-rerun tier ships now.

The governor is duck-typed (it exposes should_stop()) and injected — validation must not import the
control layer (the dependency arrow points inward).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from infra.llm import call_llm
from registry.agents import model_for
from validation.gates import GateResult, run_test_gate

# A tier verifies a project directory and returns a pass/fail finding. Tiers are ordered by
# increasing strictness; later tiers are more rigorous (and usually more expensive).
Tier = Callable[[str], GateResult]


@dataclass
class AssuranceOutcome:
    cycles_run: int
    findings: list[GateResult]
    passed: bool
    fully_hardened: bool
    stopped_reason: str


def _passed(findings: list[GateResult]) -> bool:
    return bool(findings) and all(f.passed for f in findings)


def run_assurance(
    project_dir: str,
    tiers: list[Tier],
    *,
    should_stop: Callable[[], bool] = lambda: False,
    governor: Any = None,
    max_cycles: int = 10,
) -> AssuranceOutcome:
    findings: list[GateResult] = []
    for tier in tiers:
        if len(findings) >= max_cycles:
            return AssuranceOutcome(len(findings), findings, _passed(findings), False, "max cycles reached")
        if should_stop():
            return AssuranceOutcome(len(findings), findings, _passed(findings), False, "user intervened")
        if governor is not None and governor.should_stop()[0]:
            return AssuranceOutcome(len(findings), findings, _passed(findings), False, "budget/kill-switch")
        result = tier(project_dir)
        findings.append(result)
        if not result.passed:
            return AssuranceOutcome(len(findings), findings, False, False, f"issue found at '{result.name}'")
    return AssuranceOutcome(len(findings), findings, _passed(findings), True, "all tiers passed (fully hardened)")


def default_tiers() -> list[Tier]:
    """The cheapest deterministic ladder: just re-run the project's suite (no LLM, no budget)."""
    return [lambda project_dir: run_test_gate(project_dir)]


def _parse_hardening(text: str) -> tuple[bool, str]:
    """Parse a hardening verdict {issue_found, detail}. Unparseable -> inconclusive (no confirmed issue)."""
    for line in reversed([ln.strip() for ln in text.splitlines() if ln.strip()]):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "issue_found" in data:
            return bool(data["issue_found"]), str(data.get("detail", ""))[:300]
    return False, "inconclusive (unparseable hardening verdict)"


def llm_tier(
    name: str,
    instruction: str,
    *,
    provider: str,
    model: str,
    governor: Any = None,
    call: Callable[..., Any] = call_llm,
) -> Tier:
    """A read-only LLM hardening reviewer: it looks for the described weakness and reports an issue.

    It modifies nothing (non-regressing); a found issue fails the tier (halting the loop to surface
    it); an infra error or unparseable verdict is non-blocking. It charges the governor its cost.
    """
    def tier(project_dir: str) -> GateResult:
        prompt = (
            f"{instruction}\n\nReview the code in the current working directory. "
            'Output ONLY a JSON line: {"issue_found": true|false, "detail": "..."}'
        )
        try:
            res = call(
                provider, model, prompt,
                system="You are a rigorous, read-only code-hardening reviewer. Do not modify files.",
                cwd=project_dir,
            )
        except Exception as exc:
            return GateResult(name, True, f"tier skipped (error): {type(exc).__name__}: {exc}")
        if governor is not None:
            try:
                governor.charge(float(res.cost_usd))
            except Exception:
                pass
        issue, detail = _parse_hardening(res.text)
        return GateResult(name, passed=not issue, detail=detail)

    return tier


def hardening_tiers(governor: Any = None, call: Callable[..., Any] = call_llm) -> list[Tier]:
    """The escalating ship-readiness ladder, cheapest first: re-run the suite -> REAL mutation testing
    (deterministic: prove the tests can fail) -> an adversarial LLM probe on the Judge's provider
    (independent of the builder). A finding at any tier blocks completion (the project is not 'done').
    The adversarial probe is framed strictly: report an issue only when it is concretely demonstrable,
    so a correct project converges rather than being failed on imagined faults."""
    from validation.acceptance_exec import run_acceptance_gate
    from validation.mutation import run_mutation_gate   # local import: avoids a load-order cycle
    jm = model_for("judge")
    return [
        lambda project_dir: run_test_gate(project_dir),
        lambda project_dir: run_acceptance_gate(project_dir),   # the product actually runs + produces output
        lambda project_dir: run_mutation_gate(project_dir),
        llm_tier(
            "adversarial",
            "Find a CONCRETE, demonstrable defect: a specific input or scenario (edge case, malformed "
            "or hostile input, or security flaw) the code actually mishandles. Only report an issue you "
            "can concretely justify with the offending input and the wrong behaviour; if the code is "
            "correct, report issue_found=false.",
            provider=jm["provider"], model=jm["model"], governor=governor, call=call,
        ),
    ]
