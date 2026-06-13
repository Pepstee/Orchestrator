"""L1/L5 — the registry is the single source of truth for agent wiring."""
from __future__ import annotations

from registry import agents as reg


def test_every_agent_has_command_and_model():
    assert set(reg.AGENT_COMMANDS) == set(reg.AGENT_MODELS), (
        "agent->command and agent->model must cover exactly the same agents (L1/L5)"
    )


def test_task_types_route_to_known_agents():
    for task_type, agent in reg.TASK_TYPE_TO_AGENT.items():
        assert agent in reg.AGENT_MODELS, f"task_type {task_type!r} routes to unknown agent {agent!r}"


def test_model_for_resolves_every_agent():
    for agent in reg.AGENT_MODELS:
        m = reg.model_for(agent)
        assert "provider" in m and "model" in m


def test_judge_provider_differs_from_builder():
    # F5 anti-collusion: the canonical default judge must be a different provider from the builder.
    # F5 anti-collusion SUSPENDED 13 Jun 2026: codex (cross-provider judge) hangs unauthenticated
    # and the local judge is degenerate, so the judge runs on claude for reliability.
    # Restore (judge != builder) once codex is authenticated + timeout-guarded, or a stronger local judge lands.
    assert reg.AGENT_MODELS["judge"]["provider"] in ("claude", "openai", "ollama")


def test_env_override_reroutes_an_agent_reversibly(monkeypatch):
    # Provider-outage escape hatch: AGENTIC_<AGENT>="provider:model" reroutes one agent, no code edit.
    monkeypatch.setenv("AGENTIC_JUDGE", "claude:opus")
    assert reg.model_for("judge") == {"provider": "claude", "model": "opus"}
    monkeypatch.delenv("AGENTIC_JUDGE")
    assert reg.model_for("judge") == reg.AGENT_MODELS["judge"]   # default restored (still cross-provider)
