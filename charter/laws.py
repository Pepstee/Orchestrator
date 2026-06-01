"""charter.laws — the laws as DATA, each linked to its enforcing check (the prime directive).

"A law without a machine-check is a wish." Active laws MUST name a check; the meta-check
test_every_law_has_a_check fails the build if an active law has none. Laws whose subsystem
isn't built yet are 'deferred' with a written reason — keeping the gap explicit and traceable
(the law-intake rule: a new active law ships with its check in the same change).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Law:
    id: str
    name: str
    status: str          # "active" (check required+present) | "deferred" (subsystem pending)
    check: str | None    # name of the enforcing test or import-linter contract
    note: str = ""


LAWS: list[Law] = [
    Law("L1", "Single source of truth", "active",
        "tests/architecture/test_single_definition.py + test_registry_single_source.py"),
    Law("L2", "Inward-only layered dependencies", "active",
        "import-linter: L2 — inward-only layered dependencies"),
    Law("L3", "Module-size soft guardrail (warn + review @700-800 LOC)", "active",
        "tests/architecture/test_loc_soft_guardrail.py"),
    Law("L5", "No arbitrary model choice (registry is canonical)", "active",
        "tests/architecture/test_registry_single_source.py"),
    Law("L9", "Self-modification quarantined", "active",
        "import-linter: L9 — self-modification is quarantined"),
    Law("L11", "Total state machine", "active",
        "tests/architecture/test_state_machine_total.py"),
    Law("PRIME", "Every active law has a machine-check", "active",
        "tests/architecture/test_every_law_has_a_check.py"),

    # Deferred — subsystem not built yet; check planned (gap kept explicit and traceable).
    Law("L4", "Deliverable purity (project tree isolated; no orchestrator scratch)", "active",
        "tests/test_workspace.py (containment + pristine) + builder L4 guard"),
    Law("L6", "Bounded autonomy (loops capped + budget + kill-switch)", "active",
        "tests/test_budget.py (run loop bounded by max_steps, budget cap, kill-switch)"),
    Law("L7", "File preservation (all mutation via infra.atomic_io)", "active",
        "tests/architecture/test_file_preservation.py"),
    Law("L8", "One supervised entrypoint; single-instance; graceful stop; no resurrection", "active",
        "tests/test_pidlock.py + tests/test_daemon.py"),
    Law("L10", "Failures self-explaining (cause required)", "deferred",
        None, "AgentResult.cause field exists; runtime check lands with the agent runner"),
    Law("A2", "Evals required for behaviour changes", "deferred",
        None, "check lands with the eval harness"),
]


def active_laws_missing_check() -> list[Law]:
    """The prime-directive violation set: active laws with no linked check."""
    return [law for law in LAWS if law.status == "active" and not law.check]
