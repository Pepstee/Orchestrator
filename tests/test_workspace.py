"""L4 — project workspace isolation (containment) + deliverable purity (no orchestrator scratch)."""
from __future__ import annotations

from pathlib import Path

import pytest

from infra.workspace import check_pristine, resolve_project_dir


def test_resolve_stays_within_projects(tmp_path: Path):
    d = resolve_project_dir(tmp_path, "myproj")
    assert d.is_dir() and tmp_path in d.parents


def test_resolve_rejects_escape(tmp_path: Path):
    for bad in ["../escape", "../../etc", "/etc", "..", ""]:
        with pytest.raises(ValueError):
            resolve_project_dir(tmp_path, bad)


def test_pristine_passes_for_clean_tree(tmp_path: Path):
    proj = resolve_project_dir(tmp_path, "p")
    (proj / "schema.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "README.md").write_text("# p\n", encoding="utf-8")
    assert check_pristine(proj) == []


def test_pristine_flags_orchestrator_scratch(tmp_path: Path):
    proj = resolve_project_dir(tmp_path, "p")
    (proj / "handoffs").mkdir()
    (proj / "events.log").write_text("{}\n", encoding="utf-8")
    flagged = check_pristine(proj)
    assert any("handoffs" in f for f in flagged)
    assert any("events.log" in f for f in flagged)
