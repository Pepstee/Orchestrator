"""Soak: drive the FULL concurrent loop hard with a realistic fake agent — the end-to-end integration
proof the stub unit tests don't give. Real git worktrees, real concurrency, dependency ordering,
merge-back. Asserts the machine doesn't stall, corrupt state, leak worktrees, or invent projects.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from control.budget import BudgetGovernor
from control.pool import run_concurrent
from core.models import AgentResult, Task, TaskStatus
from dispatch.repository import TaskRepository
from infra.event_store import EventStore

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _fake_agent():
    """A plausible agent: a plan fans out into 3 implement + their tests + a validate; builders/testers
    write a UNIQUE file into their worktree (independent work -> clean concurrent merges)."""
    def invoke(task: Task) -> AgentResult:
        tt = task.task_type
        if tt == "plan":
            spawned = []
            for k in range(3):
                iid = f"{task.project}-impl{k}"
                spawned.append(Task(task_id=iid, title=f"impl {k}", task_type="implement",
                                    project=task.project).to_dict())
                spawned.append(Task(task_id=f"{task.project}-test{k}", title=f"test {k}", task_type="test",
                                    project=task.project, depends_on=[iid]).to_dict())
            spawned.append(Task(task_id=f"{task.project}-val", title="validate", task_type="validate",
                                project=task.project, depends_on=[f"{task.project}-impl0"]).to_dict())
            return AgentResult(ok=True, summary="planned", spawned_tasks=spawned, metadata={"cost_usd": 0.001})
        if tt in ("implement", "test"):
            wd = task.payload.get("workdir") if isinstance(task.payload, dict) else None
            if wd:
                Path(wd, f"{task.task_id}.py").write_text(f"# {task.task_id}\nVALUE = 1\n", encoding="utf-8")
            return AgentResult(ok=True, summary=f"did {task.task_id}", metadata={"cost_usd": 0.001})
        return AgentResult(ok=True, summary="pass", metadata={"cost_usd": 0.001})   # validate
    return invoke


def test_full_concurrent_loop_converges_clean(tmp_path: Path):
    proj_root = tmp_path / "projects"
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    gov = BudgetGovernor(EventStore(tmp_path / "b.log"), cap_usd=1e9, kill_switch_path=tmp_path / "KILL")
    for i in range(6):                                   # 6 projects in parallel
        repo.create(Task(task_id=f"plan{i}", title=f"goal {i}", task_type="plan", project=f"proj{i}"))

    invoke = _fake_agent()
    rounds = 0
    while rounds < 100:
        rounds += 1
        n = run_concurrent(repo, invoke, gov, max_workers=8, max_steps=100,
                           projects_root=str(proj_root), isolate=True)
        live = repo.list()
        if n == 0 and not any(t.status in (TaskStatus.QUEUED, TaskStatus.IN_PROGRESS) for t in live):
            break

    assert rounds < 100, "did not converge — possible stall / infinite loop"
    # 1) every task is terminal (nothing stranded)
    assert all(t.status in (TaskStatus.DONE, TaskStatus.FAILED) for t in repo.list())
    # 2) no project was invented; the 6 we seeded are exactly what exists
    assert {t.project for t in repo.list()} == {f"proj{i}" for i in range(6)}
    # 3) worktrees were all cleaned up (no leak)
    wt = proj_root / ".worktrees"
    assert not wt.exists() or not any(wt.iterdir()), "worktrees leaked"
    # 4) each project's deliverables actually merged into its main tree
    for i in range(6):
        files = list((proj_root / f"proj{i}").glob("*.py"))
        assert len(files) >= 6, f"proj{i} merged only {len(files)} files"   # 3 impl + 3 test
    # 5) the durable log replays to the identical state (no corruption)
    replayed = TaskRepository.replay(EventStore(tmp_path / "e.log"))
    assert {t.task_id: t.status for t in replayed.list()} == {t.task_id: t.status for t in repo.list()}
