"""L8 — the supervised run loop: ingests the inbox, processes ready work, stops cleanly."""
from __future__ import annotations

from pathlib import Path

from control.budget import BudgetGovernor
from control.daemon import serve
from control.inbox import drop
from core.models import AgentResult, Task, TaskStatus
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def _ok(_task: Task) -> AgentResult:
    return AgentResult(ok=True, summary="ok")


def _gov(tmp_path: Path, cap: float = 0.0) -> BudgetGovernor:
    return BudgetGovernor(EventStore(tmp_path / "b.log"), cap_usd=cap, kill_switch_path=tmp_path / "KILL")


def _all_terminal(repo: TaskRepository) -> bool:
    tasks = repo.list()
    return bool(tasks) and all(t.status in (TaskStatus.DONE, TaskStatus.FAILED) for t in tasks)


def test_serve_processes_ready_tasks_then_stops(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a", title="a", task_type="implement", project="p"))
    repo.create(Task(task_id="b", title="b", task_type="validate", depends_on=["a"], project="p"))
    total = serve(repo, _gov(tmp_path), _ok, should_stop=lambda: _all_terminal(repo),
                  poll_interval=0, inbox=str(tmp_path / "inbox"),
                  projects_root=str(tmp_path / "projects"))
    assert total == 2
    assert repo.get("a").status == TaskStatus.DONE and repo.get("b").status == TaskStatus.DONE


def test_serve_stops_immediately_when_asked(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a", title="a", task_type="implement", project="p"))
    total = serve(repo, _gov(tmp_path), _ok, should_stop=lambda: True,
                  poll_interval=0, inbox=str(tmp_path / "inbox"),
                  projects_root=str(tmp_path / "projects"))
    assert total == 0
    assert repo.get("a").status == TaskStatus.QUEUED   # never ran


def test_serve_halts_on_kill_switch(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a", title="a", task_type="implement", project="p"))
    gov = _gov(tmp_path, cap=100.0)
    gov.engage_kill_switch("operator stop")
    total = serve(repo, gov, _ok, should_stop=lambda: gov.should_stop()[0],
                  poll_interval=0, inbox=str(tmp_path / "inbox"),
                  projects_root=str(tmp_path / "projects"))
    assert total == 0


def test_serve_ingests_inbox_then_runs(tmp_path: Path):
    # the live-enqueue path: a task dropped in the inbox is ingested by the running loop
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    inbox = tmp_path / "inbox"
    drop(Task(task_id="t1", title="x", task_type="implement", project="p"), inbox)
    total = serve(repo, _gov(tmp_path), _ok, should_stop=lambda: _all_terminal(repo),
                  poll_interval=0, inbox=str(inbox),
                  projects_root=str(tmp_path / "projects"))
    assert total == 1 and repo.get("t1").status == TaskStatus.DONE


# ---- AGENTIC_DEADLINE_HOURS: the strictly bounded run (self-written STOP at expiry) ----

def test_deadline_writes_stop_once_and_stays_true(tmp_path):
    from control.daemon import deadline_should_stop
    calls, st, boot = [], {}, 1000.0

    def notifier(_title, message):
        calls.append(message)
    assert not deadline_should_stop(tmp_path, st, boot=boot, hours=10,
                                    now=boot + 9.9 * 3600, notifier=notifier)
    assert not (tmp_path / "STOP").exists()
    assert deadline_should_stop(tmp_path, st, boot=boot, hours=10,
                                now=boot + 10 * 3600 + 1, notifier=notifier)
    assert (tmp_path / "STOP").exists(), "a self-chosen stop must stay stopped (supervisor reads it)"
    assert len(calls) == 1 and "deadline" in calls[0]
    assert deadline_should_stop(tmp_path, st, boot=boot, hours=10,
                                now=boot + 11 * 3600, notifier=notifier)
    assert len(calls) == 1, "notify once, not every poll"


def test_zero_deadline_means_unbounded(tmp_path):
    from control.daemon import deadline_should_stop
    assert not deadline_should_stop(tmp_path, {}, boot=0.0, hours=0, now=1e12)
    assert not (tmp_path / "STOP").exists()


def test_overseer_intervention_cap_is_env_tunable(monkeypatch):
    # The bound must exist (L6) but the number belongs to the operator (10 Jul: v3 abandoned
    # after 3 PRODUCTIVE interventions). Floor of 1 keeps the ladder terminating.
    import importlib

    import control.daemon as daemon_module
    monkeypatch.setenv("AGENTIC_MAX_OVERSEER_INTERVENTIONS", "7")
    importlib.reload(daemon_module)
    assert daemon_module.MAX_OVERSEER_INTERVENTIONS == 7
    monkeypatch.setenv("AGENTIC_MAX_OVERSEER_INTERVENTIONS", "0")
    importlib.reload(daemon_module)
    assert daemon_module.MAX_OVERSEER_INTERVENTIONS == 1
    monkeypatch.delenv("AGENTIC_MAX_OVERSEER_INTERVENTIONS")
    importlib.reload(daemon_module)
    assert daemon_module.MAX_OVERSEER_INTERVENTIONS == 3


def test_quiet_gate_defers_pulses_but_never_three_in_a_row(tmp_path, monkeypatch):
    # Cost-audit C-001: a frozen ledger defers the observe (journalled, heartbeat ticking);
    # the third interval fires regardless, so the guardian never goes silent for >3 intervals.
    from control.daemon import tick_overseer_session
    from dispatch.repository import TaskRepository
    from infra.event_store import EventStore
    from memory.overseer import start_session

    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    (tmp_path / "tasks.events.log").write_text("x" * 1000, encoding="utf-8")
    session_path = tmp_path / "overseer_session.json"
    handoff = tmp_path / "handoff_latest.md"
    start_session(session_path, now=1000.0)
    meta: dict = {"last_pulse": 1000.0, "pulse_log_size": 1000}

    def oversee_count():
        return len([t for t in repo.list() if t.task_type == "oversee"])

    tick_overseer_session(repo, session_path, handoff, meta, now=1000.0 + 3601, pulse_interval=3600)
    assert oversee_count() == 0 and meta["quiet_skips"] == 1, "first quiet interval defers"
    tick_overseer_session(repo, session_path, handoff, meta, now=1000.0 + 7202, pulse_interval=3600)
    assert oversee_count() == 0 and meta["quiet_skips"] == 2, "second quiet interval defers"
    tick_overseer_session(repo, session_path, handoff, meta, now=1000.0 + 10803, pulse_interval=3600)
    assert oversee_count() == 1, "third interval fires even on a quiet ledger"
    assert meta["quiet_skips"] == 0
    journal = tmp_path / "overseer" / "journal.jsonl"
    assert journal.exists() and journal.read_text().count('"mode": "deferred"') == 2


def test_moving_ledger_never_defers(tmp_path):
    from control.daemon import tick_overseer_session
    from dispatch.repository import TaskRepository
    from infra.event_store import EventStore
    from memory.overseer import start_session

    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    log = tmp_path / "tasks.events.log"
    log.write_text("x" * 1000, encoding="utf-8")
    session_path = tmp_path / "overseer_session.json"
    start_session(session_path, now=1000.0)
    meta: dict = {"last_pulse": 1000.0, "pulse_log_size": 100}   # ledger grew 900B since
    tick_overseer_session(repo, session_path, tmp_path / "h.md", meta,
                          now=1000.0 + 3601, pulse_interval=3600)
    assert len([t for t in repo.list() if t.task_type == "oversee"]) == 1


def test_rate_limit_backoff_escalates_and_resets():
    from control.loop import ExponentialBackoff
    slept = []
    b = ExponentialBackoff(base=300, cap=1800, sleep=slept.append)
    b(); b(); b(); b()
    assert slept == [300, 600, 1200, 1800]
    b()
    assert slept[-1] == 1800, "capped"
    b.reset(); b()
    assert slept[-1] == 300, "reset restores the base"
