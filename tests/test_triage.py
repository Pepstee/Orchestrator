"""The failure taxonomy (infra.triage, ported from v1 — manifest row B1)."""
from __future__ import annotations

from core.models import AgentResult, Event, Task, TaskStatus
from dispatch.dispatcher import settle
from dispatch.repository import TaskRepository
from infra.event_store import EventStore
from infra.triage import ErrorClass, classify, is_input_deterministic, is_transient_cause


def test_rate_limits_and_restart_kills_are_transient():
    assert classify("provider rate limit hit (429)")[0] is ErrorClass.TRANSIENT
    assert classify("claude exited 1 — 5-hour limit reached ∙ resets 5am")[0] is ErrorClass.TRANSIENT
    assert classify("KeyboardInterrupt")[0] is ErrorClass.TRANSIENT


def test_environment_faults_are_transient():
    assert classify("subprocess.TimeoutExpired: command timed out after 600s")[0] is ErrorClass.TRANSIENT
    assert classify("fatal: .git/index.lock exists — failed to lock")[0] is ErrorClass.TRANSIENT
    assert classify("OSError: no space left on device")[0] is ErrorClass.TRANSIENT
    assert classify("ConnectionError: connection reset by peer")[0] is ErrorClass.TRANSIENT


def test_deterministic_cli_errors_are_permanent():
    cause = "RuntimeError: claude exited 2: error: unknown option '--modle'"
    assert classify(cause)[0] is ErrorClass.PERMANENT
    assert classify("claude exited 1: error: invalid model 'sonnnet'")[0] is ErrorClass.PERMANENT
    assert classify("prerequisite failed: ['abc123']")[0] is ErrorClass.PERMANENT
    assert classify("abandoned by overseer: hopeless")[0] is ErrorClass.PERMANENT


def test_default_is_recoverable_never_discarded():
    assert classify("tests failed: 3 assertions")[0] is ErrorClass.RECOVERABLE
    assert classify("")[0] is ErrorClass.RECOVERABLE
    # a project's own output mentioning an option must not read as a CLI error
    assert classify("FAILED tests/test_cli.py — prints 'unknown option' help text")[0] \
        is ErrorClass.RECOVERABLE


def test_merge_conflicts_are_recoverable_and_input_deterministic():
    cause = "merge conflict integrating t1 into alpha (a concurrent task changed the same lines)"
    assert classify(cause)[0] is ErrorClass.RECOVERABLE
    assert is_input_deterministic(cause)
    assert not is_input_deterministic("tests failed: 3 assertions")
    assert is_transient_cause(cause) is False


def test_ladder_fails_permanent_fast_without_burning_retries(tmp_path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    task = repo.create(Task(task_id="t1", title="x", task_type="implement", project="alpha"))
    repo.apply(task.task_id, Event.CLAIM)
    bad = AgentResult(ok=False, summary="boom",
                      cause="claude exited 2: error: unknown option '--modle'")
    repo.record_result(task.task_id, bad)
    settle(repo, task, bad)
    assert repo.get("t1").status == TaskStatus.FAILED
    assert task.retries == 0, "permanent causes must not consume the retry budget"
