"""infra.worktree — per-task git worktree isolation, so MANY agents can safely edit ONE project at once.

Two agents writing the same project tree concurrently would clobber each other. Instead each
file-editing task runs in its own ephemeral git worktree (a branch off the project's current state);
on completion its changes are committed and merged back into the project's main tree. Independent
work (different files) merges cleanly; a real collision surfaces as a merge conflict and fails the
task — the planner then re-sequences. All git operations are driven from the dispatcher's single main
thread, so the merges never race; only the agents' edits run in parallel, each in its own checkout.

Git is driven via subprocess with an explicit identity (the v1 trap: a commit with no author silently
fails). Git owns the tree, so there are no raw file writes/deletes here — law L7 is untouched.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from infra.atomic_io import remove, write_text_atomic

_IDENT = ("-c", "user.email=orchestrator@local", "-c", "user.name=orchestrator")

# Build artefacts must never be tracked in a project repo: gate-runs regenerate them in the MAIN
# tree, the tree goes permanently dirty, and every worktree integration then fails
# deterministically — the 11 Jun overnight wedge (completed, tests-passing work was discarded at
# the merge step across all eight projects). Written at ensure_repo; legacy repos are healed at
# integrate time.
_PROJECT_GITIGNORE = "__pycache__/\n*.pyc\n.pytest_cache/\n*.egg-info/\n.ruff_cache/\n"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *_IDENT, *args],
                          capture_output=True, text=True)


def ensure_repo(project_dir: Path) -> None:
    """Make `project_dir` a git repo with at least one commit, so worktrees can branch off it.
    Always ensures the artefact .gitignore exists FIRST, so the baseline never tracks junk."""
    project_dir.mkdir(parents=True, exist_ok=True)
    gitignore = project_dir / ".gitignore"
    if not gitignore.exists():
        write_text_atomic(gitignore, _PROJECT_GITIGNORE)
    if (project_dir / ".git").exists():
        return
    _git(project_dir, "init", "-q")
    _git(project_dir, "add", "-A")
    _git(project_dir, "commit", "-q", "--allow-empty", "-m", "orchestrator: project baseline")


def heal_repo(project_dir: Path) -> None:
    """Make the PROJECT repo mergeable again (the 11 Jun wedge, made structural):
    1. abort any unfinished merge a crash/kill left behind; clear its residue files;
    2. untrack build artefacts a legacy baseline swept in (idempotent);
    3. snapshot any remaining stray changes as a commit — preserved, never discarded —
       so the next merge meets a clean base. Safe to call before every integration."""
    git_dir = project_dir / ".git"
    if not git_dir.exists():
        return
    if (git_dir / "MERGE_HEAD").exists():
        _git(project_dir, "merge", "--abort")
    for residue in ("AUTO_MERGE", "MERGE_HEAD", "MERGE_MSG"):
        remove(git_dir / residue)
    ensure_repo(project_dir)   # guarantees the artefact .gitignore exists
    _git(project_dir, "rm", "-r", "-q", "--cached", "--ignore-unmatch",
         "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache")
    if _git(project_dir, "status", "--porcelain").stdout.strip():
        _git(project_dir, "add", "-A")
        _git(project_dir, "commit", "-q", "-m",
             "orchestrator: heal - snapshot stray changes, untrack artefacts (pre-merge)")


def _wt_path(project_dir: Path, task_id: str) -> Path:
    # Outside the project tree (siblings under .worktrees/) so the test gate + scanners never see it.
    return project_dir.parent / ".worktrees" / f"{project_dir.name}_{task_id}"


def create_worktree(project_dir: Path, task_id: str) -> Path:
    """Branch a fresh worktree off the project's current main and return its path (the agent's cwd)."""
    ensure_repo(project_dir)
    wt = _wt_path(project_dir, task_id)
    if wt.exists():
        remove_worktree(project_dir, task_id)
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(project_dir, "worktree", "add", "-q", "-b", f"wt/{task_id}", str(wt), "HEAD")
    return wt


def integrate_worktree(project_dir: Path, task_id: str) -> bool:
    """Commit the worktree's changes and merge them into the project's main tree. Returns True on a
    clean merge, False on conflict (the merge is aborted; the task should be treated as failed)."""
    wt = _wt_path(project_dir, task_id)
    if not wt.exists():
        return True   # no worktree was created -> nothing to integrate
    heal_repo(project_dir)   # never merge into a wedged tree (11 Jun: it discards finished work)
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "--allow-empty", "-m", f"orchestrator: {task_id}")
    merged = _git(project_dir, "merge", "-q", "--no-ff", "-m", f"merge {task_id}", f"wt/{task_id}")
    if merged.returncode != 0:
        _git(project_dir, "merge", "--abort")
        return False
    return True


def head_rev(project_dir: Path) -> str:
    """The project's current HEAD commit — its base-state for BG-3's input fingerprint.
    Empty string when the directory is not (yet) a git repo: callers treat that as
    'determinism unprovable' and fall back to the ordinary bounded ladder."""
    proc = _git(Path(project_dir), "rev-parse", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def remove_worktree(project_dir: Path, task_id: str) -> None:
    """Tear down the worktree and its branch (best-effort; git owns the deletion, never raw rmtree)."""
    _git(project_dir, "worktree", "remove", "--force", str(_wt_path(project_dir, task_id)))
    _git(project_dir, "branch", "-D", f"wt/{task_id}")
