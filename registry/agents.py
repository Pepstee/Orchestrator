"""registry.agents — the SINGLE SOURCE OF TRUTH for agent wiring (laws L1, L5).

Nothing is arbitrary: every agent's launch command and model are declared here, once.
Agents resolve their model from this module; the `reported == chosen` runtime check
(added when the agent runner lands) fails the build if a running agent drifts off it.

Roster: 5 agents + the meta-agent (Overseer). Everything else is a function/tool/mode,
not a standalone agent (resisting v1's agent proliferation).
"""
from __future__ import annotations

# task_type -> agent name. (One responsibility, one canonical mapping.)
TASK_TYPE_TO_AGENT: dict[str, str] = {
    "plan": "task_manager",
    "architect": "architect",
    "implement": "builder",
    "validate": "judge",
    "test": "tester",
    "oversee": "overseer",
}

# agent -> launch command (the subprocess contract).
AGENT_COMMANDS: dict[str, list[str]] = {
    "task_manager": ["python", "-m", "agents.task_manager"],
    "architect":    ["python", "-m", "agents.architect"],
    "builder":      ["python", "-m", "agents.builder"],
    "judge":        ["python", "-m", "agents.judge"],
    "tester":       ["python", "-m", "agents.tester"],
    "overseer":     ["python", "-m", "agents.overseer"],
}

# agent -> model assignment, decided by role stakes (ratified decision D4).
#   provider/model behind a clean abstraction so the Claude->local migration is config.
#   Judge runs on a DIFFERENT PROVIDER from the Builder (true independence, finding F5).
AGENT_MODELS: dict[str, dict[str, str]] = {
    # role          provider    model tier        notes
    "task_manager": {"provider": "claude", "model": "sonnet"},   # ->opus for complex goals
    "architect":    {"provider": "claude", "model": "opus"},     # highest-stakes design
    "builder":      {"provider": "claude", "model": "sonnet"},   # cascades local->sonnet->opus by difficulty
    "judge":        {"provider": "openai", "model": "codex"},    # cross-provider independence (F5)
    "tester":       {"provider": "claude", "model": "haiku"},    # mechanical, high-volume
    "overseer":     {"provider": "claude", "model": "opus"},     # high-stakes judgment (bounded)
}


def model_for(agent: str) -> dict[str, str]:
    """The canonical model for an agent. Raise loudly on an unknown agent (no silent default)."""
    try:
        return AGENT_MODELS[agent]
    except KeyError as exc:  # noqa: F841
        raise KeyError(f"{agent!r} has no model in the registry (registry.agents.AGENT_MODELS)") from None
