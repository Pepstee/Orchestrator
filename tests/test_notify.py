"""Behavioural: notifications are best-effort and never crash the caller."""
from __future__ import annotations

from infra.notify import notify


def test_notify_never_raises_and_returns_bool():
    result = notify("Orchestrator", 'a project "demo" is ready')   # quotes must not break it
    assert isinstance(result, bool)
