"""Behavioural: the failure ladder — PA fast-path -> retry -> escalate (all bounded, L6)."""
from __future__ import annotations

from pathlib import Path

from core.models import AgentResult, Task, TaskStatus
from dispatch.dispatcher import run_until_idle
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def _repo(tmp_path: Path) -> TaskRepository:
    return TaskRepository(EventStore(tmp_path / "e.log"))


def _fail(_task: Task) -> AgentResult:
    return AgentResult(ok=False, summary="nope", cause="boom")


def _escalations(tmp_path: Path) -> list[dict]:
    return [e.data for e in EventStore(str(tmp_path / "e.log")).replay() if e.kind == "escalation"]


def test_retries_then_escalates(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="t", title="t", task_type="implement", max_retries=2))
    run_until_idle(repo, _fail)
    assert repo.get("t").status == TaskStatus.FAILED
    assert repo.get("t").retries == 2                       # retried max_retries times, then gave up
    assert _escalations(tmp_path)[-1]["reason"] == "retries exhausted"


def test_pa_requeue_overrides_retry_budget(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="t", title="t", task_type="implement", max_retries=0))
    # PA classifies the cause as transient -> requeue regardless of the (zero) retry budget;
    # the only thing that stops it is the max_steps bound (L6 — no rung can self-amplify).
    n = run_until_idle(repo, _fail, max_steps=3, pa_consult=lambda _c: "requeue")
    assert n == 3 and repo.get("t").status == TaskStatus.QUEUED


def test_pa_escalate_skips_retry(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="t", title="t", task_type="implement", max_retries=5))
    run_until_idle(repo, _fail, pa_consult=lambda _c: "escalate")
    assert repo.get("t").status == TaskStatus.FAILED        # PA escalated at once — no retries burnt
    assert repo.get("t").retries == 0
    assert _escalations(tmp_path)[-1]["reason"] == "pa:escalate"


def test_pa_no_match_falls_through_to_retry(tmp_path: Path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="t", title="t", task_type="implement", max_retries=1))
    run_until_idle(repo, _fail, pa_consult=lambda _c: None)  # PA abstains -> ordinary ladder
    assert repo.get("t").status == TaskStatus.FAILED and repo.get("t").retries == 1
