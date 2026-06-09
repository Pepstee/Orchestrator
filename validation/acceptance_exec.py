"""validation.acceptance_exec — the acceptance-by-execution gate (Quality Charter bar 2).

A green test suite proves code parses and asserts; it does not prove the PRODUCT works. This gate runs
the real product on real input in its own directory and captures the output, so a stub that produces
nothing — or crashes — fails. It is the strongest anti-stub check, because output is far harder to fake
than a test.

The run command is DECLARED by the project: either passed in, or read from an `acceptance` /
`acceptance.txt` file in the project root (first non-empty, non-comment line). If nothing is declared
the gate is NOT APPLICABLE and passes — a library needn't ship a demo; only a declared demo is held to
"exit 0 with real output". Deterministic and dependency-free.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from validation.gates import GateResult

_DECL_FILES = ("acceptance", "acceptance.txt")
_MAX_OUTPUT = 400


def _declared_command(project_dir: Path) -> str:
    for name in _DECL_FILES:
        f = project_dir / name
        if not f.is_file():
            continue
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
        except OSError:
            continue
    return ""


def run_acceptance_gate(
    project_dir: str,
    *,
    command: str = "",
    timeout: int = 300,
) -> GateResult:
    """Run the declared acceptance command in the project dir. Passed = exit 0 AND non-empty output.
    No declared command -> not applicable (pass). The captured output is returned for the Judge to read."""
    root = Path(project_dir)
    cmd = command.strip() or _declared_command(root)
    if not cmd:
        return GateResult("acceptance_exec", True, "no acceptance command declared (not applicable)")
    try:
        proc = subprocess.run(cmd, shell=True, cwd=str(root), capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GateResult("acceptance_exec", False, f"acceptance command failed to run: {exc}")
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return GateResult("acceptance_exec", False,
                          f"`{cmd}` exited {proc.returncode}: {(err or out)[-_MAX_OUTPUT:]}")
    if not out:
        return GateResult("acceptance_exec", False,
                          f"`{cmd}` exited 0 but produced no output — the product must do something real")
    return GateResult("acceptance_exec", True, f"`{cmd}` ran: {out[-_MAX_OUTPUT:]}")
