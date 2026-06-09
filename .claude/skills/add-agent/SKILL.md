---
name: add-agent
description: Scaffold a new agent in the agentic-orchestrator, following the registry + AgentResult contract. Use when adding a new task_type/worker (e.g. a reviewer, a doc-writer) to the orchestrator.
---

# Add a new agent

Agents are Python subprocesses with one contract: read a payload on stdin, emit exactly one
`AgentResult` on stdout, exit. Resist agent proliferation (the v1 failure) — only add one if it is a
genuinely distinct responsibility.

Steps:

1. **Write `agents/<name>.py`**, mirroring an existing agent (`agents/builder.py` for a file-writing
   agent, `agents/judge.py` for a read-only reviewer). Use the contract helpers:

   ```python
   from agents.common import safe_main
   from core.models import AgentResult, Task
   from infra.llm import call_llm
   from registry.agents import model_for

   def run(payload: dict, call=call_llm) -> AgentResult:
       task = Task.from_dict(payload.get("task", {}))
       spec = model_for("<name>")
       try:
           res = call(spec["provider"], spec["model"], "<prompt>", system="<system>")
       except Exception as exc:
           return AgentResult(ok=False, summary="<name> failed", cause=f"{type(exc).__name__}: {exc}")
       return AgentResult(ok=True, summary="...", metadata={"cost_usd": res.cost_usd})

   if __name__ == "__main__":
       safe_main(run, "<name>")
   ```

2. **Register it in `registry/agents.py`** (the single source of truth — all three must agree):
   - add `"<task_type>": "<name>"` to `TASK_TYPE_TO_AGENT`
   - add `"<name>": [_PY, "-m", "agents.<name>"]` to `AGENT_COMMANDS`
   - add `"<name>": {"provider": ..., "model": ...}` to `AGENT_MODELS`
   The registry test asserts `AGENT_COMMANDS` and `AGENT_MODELS` cover the same agents — keep them in
   sync or the build fails.

3. **If the planner should emit this task_type**, update `agents/task_manager.py`
   (`SYSTEM_PROMPT` + `build_prompt` allowed types).

4. **Write `tests/test_<name>.py`** with an injected fake `call` (no real LLM). Cover: happy path,
   the L4 deliverable-purity / no-op failure case, and an LLM-failure-is-safe case.

5. **Run the `run-gates` skill.** The agent module must import cleanly and the registry test must pass.

Guardrails: file-writing agents must keep the project tree pristine (L4 — no scratch files) and write
only via the editing tools in their `cwd`; never write to the orchestrator's own tree.
