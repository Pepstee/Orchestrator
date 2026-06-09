"""control.self_test — BG-1: the boot self-test (enforcement before features).

The daemon refuses to dispatch unless every ACTIVE law's pytest-linked checks are present,
collected, and passing — anchored on the prime-directive check itself. The predicates are
explicit (docs/planning/09 §3, BG-1): named checks collected and passed, never a bare exit
code; a deleted or emptied law-linked test file reads red. There is deliberately NO bypass
flag or env switch — tests/architecture/test_boot_self_test.py asserts its absence.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

from charter.laws import LAWS

# Anchored on the prime directive: if this check is not among the law-linked set (or fails),
# nothing else in the system can be trusted to be enforced.
ANCHOR = "tests/architecture/test_every_law_has_a_check.py"

Runner = Callable[[Path, list[str]], tuple[int, str]]


def law_linked_test_paths(laws=LAWS) -> list[str]:
    """Every pytest path named by an ACTIVE law's check string — the boot-required set."""
    return sorted({
        path
        for law in laws
        if law.status == "active" and law.check
        for path in re.findall(r"tests/[\w./-]+\.py", law.check)
    })


def _pytest(root: Path, args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *args, "-q", "--tb=no", "-p", "no:cacheprovider"],
        cwd=root, capture_output=True, text=True, timeout=600,
    )
    return proc.returncode, proc.stdout + proc.stderr


def run_boot_self_test(root: Path, laws=LAWS, runner: Runner | None = None) -> tuple[bool, str]:
    """True iff every law-linked check exists, collects at least one test, and passes."""
    runner = runner or _pytest
    paths = law_linked_test_paths(laws)
    if ANCHOR not in paths:
        return False, f"anchor check missing from charter law-links: {ANCHOR}"
    missing = [p for p in paths if not (root / p).is_file()]
    if missing:
        return False, f"law-linked test files missing: {missing}"
    code, out = runner(root, ["--collect-only", *paths])
    if code != 0:
        return False, f"collection failed: {out[-300:]}"
    uncollected = [p for p in paths if p not in out]
    if uncollected:
        return False, f"law-linked files collected no tests: {uncollected}"
    code, out = runner(root, paths)
    if code != 0:
        return False, f"law-linked checks failed: {out[-300:]}"
    match = re.search(r"(\d+) passed", out)
    if not match or int(match.group(1)) < len(paths):
        return False, f"fewer checks passed than law-linked files: {out[-200:]}"
    return True, f"{match.group(1)} law-linked checks passed ({len(paths)} files)"
