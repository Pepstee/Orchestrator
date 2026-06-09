"""infra.workspace — the project workspace: where deliverables are built, kept isolated (law L4).

resolve_project_dir guarantees an agent can only build *inside* projects/<name> (no escaping into
the orchestrator's own source/state). check_pristine enforces deliverable purity: a project tree
must contain only its own artifacts, never orchestrator scratch (handoffs, reports, state, logs) —
the v1 pollution bug, now structurally caught.
"""
from __future__ import annotations

from pathlib import Path

from core.models import Task

# Orchestrator bookkeeping that must NEVER appear inside a deliverable project tree.
SCRATCH_DIRS = {"handoffs", "reports", "state", "journal", ".worktrees"}


def default_projects_root() -> Path:
    """The canonical projects/ directory at the repo root (gitignored)."""
    return Path(__file__).resolve().parents[1] / "projects"


def task_workdir(task: Task, projects_root: Path | str | None = None) -> Path:
    """The directory an agent should edit: its per-task git worktree if the dispatcher provided one
    (concurrent isolation — many agents on one project), else the project's own tree. Threads the
    worktree through without every agent needing to know about worktrees."""
    wd = task.payload.get("workdir") if isinstance(task.payload, dict) else None
    if wd:
        return Path(wd)
    root = Path(projects_root) if projects_root else default_projects_root()
    return resolve_project_dir(root, task.project)


def resolve_project_dir(projects_root: Path | str, name: str) -> Path:
    """Resolve projects_root/<name>, guaranteeing the result is strictly inside projects_root."""
    root = Path(projects_root).resolve()
    candidate = (root / name).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError(f"project name {name!r} escapes the projects root {root}")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def check_pristine(project_dir: Path | str) -> list[str]:
    """Return any orchestrator-scratch paths found in the project tree ([] means pristine)."""
    project_dir = Path(project_dir)
    offenders: set[str] = set()
    for p in project_dir.rglob("*"):
        rel = p.relative_to(project_dir)
        if set(rel.parts) & SCRATCH_DIRS:
            offenders.add(str(rel))
        elif p.is_file() and (
            p.name == "events.log"
            or p.name.endswith(".events.log")
            or p.name.startswith("agent_input_")
        ):
            offenders.add(str(rel))
    return sorted(offenders)
