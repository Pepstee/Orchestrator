"""BG-3 — failure budgets are durable and every requeue path is finite.

The two pathologies these tests pin down, from the June burn (docs/planning/09, E1–E2):
1. unbounded 'no-penalty' requeues — one misclassified cause could loop a task forever;
2. restart laundering — in-memory retry counters reset on replay, so a restart refilled
   every budget. Counters now derive from the durable result log.
"""
from __future__ import annotations

from core.models import AgentResult, Event, Task, TaskStatus
from dispatch.dispatcher import settle
from dispatch.repository import MAX_TRANSIENT_REQUEUES, TaskRepository
from infra.event_store import EventStore

TRANSIENT_CAUSE = "provider rate limit hit (429) — try again later"
HARD_CAUSE = "tests failed: 3 assertions in test_core.py"


def _fail(cause: str) -> AgentResult:
    return AgentResult(ok=False, summary="failed", cause=cause)


def _run_failure(repo: TaskRepository, task: Task, cause: str) -> None:
    """One driver round: claim, record the failure durably, settle through the ladder."""
    repo.apply(task.task_id, Event.CLAIM)
    repo.record_result(task.task_id, _fail(cause))
    settle(repo, task, _fail(cause))


def test_transient_requeues_are_finite(tmp_path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    task = repo.create(Task(task_id="t1", title="x", task_type="implement", project="alpha"))
    rounds = 0
    while repo.get("t1").status != TaskStatus.FAILED and rounds < 30:
        _run_failure(repo, task, TRANSIENT_CAUSE)
        rounds += 1
    assert repo.get("t1").status == TaskStatus.FAILED, "a transient cause must not loop forever"
    # Budget shape: MAX_TRANSIENT_REQUEUES no-penalty rounds, then the bounded ordinary ladder.
    assert rounds <= MAX_TRANSIENT_REQUEUES + task.max_retries + 2


def test_hard_failures_terminate_within_max_retries(tmp_path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    task = repo.create(Task(task_id="t1", title="x", task_type="implement", project="alpha"))
    rounds = 0
    while repo.get("t1").status != TaskStatus.FAILED and rounds < 10:
        _run_failure(repo, task, HARD_CAUSE)
        rounds += 1
    assert repo.get("t1").status == TaskStatus.FAILED
    assert rounds == task.max_retries + 1   # 3 retries then terminal


def test_restart_cannot_launder_the_budget(tmp_path):
    store_path = tmp_path / "e.log"
    repo = TaskRepository(EventStore(store_path))
    task = repo.create(Task(task_id="t1", title="x", task_type="implement", project="alpha"))
    for _ in range(task.max_retries + 1):   # exhaust the hard budget, durably
        repo.apply(task.task_id, Event.CLAIM)
        repo.record_result(task.task_id, _fail(HARD_CAUSE))
        repo.apply(task.task_id, Event.REQUEUE)
    # restart: rebuild from the log alone — in-memory retries is back to its creation value
    revived = TaskRepository.replay(EventStore(store_path))
    t = revived.get("t1")
    assert t.retries == 0, "precondition: replay resets the in-memory counter (the old hole)"
    assert revived.hard_failure_count("t1") == task.max_retries + 1
    revived.apply("t1", Event.CLAIM)
    revived.record_result("t1", _fail(HARD_CAUSE))
    settle(revived, t, _fail(HARD_CAUSE))
    assert revived.get("t1").status == TaskStatus.FAILED, (
        "after restart the durable budget must still be exhausted — no laundering"
    )


CONFLICT_CAUSE = "merge conflict integrating t1 into alpha (a concurrent task changed the same lines)"


def _run_conflict(repo: TaskRepository, task: Task, base_state: str) -> None:
    repo.apply(task.task_id, Event.CLAIM)
    repo.record_result(task.task_id, _fail(CONFLICT_CAUSE))
    settle(repo, task, _fail(CONFLICT_CAUSE), base_state=base_state)


def test_identical_deterministic_reattempt_refused(tmp_path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    task = repo.create(Task(task_id="t1", title="x", task_type="implement", project="alpha"))
    _run_conflict(repo, task, base_state="rev-A")
    assert repo.get("t1").status == TaskStatus.QUEUED, "first conflict: retry permitted"
    _run_conflict(repo, task, base_state="rev-A")
    assert repo.get("t1").status == TaskStatus.FAILED, (
        "same inputs, same base — the re-attempt must be refused, not re-run (BG-3)"
    )


def test_rebase_changes_inputs_and_permits_reattempt(tmp_path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    task = repo.create(Task(task_id="t1", title="x", task_type="implement", project="alpha"))
    _run_conflict(repo, task, base_state="rev-A")
    _run_conflict(repo, task, base_state="rev-B")   # base moved (rebase/merge happened)
    assert repo.get("t1").status == TaskStatus.QUEUED, "changed base — retry permitted"
    _run_conflict(repo, task, base_state="rev-B")
    assert repo.get("t1").status == TaskStatus.FAILED


def test_fingerprint_survives_restart(tmp_path):
    store_path = tmp_path / "e.log"
    repo = TaskRepository(EventStore(store_path))
    task = repo.create(Task(task_id="t1", title="x", task_type="implement", project="alpha"))
    _run_conflict(repo, task, base_state="rev-A")
    revived = TaskRepository.replay(EventStore(store_path))
    t = revived.get("t1")
    revived.apply("t1", Event.CLAIM)
    revived.record_result("t1", _fail(CONFLICT_CAUSE))
    settle(revived, t, _fail(CONFLICT_CAUSE), base_state="rev-A")
    assert revived.get("t1").status == TaskStatus.FAILED, (
        "the fingerprint is durable — a restart must not permit the identical re-attempt"
    )


def test_stochastic_failures_keep_the_ordinary_budget(tmp_path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    task = repo.create(Task(task_id="t1", title="x", task_type="implement", project="alpha"))
    rounds = 0
    while repo.get("t1").status != TaskStatus.FAILED and rounds < 10:
        repo.apply(task.task_id, Event.CLAIM)
        repo.record_result(task.task_id, _fail(HARD_CAUSE))
        settle(repo, task, _fail(HARD_CAUSE), base_state="rev-A")
        rounds += 1
    assert rounds == task.max_retries + 1, (
        "non-deterministic causes must keep their full retry budget despite a fixed base"
    )


def test_revival_respects_the_transient_budget(tmp_path):
    store_path = tmp_path / "e.log"
    repo = TaskRepository(EventStore(store_path))
    under = repo.create(Task(task_id="u1", title="u", task_type="implement", project="alpha"))
    over = repo.create(Task(task_id="o1", title="o", task_type="implement", project="alpha"))
    repo.apply(under.task_id, Event.CLAIM)
    repo.record_result(under.task_id, _fail(TRANSIENT_CAUSE))
    repo.cancel_task(under.task_id)   # leave it FAILED with a transient last cause
    for _ in range(MAX_TRANSIENT_REQUEUES + 1):
        repo.apply(over.task_id, Event.CLAIM)
        repo.record_result(over.task_id, _fail(TRANSIENT_CAUSE))
        repo.apply(over.task_id, Event.REQUEUE)
    repo.cancel_task(over.task_id)
    revived = TaskRepository.replay(EventStore(store_path))
    revived.revive_transient_failures()
    assert revived.get("u1").status == TaskStatus.QUEUED, "under budget — revive"
    assert revived.get("o1").status == TaskStatus.FAILED, "over budget — stays terminal"
