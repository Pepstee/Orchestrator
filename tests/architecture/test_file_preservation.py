"""L7 — file preservation: all mutating file ops go through infra.atomic_io (the only writer)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {".venv", "__pycache__", ".git", "projects", ".ruff_cache", ".pytest_cache", "tests"}
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
        if any(part in SKIP for part in p.parts):
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
