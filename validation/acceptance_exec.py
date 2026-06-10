"""validation.acceptance_exec — the acceptance-by-execution gate (Quality Charter bar 2; DG-6).

A green test suite proves code parses and asserts; it does not prove the PRODUCT works. This gate
runs the real product on real input in its own directory and captures the output, so a stub that
produces nothing — or crashes — fails. Output is far harder to fake than a test.

The contract is DECLARED in an `acceptance` / `acceptance.txt` file in the project root: every
non-comment line is one executable criterion, and **all** must exit 0 with real output. Under
DG-6 (depth D2.5, zero-touch DG-2) there is no "not applicable" escape:

  - NO declaration  -> FAIL. Every product must declare how to demonstrate itself; under
    zero-touch, a default-pass gate is an invitation the June run already accepted once.
  - a MOCK tell in a criterion command (`--mock`, `mock`, `fake`, `dummy`, `stub`) -> FAIL.
    The June demo literally ran `acceptance.py --mock` against a dead package —
    a demonstration of the fake is not a demonstration.

Deterministic and dependency-free; the captured output is returned for the Judge to read.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from validation.gates import GateResult

_DECL_FILES = ("acceptance", "acceptance.txt")
_MAX_OUTPUT = 400
_MOCK_TELL = re.compile(r"(?i)(?:^|[\s/_.=-])(mock|fake|dummy|stub)(?:$|[\s/_.=-])")


def _declared_commands(project_dir: Path) -> list[str]:
    for name in _DECL_FILES:
        f = project_dir / name
        if not f.is_file():
            continue
        try:
            lines = [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()]
        except OSError:
            continue
        cmds = [ln for ln in lines if ln and not ln.startswith("#")]
        if cmds:
            return cmds
    return []


def _run_one(cmd: str, root: Path, timeout: int) -> GateResult:
    if _MOCK_TELL.search(cmd):
        return GateResult("acceptance_exec", False,
                          f"`{cmd}` demonstrates a mock path — acceptance must run the real product")
    try:
        proc = subprocess.run(cmd, shell=True, cwd=str(root), capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GateResult("acceptance_exec", False, f"`{cmd}` failed to run: {exc}")
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return GateResult("acceptance_exec", False,
                          f"`{cmd}` exited {proc.returncode}: {(err or out)[-_MAX_OUTPUT:]}")
    if not out:
        return GateResult("acceptance_exec", False,
                          f"`{cmd}` exited 0 but produced no output — the product must do something real")
    return GateResult("acceptance_exec", True, f"`{cmd}` ran: {out[-_MAX_OUTPUT:]}")


def run_acceptance_gate(
    project_dir: str,
    *,
    command: str = "",
    timeout: int = 300,
) -> GateResult:
    """Run every declared acceptance criterion in the project dir. Passed = ALL exit 0 with
    output and none is a mock path. No declaration -> FAIL (DG-6: no default-pass gates)."""
    root = Path(project_dir)
    cmds = [command.strip()] if command.strip() else _declared_commands(root)
    if not cmds:
        return GateResult(
            "acceptance_exec", False,
            "no acceptance declaration — every product must declare how to demonstrate itself "
            "(an `acceptance` file: one executable criterion per line)")
    results = [_run_one(cmd, root, timeout) for cmd in cmds]
    failed = [r for r in results if not r.passed]
    if failed:
        return GateResult("acceptance_exec", False,
                          f"{len(failed)}/{len(results)} criteria failed — first: {failed[0].detail}")
    joined = " | ".join(r.detail for r in results)
    return GateResult("acceptance_exec", True,
                      f"{len(results)} criteria demonstrated: {joined[:_MAX_OUTPUT * 2]}")
