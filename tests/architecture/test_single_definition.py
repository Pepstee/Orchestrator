"""L1 — each domain type has exactly ONE definition (no v1-style dual AgentResult)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {".venv", "__pycache__", ".git", "projects", ".ruff_cache", ".pytest_cache"}


def _py_files():
    for p in ROOT.rglob("*.py"):
        if not any(part in SKIP for part in p.parts):
            yield p


def _count_class_defs(name: str) -> int:
    pat = re.compile(rf"^\s*class\s+{re.escape(name)}\b")
    return sum(
        1
        for p in _py_files()
        for line in p.read_text(encoding="utf-8").splitlines()
        if pat.match(line)
    )


def test_agentresult_defined_once():
    assert _count_class_defs("AgentResult") == 1, "AgentResult must have exactly one definition (L1)"


def test_task_defined_once():
    assert _count_class_defs("Task") == 1, "Task must have exactly one definition (L1)"
