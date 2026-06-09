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


# ---- burn-rate breaker (09 hard floor; the 52-vs-1513 lesson) ----

def _governor(tmp_path, name="b.log"):
    from infra.event_store import EventStore
    from control.budget import BudgetGovernor
    return BudgetGovernor(EventStore(tmp_path / name), cap_usd=0.0,
                          kill_switch_path=tmp_path / "KILL")


def test_burn_breaker_trips_on_collapsed_ratio(tmp_path):
    g = _governor(tmp_path)
    t = 1000.0
    for i in range(20):
        g.record_outcome(i < 5, now=t)          # 5 ok / 15 failed = 25% < 40%
    assert g.burn_paused(now=t + 1)
    assert not g.burn_paused(now=t + g.BURN_PAUSE_SECONDS + 1), "pause expires"


def test_burn_breaker_never_judges_a_small_sample(tmp_path):
    g = _governor(tmp_path)
    for _ in range(g.BURN_MIN_RUNS - 1):
        g.record_outcome(False, now=1000.0)
    assert not g.burn_paused(now=1001.0)


def test_burn_breaker_ignores_healthy_ratios(tmp_path):
    g = _governor(tmp_path)
    for i in range(40):
        g.record_outcome(i % 2 == 0, now=1000.0)   # 50% >= 40%
    assert not g.burn_paused(now=1001.0)


def test_burn_pause_survives_restart(tmp_path):
    g = _governor(tmp_path)
    t = 1000.0
    for _ in range(20):
        g.record_outcome(False, now=t)
    assert g.burn_paused(now=t + 1)
    g2 = _governor(tmp_path)                       # replay from the same store
    assert g2.burn_paused(now=t + 1), "a restart must not clear the pause"


def test_daemon_wires_the_breaker_into_the_allowance():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "control" / "daemon.py").read_text(encoding="utf-8")
    assert "governor.burn_paused()" in src and "breadth_allowance(repo, flagship)" in src
