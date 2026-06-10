"""L3 — god-file soft guardrail: warn + trigger review above the limit, but NEVER block."""
from __future__ import annotations

import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {".venv", "__pycache__", ".git", "projects", ".ruff_cache", ".pytest_cache"}

# Mirrors pyproject.toml [tool.agentic] loc_soft_limit (charter L3). Kept inline so this
# trivial guardrail has no toml-parser dependency / Python-version requirement.
SOFT_LIMIT = 800


def test_loc_soft_guardrail_is_non_blocking():
    limit = SOFT_LIMIT
    offenders = []
    for p in ROOT.rglob("*.py"):
        # Skip archives and donor material along with the usual dirs: the guardrail watches the
        # ORCHESTRATOR's own source for god-files; archived deliverables alarming on every run
        # is the repeat-alert pathology (BG-4) in miniature.
        if any(part in SKIP or part.startswith("projects.") or ".archived-" in part
               or part == "docs" for part in p.parts):
            continue
        n = len(p.read_text(encoding="utf-8").splitlines())
        if n > limit:
            offenders.append((str(p.relative_to(ROOT)), n))
    if offenders:
        warnings.warn(
            f"L3 god-file guardrail: {offenders} exceed {limit} LOC — "
            f"architecture review triggered (non-blocking).",
            stacklevel=2,
        )
    assert True  # charter L3: soft guardrail never blocks the build
