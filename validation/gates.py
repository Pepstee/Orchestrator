"""validation.gates — the completion gates and the four-gate completion contract.

Two-tier completion: *tasks* complete autonomously; a *project* (Global Task) is "done" only when
ALL FOUR gates pass — tests (it works) AND acceptance (meets intent) AND judge (independent
correctness/quality) AND user (your confirmation). The gates deliberately answer different
questions: tests prove the work *functions*, not that it is *safe/hardened* (finding F2).
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field

REQUIRED_GATES = ("tests", "acceptance", "judge", "user")

# Use the daemon's own interpreter, never a bare "python" — on macOS only "python3" may exist
# (the same exit-127 trap that bit agent launch). Single source of truth for the test command.
DEFAULT_TEST_COMMAND = (sys.executable or "python3", "-m", "pytest", "-q")


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CompletionResult:
    done: bool
    unmet: list[str] = field(default_factory=list)


def run_test_gate(
    project_dir: str,
    command: tuple[str, ...] = ("python", "-m", "pytest", "-q"),
    timeout: int = 1800,
) -> GateResult:
    """Run the project's own test suite in its directory. Passed = exit code 0."""
    try:
        proc = subprocess.run(
            list(command), cwd=str(project_dir), capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GateResult("tests", False, f"test command failed to run: {exc}")
    detail = (proc.stdout or proc.stderr or "").strip()[-400:]
    return GateResult("tests", proc.returncode == 0, detail)


def evaluate_completion(gates: dict[str, bool]) -> CompletionResult:
    """A project is done only when every required gate is present and True (conjunctive)."""
    unmet = [g for g in REQUIRED_GATES if not gates.get(g, False)]
    return CompletionResult(done=not unmet, unmet=unmet)
