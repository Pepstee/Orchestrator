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


# The exact wordings Claude emits when the Max window is exhausted — these MUST be recognised, or a
# limit would be mistaken for a hard failure (retried + escalated) instead of self-resolving.
_REAL_LIMIT_MESSAGES = [
    "5-hour limit reached ∙ resets 5am",          # the dot-separator CLI form
    "5-hour limit reached - resets 5am",
    "Claude AI usage limit reached, please try again after 3pm",
    "weekly limit reached",
    "API error 429: too many requests",
    "overloaded_error",
]


def test_real_limit_messages_detected_at_both_layers():
    from dispatch.dispatcher import is_rate_limited
    from infra.llm import _looks_rate_limited
    for msg in _REAL_LIMIT_MESSAGES:
        assert _looks_rate_limited(msg), f"infra missed: {msg}"
        result = AgentResult(ok=False, summary="x", cause=f"RuntimeError: claude exited 1: {msg}")
        assert is_rate_limited(result), f"dispatcher missed: {msg}"


def test_ordinary_failure_is_not_mistaken_for_a_limit():
    from dispatch.dispatcher import is_rate_limited
    for cause in ("AssertionError: expected 5 got 4", "ModuleNotFoundError: no module named foo",
                  "recursion depth exceeded"):
        assert not is_rate_limited(AgentResult(ok=False, summary="x", cause=cause)), cause


def test_bare_5h_limit_self_resolves(tmp_path: Path):
    """The bare '5-hour limit' message (no 'rate limit'/'usage limit' phrase) must still requeue +
    back off, not fail — this is the case the old hint list missed."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="t", title="t", task_type="implement", max_retries=3))
    gov = BudgetGovernor(EventStore(tmp_path / "b.log"), cap_usd=0.0, kill_switch_path=tmp_path / "KILL")
    backoffs = {"n": 0}

    def invoke(_t: Task) -> AgentResult:
        return AgentResult(ok=False, summary="limited",
                           cause="RuntimeError: claude exited 1: 5-hour limit reached ∙ resets 5am")

    run_loop(repo, invoke, gov, max_steps=10, backoff=lambda: backoffs.__setitem__("n", backoffs["n"] + 1))
    assert backoffs["n"] == 1
    assert repo.get("t").status == TaskStatus.QUEUED and repo.get("t").retries == 0


def test_keyboardinterrupt_requeues_not_escalates(tmp_path: Path):
    """A task killed mid-run by a daemon restart (KeyboardInterrupt) is a restart casualty, NOT a
    defect — it must requeue, never fail or escalate (the cause of the phantom 'needs you' flood)."""
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="t", title="t", task_type="implement", max_retries=3))
    gov = BudgetGovernor(EventStore(tmp_path / "b.log"), cap_usd=0.0, kill_switch_path=tmp_path / "KILL")

    def invoke(_t: Task) -> AgentResult:
        return AgentResult(ok=False, summary="killed",
                           cause='Traceback ... selectors.py line 416 ... KeyboardInterrupt')

    run_loop(repo, invoke, gov, max_steps=2, backoff=lambda: None)
    assert repo.get("t").status == TaskStatus.QUEUED   # requeued, not failed/escalated
    assert repo.get("t").retries == 0                  # no penalty
    escalations = [e for e in EventStore(str(tmp_path / "e.log")).replay() if e.kind == "escalation"]
    assert not escalations                             # never escalated to the user
