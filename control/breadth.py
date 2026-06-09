"""control.breadth — BG-2: depth before breadth (one project until a certification exists).

The flagship is HUMAN-ONLY configuration: a plain file `state/flagship` the operator writes.
Nothing in this codebase writes that file — tests/architecture/test_breadth_cap.py asserts
that the only source files even referencing it are this module and the daemon (both reads).
Until the repository records a first project confirmation, dispatch is restricted to the
flagship (reserved `__` meta-projects always dispatch). Once a certification exists the cap
lifts; DG-4's ratchet (overseer-steered priorities, halve-on-breach) governs breadth beyond.
"""
from __future__ import annotations

from pathlib import Path

from dispatch.repository import TaskRepository


def read_flagship(state_dir: Path) -> str | None:
    """The operator-written flagship project name, or None if unset/unreadable."""
    try:
        text = (state_dir / "flagship").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def breadth_allowance(repo: TaskRepository, flagship: str | None) -> set[str] | None:
    """None = unrestricted (a certification exists). Otherwise the allowed project set —
    the flagship alone, or empty (park everything buildable) when no flagship is set."""
    if repo.confirmed_projects():
        return None
    return {flagship} if flagship else set()
