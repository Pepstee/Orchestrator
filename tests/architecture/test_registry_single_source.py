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
    assert reg.AGENT_MODELS["judge"]["provider"] != reg.AGENT_MODELS["builder"]["provider"]


def test_env_override_reroutes_an_agent_reversibly(monkeypatch):
    # Provider-outage escape hatch: AGENTIC_<AGENT>="provider:model" reroutes one agent, no code edit.
    monkeypatch.setenv("AGENTIC_JUDGE", "claude:opus")
    assert reg.model_for("judge") == {"provider": "claude", "model": "opus"}
    monkeypatch.delenv("AGENTIC_JUDGE")
    assert reg.model_for("judge") == reg.AGENT_MODELS["judge"]   # default restored (still cross-provider)


def test_overseer_ladder_is_sol_then_opus():
    # Phase 2 live (18 Jul 2026, Fable walled 19 Jul): exec Sol via codex, deputy Opus —
    # cross-provider both ways so neither provider's outage darks the pulse.
    ladder = reg.model_ladder("overseer")
    assert ladder[0] == reg.AGENT_MODELS["overseer"]        # rung 0 = exec = Sol
    assert ladder[0] == {"provider": "openai", "model": "gpt-5.6-sol"}
    assert ladder[1] == {"provider": "claude", "model": "opus"}   # cross-provider deputy


def test_model_ladder_pin_disables_fallback(monkeypatch):
    monkeypatch.setenv("AGENTIC_OVERSEER", "claude:opus")
    assert reg.model_ladder("overseer") == [{"provider": "claude", "model": "opus"}]
    monkeypatch.delenv("AGENTIC_OVERSEER")
    assert len(reg.model_ladder("overseer")) == 2           # ladder restored (Sol -> Opus)
