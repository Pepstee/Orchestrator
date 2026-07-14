"""Behavioural: the concurrent driver — real parallelism, dependency ordering, worktree isolation."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from control.budget import BudgetGovernor
from control.pool import run_concurrent
from core.models import AgentResult, Event, Task, TaskStatus
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def _gov(tmp_path: Path) -> BudgetGovernor:
    return BudgetGovernor(EventStore(tmp_path / "b.log"), cap_usd=1_000_000.0, kill_switch_path=tmp_path / "KILL")


def test_maintenance_runs_during_a_busy_batch(tmp_path: Path):
    """The per-cycle hook must fire WHILE agents are in flight, not only after the batch drains —
    otherwise a never-idle pool starves the overseer pulse / prerequisite cascade. Here a long-running
    agent is in flight and maintenance enqueues a NEW task that gets claimed before the first settles."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="slow", title="x", task_type="implement", project="A"))
    ran = {"n": 0}

    def maintenance() -> None:
        ran["n"] += 1
        if ran["n"] == 1:                       # mid-batch: inject a second project's work
            repo.create(Task(task_id="late", title="y", task_type="implement", project="B"))

    def invoke(t: Task) -> AgentResult:
        time.sleep(0.2 if t.task_id == "slow" else 0.01)
        return AgentResult(ok=True, summary="done")

    n = run_concurrent(repo, invoke, _gov(tmp_path), max_workers=4, max_steps=50, isolate=False,
                       maintenance=maintenance, maintenance_interval=0.0)
    assert n == 2                                # both ran in one batch
    assert repo.get("late").status == TaskStatus.DONE   # the mid-batch injection was picked up
    assert ran["n"] >= 1


def test_runs_agents_concurrently(tmp_path: Path):
    """Six 0.15s calls should finish in ~one call's time, not six (proves real parallelism)."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    for i in range(6):
        repo.create(Task(task_id=f"t{i}", title="x", task_type="implement", project=f"p{i}"))

    def invoke(_t: Task) -> AgentResult:
        time.sleep(0.15)
        return AgentResult(ok=True, summary="done")

    start = time.time()
    n = run_concurrent(repo, invoke, _gov(tmp_path), max_workers=6, max_steps=50, isolate=False)
    elapsed = time.time() - start
    assert n == 6
    assert all(repo.get(f"t{i}").status == TaskStatus.DONE for i in range(6))
    assert elapsed < 0.6, f"ran serially? {elapsed:.2f}s (6×0.15 = 0.9s sequential)"


def test_claim_next_serialises_per_project_by_default(tmp_path: Path):
    """Default per_project_cap=1: one agent per project tree at a time (kills intra-project merge-conflict
    thrash); cross-project work still runs in parallel. Opt back into intra-project parallelism with
    per_project_cap=0 (worktrees isolate) — covered in test_repository."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a", title="x", task_type="implement", project="P"))
    repo.create(Task(task_id="b", title="y", task_type="implement", project="P"))
    repo.create(Task(task_id="c", title="z", task_type="implement", project="Q"))
    claimed = {repo.claim_next().task_id, repo.claim_next().task_id}
    assert claimed == {"a", "c"}                  # one per project (P + Q); P's second task is held
    assert repo.claim_next() is None              # b stays queued until a frees P


def test_claim_next_skips_control_and_respects_deps(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="ctl", title="abandon", task_type="control", project="__overseer__"))
    repo.create(Task(task_id="impl", title="i", task_type="implement", project="proj"))
    repo.create(Task(task_id="test", title="t", task_type="test", project="proj", depends_on=["impl"]))
    assert repo.claim_next().task_id == "impl"   # control skipped (daemon executes those)
    assert repo.claim_next() is None             # test blocked: prerequisite not yet done
    repo.apply("impl", Event.COMPLETE)
    assert repo.claim_next().task_id == "test"   # dependency satisfied


