"""Behavioural: the confirmation surface — the pending tray and the user-gate confirm flow."""
from __future__ import annotations

from pathlib import Path

from control.confirm import ingest_confirmations, pending, project_states, request_confirmation
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def test_pending_lists_only_unconfirmed_finalised(tmp_path: Path):
    log = str(tmp_path / "e.log")
    repo = TaskRepository(EventStore(log))
    repo.record_project_status("demo", gates={"user": False}, pending_user=True)
    repo.record_project_status("other", gates={}, pending_user=False)   # not finalised -> not in tray
    assert pending(EventStore(log)) == ["demo"]


def test_request_drops_a_signal(tmp_path: Path):
    cdir = tmp_path / "conf"
    request_confirmation("demo", cdir)
    assert (cdir / "demo.json").exists()


def test_confirm_flow_clears_the_tray(tmp_path: Path):
    log = str(tmp_path / "e.log")
    cdir = tmp_path / "conf"
    repo = TaskRepository(EventStore(log))
    repo.record_project_status("demo", gates={}, pending_user=True)
    assert pending(EventStore(log)) == ["demo"]

    request_confirmation("demo", cdir)
    assert ingest_confirmations(repo, cdir) == 1          # daemon applies the signal
    assert not (cdir / "demo.json").exists()              # signal consumed

    assert pending(EventStore(log)) == []                 # confirmed -> no longer pending
    assert project_states(EventStore(log))["demo"]["confirmed"]


def test_project_states_reflects_hardening(tmp_path: Path):
    log = str(tmp_path / "e.log")
    repo = TaskRepository(EventStore(log))
    repo.record_project_status("demo", gates={}, pending_user=True)
    repo.record_assurance("demo", fully_hardened=True, reason="all tiers passed (fully hardened)")
    state = project_states(EventStore(log))["demo"]
    assert state["hardened"] and "fully hardened" in state["assurance_reason"]
