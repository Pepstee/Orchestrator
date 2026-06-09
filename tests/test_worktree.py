"""Behavioural: per-task worktree isolation — independent work merges, collisions are caught (real git)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from infra.worktree import create_worktree, ensure_repo, integrate_worktree, remove_worktree

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _project(tmp_path: Path) -> Path:
    proj = tmp_path / "projects" / "demo"
    proj.mkdir(parents=True)
    (proj / "base.py").write_text("BASE = 1\n", encoding="utf-8")
    ensure_repo(proj)
    return proj


def test_independent_changes_merge_cleanly(tmp_path: Path):
    proj = _project(tmp_path)
    wt_a = create_worktree(proj, "A")
    (wt_a / "a.py").write_text("A = 1\n", encoding="utf-8")     # different files...
    wt_b = create_worktree(proj, "B")
    (wt_b / "b.py").write_text("B = 1\n", encoding="utf-8")     # ...so both merge
    assert integrate_worktree(proj, "A") is True
    assert integrate_worktree(proj, "B") is True
    remove_worktree(proj, "A")
    remove_worktree(proj, "B")
    assert (proj / "a.py").exists() and (proj / "b.py").exists()   # both landed in main
    assert (proj / "base.py").exists()


def test_colliding_changes_report_conflict(tmp_path: Path):
    proj = _project(tmp_path)
    wt_a = create_worktree(proj, "A")
    (wt_a / "base.py").write_text("BASE = 2\n", encoding="utf-8")   # same file...
    wt_b = create_worktree(proj, "B")
    (wt_b / "base.py").write_text("BASE = 3\n", encoding="utf-8")   # ...conflict on the second merge
    assert integrate_worktree(proj, "A") is True
    assert integrate_worktree(proj, "B") is False                  # caught, not silently clobbered
    remove_worktree(proj, "A")
    remove_worktree(proj, "B")
    assert (proj / "base.py").read_text(encoding="utf-8") == "BASE = 2\n"   # A kept; B cleanly rejected


def test_worktrees_live_outside_the_project_tree(tmp_path: Path):
    proj = _project(tmp_path)
    wt = create_worktree(proj, "X")
    assert ".worktrees" in str(wt) and proj not in wt.parents   # never inside the scanned project tree
    remove_worktree(proj, "X")