def test_concurrent_settles_spawned_tasks(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="p", title="plan", task_type="plan", project="proj"))

    def invoke(t: Task) -> AgentResult:
        if t.task_id == "p":
            spawned = [Task(task_id="impl", title="i", task_type="implement", project="proj").to_dict()]
            return AgentResult(ok=True, summary="planned", spawned_tasks=spawned)
        return AgentResult(ok=True, summary="built")

    run_concurrent(repo, invoke, _gov(tmp_path), max_workers=4, max_steps=50, isolate=False)
    assert repo.get("p").status == TaskStatus.DONE
    assert repo.get("impl") is not None and repo.get("impl").status == TaskStatus.DONE


def test_a_crashing_invoke_does_not_lose_the_task(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="t", title="x", task_type="implement", project="p", max_retries=0))

    def invoke(_t: Task) -> AgentResult:
        raise RuntimeError("agent blew up")

    run_concurrent(repo, invoke, _gov(tmp_path), max_workers=2, max_steps=10, isolate=False)
    assert repo.get("t").status == TaskStatus.FAILED   # crash became a clean failure, not a hang/loss


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_pool_isolates_concurrent_same_project_and_merges(tmp_path: Path):
    """Two implement tasks in ONE project run concurrently in separate worktrees; both deliverables
    merge back into the project's main tree (the whole point of intra-project concurrency)."""
    proj_root = tmp_path / "projects"
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="t1", title="part one", task_type="implement", project="demo"))
    repo.create(Task(task_id="t2", title="part two", task_type="implement", project="demo"))

    def invoke(t: Task) -> AgentResult:
        wd = Path(t.payload["workdir"])               # the dispatcher gave each its own worktree
        (wd / f"{t.task_id}.py").write_text(f"# {t.task_id}\n", encoding="utf-8")
        return AgentResult(ok=True, summary="built")

    run_concurrent(repo, invoke, _gov(tmp_path), max_workers=4, max_steps=20,
                   projects_root=str(proj_root), isolate=True)
    assert repo.get("t1").status == TaskStatus.DONE and repo.get("t2").status == TaskStatus.DONE
    demo = proj_root / "demo"
    assert (demo / "t1.py").exists() and (demo / "t2.py").exists()   # both merged into main


def test_breaker_ignores_transient_failures(tmp_path: Path):
    """Quota weather is not a quality signal (14 Jul: six rate-limited hours filled the trailing
    window, so the breaker tripped the moment real work resumed). Transient failures must not
    feed the burn-rate breaker; genuine failures must. A rate-limited settle ends its batch, so
    the transient half drives one batch per settle (backoff injected as a no-op)."""
    gov = _gov(tmp_path)
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    for i in range(25):
        repo.create(Task(task_id=f"t{i}", title=f"t{i}", task_type="implement", project=f"P{i}"))

    def rate_limited(_t: Task) -> AgentResult:
        return AgentResult(ok=False, summary="limit",
                           cause="RateLimited: claude usage/rate limit: weekly limit reached")

    for _ in range(25):   # each batch settles one task then ends on the rate-limit signal
        run_concurrent(repo, rate_limited, gov, max_workers=1, max_steps=1,
                       isolate=False, project_cap=0, backoff=lambda: None)
    assert not gov.burn_paused(), "25 rate-limited settles must NOT trip the breaker"

    repo2 = TaskRepository(EventStore(tmp_path / "e2.log"))
    for i in range(40):
        repo2.create(Task(task_id=f"h{i}", title=f"h{i}", task_type="implement", project=f"Q{i}"))

    def hard_fail(_t: Task) -> AgentResult:
        return AgentResult(ok=False, summary="broken", cause="tests failed: assertion error")

    run_concurrent(repo2, hard_fail, gov, max_workers=4, max_steps=40,
                   isolate=False, project_cap=0, backoff=lambda: None)
    assert gov.burn_paused(), "40 genuine failures MUST trip the breaker"
