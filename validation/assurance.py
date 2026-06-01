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

from dataclasses import dataclass
from typing import Any, Callable

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
    """The shippable ladder: re-run the project's suite. LLM tiers (edge/mutation/adversarial/audit)
    are appended here as they are built."""
    return [lambda project_dir: run_test_gate(project_dir)]
