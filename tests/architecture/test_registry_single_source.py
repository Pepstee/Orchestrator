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
    # F5 anti-collusion: the judge must be a different provider from the builder.
    assert reg.AGENT_MODELS["judge"]["provider"] != reg.AGENT_MODELS["builder"]["provider"]
