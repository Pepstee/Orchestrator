"""Behavioural: the task lifecycle persists, replays (resume-from-step), and is transition-safe."""
from __future__ import annotations

from pathlib import Path

from core.models import AgentResult, Event, Task, TaskStatus
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def _task(tid: str = "t1") -> Task:
    return Task(task_id=tid, title="x", task_type="implement")


def test_lifecycle_persists(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(_task())
    repo.apply("t1", Event.CLAIM)
    assert repo.get("t1").status == TaskStatus.IN_PROGRESS
    repo.apply("t1", Event.COMPLETE)
    assert repo.get("t1").status == TaskStatus.DONE


def test_replay_reconstructs_state(tmp_path: Path):
    p = tmp_path / "e.log"
    repo = TaskRepository(EventStore(p))
    repo.create(_task())
    repo.apply("t1", Event.CLAIM)
    # simulate crash + restart: rebuild from the log alone
    repo2 = TaskRepository.replay(EventStore(p))
    assert repo2.get("t1").status == TaskStatus.IN_PROGRESS


def test_illegal_transition_is_noop(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(_task())  # QUEUED
    repo.apply("t1", Event.COMPLETE)  # illegal from QUEUED -> no-op, no crash
    assert repo.get("t1").status == TaskStatus.QUEUED


def test_queued_can_be_blocked(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(_task())
    repo.apply("t1", Event.BLOCK)  # the v1 bug, now legal
    assert repo.get("t1").status == TaskStatus.BLOCKED


def test_claim_next_caps_concurrency_per_project(tmp_path: Path):
    """With per_project_cap=1, a project that already has a task IN_PROGRESS yields no further claims,
    so two agents never edit one project tree at once (the merge-conflict thrash is structurally
    impossible). A different project is still claimable on the same cycle."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a1", title="x", task_type="implement", project="alpha"))
    repo.create(Task(task_id="a2", title="x", task_type="implement", project="alpha"))
    repo.create(Task(task_id="b1", title="x", task_type="implement", project="beta"))

    first = repo.claim_next(per_project_cap=1)
    assert first is not None and first.project == "alpha"
    # alpha is now busy: the cap skips a2 and hands out beta instead.
    second = repo.claim_next(per_project_cap=1)
    assert second is not None and second.task_id == "b1"
    # both projects busy -> nothing left to claim under the cap.
    assert repo.claim_next(per_project_cap=1) is None
    # free alpha; a2 becomes claimable again.
    repo.apply("a1", Event.COMPLETE)
    third = repo.claim_next(per_project_cap=1)
    assert third is not None and third.task_id == "a2"


def test_revive_transient_failures_requeues_only_transient(tmp_path: Path):
    """Boot revival returns a task FAILED for a TRANSIENT cause (provider limit / restart-kill) to
    QUEUED. A merge conflict is NOT transient — it must stay FAILED, never be revived into an unbounded
    loop (a conflict re-run burns a full agent each time and drained the budget once)."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="limited", title="x", task_type="implement", project="P"))
    repo.create(Task(task_id="conflict", title="y", task_type="implement", project="Q"))
    for tid, cause in [("limited", "claude usage limit: 5-hour limit reached"),
                       ("conflict", "merge conflict integrating conflict into Q")]:
        repo.apply(tid, Event.CLAIM)
        repo.record_result(tid, AgentResult(ok=False, summary="fail", cause=cause))
        repo.apply(tid, Event.FAIL)
    n = repo.revive_transient_failures()
    assert n == 1
    assert repo.get("limited").status == TaskStatus.QUEUED    # transient -> revived
    assert repo.get("conflict").status == TaskStatus.FAILED   # conflict -> stays terminal (no loop)


def test_claim_next_unbounded_cap_allows_many_per_project(tmp_path: Path):
    """per_project_cap=0 disables the cap: concurrent same-project claims are permitted (worktree
    isolation makes this safe), for operators who want intra-project parallelism."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a1", title="x", task_type="implement", project="alpha"))
    repo.create(Task(task_id="a2", title="x", task_type="implement", project="alpha"))
    assert repo.claim_next(per_project_cap=0) is not None
    assert repo.claim_next(per_project_cap=0) is not None  # same project, still claimable


def test_iter_results_is_chronological_and_read_only(tmp_path: Path):
    """iter_results yields every task_result in ledger order (F-001 reads this to find the last
    unresolved validate finding without collapsing to latest-per-task the way last_results does)."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(_task("t1"))
    repo.apply("t1", Event.CLAIM)
    repo.record_result("t1", AgentResult(ok=False, summary="fail", cause="finding one"))
    repo.apply("t1", Event.REQUEUE)
    repo.apply("t1", Event.CLAIM)
    repo.record_result("t1", AgentResult(ok=True, summary="pass"))
    rows = repo.iter_results()
    assert [r["ok"] for r in rows] == [False, True]           # both, in order (not collapsed)
    assert rows[0]["cause"] == "finding one" and rows[0]["task_id"] == "t1"
    # survives a restart (derived from the durable log)
    revived = TaskRepository.replay(EventStore(tmp_path / "e.log"))
    assert [r["ok"] for r in revived.iter_results()] == [False, True]
