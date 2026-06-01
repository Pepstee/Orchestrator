"""Behavioural: bounded autonomy (L6) — the loop halts on cap, kill-switch, or max_steps."""
from __future__ import annotations

from pathlib import Path

from control.budget import BudgetGovernor
from control.loop import run
from core.models import AgentResult, Task, TaskStatus
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def _cost(c: float):
    def invoke(_task: Task) -> AgentResult:
        return AgentResult(ok=True, summary="ok", metadata={"cost_usd": c})
    return invoke


def _gov(tmp_path: Path, cap: float) -> BudgetGovernor:
    return BudgetGovernor(EventStore(tmp_path / "spend.log"), cap_usd=cap,
                          kill_switch_path=tmp_path / "KILL")


def test_charges_and_exhausts(tmp_path: Path):
    g = _gov(tmp_path, 1.0)
    g.charge(0.6)
    assert not g.exhausted()
    g.charge(0.5)
    assert g.exhausted() and g.should_stop()[0]


def test_budget_persists_across_restart(tmp_path: Path):
    p = tmp_path / "spend.log"
    BudgetGovernor(EventStore(p), cap_usd=5.0, kill_switch_path=tmp_path / "KILL").charge(2.0)
    g2 = BudgetGovernor(EventStore(p), cap_usd=5.0, kill_switch_path=tmp_path / "KILL")
    assert abs(g2.spent() - 2.0) < 1e-9


def test_kill_switch_halts_loop(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="t1", title="x", task_type="implement"))
    g = _gov(tmp_path, 100.0)
    g.engage_kill_switch("operator stop")
    assert run(repo, _cost(0.1), g) == 0
    assert repo.get("t1").status == TaskStatus.QUEUED


def test_budget_exhaustion_halts_loop(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    repo.create(Task(task_id="a", title="a", task_type="implement"))
    repo.create(Task(task_id="b", title="b", task_type="implement"))
    g = _gov(tmp_path, 0.5)
    assert run(repo, _cost(0.6), g) == 1   # first task exhausts the cap, second never runs
    assert repo.get("b").status == TaskStatus.QUEUED
    assert g.kill_switch_engaged()          # exhaustion engaged the kill-switch


def test_max_steps_caps_loop(tmp_path: Path):
    repo = TaskRepository(EventStore(tmp_path / "e.log"))
    for i in range(5):
        repo.create(Task(task_id=f"t{i}", title="x", task_type="implement"))
    g = _gov(tmp_path, 0.0)   # cap 0 = unlimited; only max_steps bounds the loop
    assert run(repo, _cost(0.0), g, max_steps=2) == 2
