"""Behavioural: crash/restart recovery — orphaned in-progress tasks are reclaimed, not lost."""
from __future__ import annotations

from pathlib import Path

from control.budget import BudgetGovernor
from control.loop import run as run_loop
from core.models import AgentResult, Event, Task, TaskStatus
from dispatch.dispatcher import propagate_prerequisite_failures, run_until_idle
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def test_reclaim_requeues_orphaned_in_progress(tmp_path: Path):
    log = tmp_path / "e.log"
    repo = TaskRepository(EventStore(log))
    repo.create(Task(task_id="t", title="x", task_type="implement"))
    repo.apply("t", Event.CLAIM)                       # IN_PROGRESS, then the daemon "dies"

    restarted = TaskRepository.replay(EventStore(log))  # a fresh daemon replays the log
    assert restarted.get("t").status == TaskStatus.IN_PROGRESS   # orphaned by the restart
    assert restarted.reclaim_orphans() == 1
    assert restarted.get("t").status == TaskStatus.QUEUED        # re-queued -> will run again


def test_reclaim_is_a_noop_with_nothing_in_flight(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a", title="a", task_type="implement"))
    repo.apply("a", Event.CLAIM)
    repo.apply("a", Event.COMPLETE)                    # terminal, not in-flight
    assert repo.reclaim_orphans() == 0
    assert repo.get("a").status == TaskStatus.DONE


def _fail(_t: Task) -> AgentResult:
    return AgentResult(ok=False, summary="nope", cause="boom")


def test_prerequisite_failure_cascades_transitively(tmp_path: Path):
    """A fails -> B (dep A) and C (dep B) can never run; they must cascade to FAILED, not strand the
    project as non-terminal forever (the overnight-run stall)."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a", title="a", task_type="implement", max_retries=0))
    repo.create(Task(task_id="b", title="b", task_type="implement", depends_on=["a"]))
    repo.create(Task(task_id="c", title="c", task_type="validate", depends_on=["b"]))
    run_until_idle(repo, _fail)                        # a fails; run_until_idle then cascades
    assert repo.get("a").status == TaskStatus.FAILED
    assert repo.get("b").status == TaskStatus.FAILED   # cascaded
    assert repo.get("c").status == TaskStatus.FAILED   # cascaded transitively
    # the cascade is self-explaining (L10)
    causes = [e.data["cause"] for e in EventStore(str(tmp_path / "e.log")).replay()
              if e.kind == "task_result" and not e.data.get("ok") and "prerequisite" in str(e.data.get("cause"))]
    assert causes


def test_propagate_leaves_healthy_graphs_untouched(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="x", title="x", task_type="implement"))   # QUEUED, no failed deps
    assert propagate_prerequisite_failures(repo) == 0
    assert repo.get("x").status == TaskStatus.QUEUED


def test_rate_limit_backs_off_and_requeues_without_penalty(tmp_path: Path):
    """A provider usage/rate limit must NOT fail or escalate the task — it requeues unpenalised, the
    loop backs off, and the batch ends (no hammering). Resumes next cycle when the window resets."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="t", title="t", task_type="implement", max_retries=3))
    gov = BudgetGovernor(EventStore(tmp_path / "b.log"), cap_usd=0.0, kill_switch_path=tmp_path / "KILL")
    calls = {"invoke": 0, "backoff": 0}

    def invoke(_t: Task) -> AgentResult:
        calls["invoke"] += 1
        return AgentResult(ok=False, summary="limited", cause="RateLimited: claude usage/rate limit: resets at ...")

    run_loop(repo, invoke, gov, max_steps=10, backoff=lambda: calls.__setitem__("backoff", calls["backoff"] + 1))

    assert calls["backoff"] == 1                       # backed off once
    assert calls["invoke"] == 1                        # ended the batch — did NOT hammer the limited API
    assert repo.get("t").status == TaskStatus.QUEUED   # requeued, not failed/escalated
    assert repo.get("t").retries == 0                  # no retry penalty for a transient limit
