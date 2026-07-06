"""registry.agents — the SINGLE SOURCE OF TRUTH for agent wiring (laws L1, L5).

Nothing is arbitrary: every agent's launch command and model are declared here, once.
Agents resolve their model from this module; the `reported == chosen` runtime check
(added when the agent runner lands) fails the build if a running agent drifts off it.

Roster: 5 agents + the meta-agent (Overseer). Everything else is a function/tool/mode,
not a standalone agent (resisting v1's agent proliferation).
"""
from __future__ import annotations

import os
import sys

# Launch agents with the SAME interpreter running the orchestrator — guarantees it exists
# (fixes "'python' not found" on macOS, where only python3 is on PATH).
_PY = sys.executable or "python3"

# task_type -> agent name. (One responsibility, one canonical mapping.)
TASK_TYPE_TO_AGENT: dict[str, str] = {
    "plan": "task_manager",
    "implement": "builder",
    "test": "tester",        # the INDEPENDENT test-author (separate from the builder — anti-collusion)
    "validate": "judge",
    "oversee": "overseer",
    "research": "researcher",  # deep tiered research; its output is gated by validation.research_contract (DV-3)
}

# agent -> launch command (the subprocess contract).
AGENT_COMMANDS: dict[str, list[str]] = {
    "task_manager": [_PY, "-m", "agents.task_manager"],
    "builder":      [_PY, "-m", "agents.builder"],
    "tester":       [_PY, "-m", "agents.tester"],
    "judge":        [_PY, "-m", "agents.judge"],
    "overseer":     [_PY, "-m", "agents.overseer"],
    "researcher":   [_PY, "-m", "agents.researcher"],
}

# agent -> model assignment, decided by role stakes (ratified decision D4).
#   provider/model behind a clean abstraction so the Claude->local migration is config.
#   Judge runs on a DIFFERENT PROVIDER from the Builder (true independence, finding F5).
AGENT_MODELS: dict[str, dict[str, str]] = {
    # role          provider    model tier        notes
    "task_manager": {"provider": "claude", "model": "sonnet"},   # ->opus for complex goals
    "builder":      {"provider": "claude", "model": "sonnet"},   # cascades local->sonnet->opus by difficulty
    "tester":       {"provider": "claude", "model": "sonnet"},   # independent test-author (mutation gate backs it)
    "judge":        {"provider": "openai", "model": "codex"},    # cross-provider independence (F5)
    # Overseer promoted Opus 4.8 -> Fable 5 (operator decision, 9 Jun 2026; DG-3: strongest model
    # to the highest-stakes judgement role first). Metric to watch per DG-3: retries-per-completion
    # and tokens-per-certified-criterion — the premium must pay for itself in fewer attempts.
    # If the host CLI rejects the model string, the failure is PERMANENT (loud) and the env
    # override AGENTIC_OVERSEER="claude:opus" reroutes it without a code change.
    "overseer":     {"provider": "claude", "model": "claude-fable-5"},
    # Deep-research synthesis. Promotes to Fable 5 AFTER the Overseer eval (locked order: Overseer
    # first, DV-4); runs on sonnet until then. Its adversarial verification stays cross-provider.
    "researcher":   {"provider": "claude", "model": "sonnet"},
}


def model_for(agent: str) -> dict[str, str]:
    """The canonical model for an agent, with a reversible per-agent env override for provider
    outages. Set ``AGENTIC_<AGENT>="provider:model"`` to reroute one agent without editing code —
    e.g. ``AGENTIC_JUDGE=claude:opus`` when Codex usage is exhausted (a month at a time). The
    registry above stays the canonical cross-provider default (F5); drop the env var to restore it.
    Raises loudly on an unknown agent (no silent default)."""
    try:
        spec = AGENT_MODELS[agent]
    except KeyError:
        raise KeyError(f"{agent!r} has no model in the registry (registry.agents.AGENT_MODELS)") from None
    override = os.environ.get(f"AGENTIC_{agent.upper()}", "")
    if ":" in override:
        provider, model = override.split(":", 1)
        return {"provider": provider.strip(), "model": model.strip()}
    return spec
