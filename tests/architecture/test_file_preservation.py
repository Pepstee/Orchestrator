"""L7 — file preservation: all mutating file ops go through infra.atomic_io (the only writer)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {".venv", "__pycache__", ".git", "projects", ".ruff_cache", ".pytest_cache", "tests", "docs",
        "state"}
# docs/ added 9 Jun 2026: staged v1 port organs (docs/planning/port/) are non-importable donor
# material, not runtime source — L7's intent is that no RUNTIME path raw-writes. Each organ is
# reworked through atomic_io as it is ported into a live layer (PORT_LEDGER.md).
# state/ added 12 Jun 2026: runtime artefacts, never source — the L9R fence quarantines forensic
# COPIES of agent files there (state/quarantine/), and a copy of a test legitimately using raw
# writes must not fail the gate (the LOC-guardrail archive-scan pathology in miniature).
ALLOWED = {"infra/atomic_io.py"}  # the sanctioned writer/deleter

FORBIDDEN = [
    re.compile(r"""open\([^)]*["'][wa]"""),   # open(..., "w"/"a")
    re.compile(r"\.write_text\("),
    re.compile(r"\.write_bytes\("),
    re.compile(r"os\.unlink\("),
    re.compile(r"os\.remove\("),
    re.compile(r"\.unlink\("),
    re.compile(r"shutil\.rmtree\("),
]


def _py_files():
    for p in ROOT.rglob("*.py"):
        # Skip the SKIP dirs, and any built-deliverable or archive tree (projects/, projects.archived-*,
        # *.archived-*) — those are products, not orchestrator source the law applies to.
        if any(part in SKIP or part.startswith("projects.") or ".archived-" in part for part in p.parts):
            continue
        if str(p.relative_to(ROOT)).replace("\\", "/") in ALLOWED:
            continue
        yield p


def test_no_raw_file_mutation_outside_atomic_io():
    offenders = []
    for p in _py_files():
        text = p.read_text(encoding="utf-8")
        for pat in FORBIDDEN:
            if pat.search(text):
                offenders.append((str(p.relative_to(ROOT)), pat.pattern))
    assert not offenders, f"raw file mutation outside infra.atomic_io (L7): {offenders}"
