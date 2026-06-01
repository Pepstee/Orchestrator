"""dispatch.runner — the agent subprocess contract.

An agent is a subprocess: it reads a JSON payload on stdin and writes exactly one AgentResult
JSON line to stdout, then exits. The default invoke resolves the agent + command from the
registry (single source of truth). Any failure — non-zero exit, timeout, unparseable output —
yields an AgentResult carrying a `cause`, so the failure is self-explaining (finding F10).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

from core.models import AgentResult, Task
from registry import agents as reg

_REPO_ROOT = str(Path(__file__).resolve().parents[1])


def parse_agent_output(stdout: str) -> AgentResult:
    """Scan stdout backwards for the last JSON object with an `ok` field (tolerates log noise)."""
    for line in reversed([ln.strip() for ln in stdout.splitlines() if ln.strip()]):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "ok" in data:
            return AgentResult.from_dict(data)
    return AgentResult(
        ok=False,
        summary="unparseable agent output",
        cause="no AgentResult JSON line found in agent stdout",
    )


def run_subprocess_agent(
    command: list[str],
    payload: dict,
    timeout: int = 4500,
    cwd: str | None = None,
    env: dict | None = None,
) -> AgentResult:
    try:
        proc = subprocess.run(
            command,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return AgentResult(ok=False, summary="agent timed out", cause=f"timeout after {timeout}s")
    except (OSError, ValueError) as exc:
        return AgentResult(ok=False, summary="agent failed to launch", cause=str(exc))
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-400:]
        return AgentResult(
            ok=False,
            summary=f"agent exited {proc.returncode}",
            cause=tail or f"non-zero exit {proc.returncode}",
        )
    return parse_agent_output(proc.stdout)


def make_subprocess_invoke() -> Callable[[Task], AgentResult]:
    """The default invoke: resolve agent + command from the registry and run the subprocess.

    Runs from the repo root with the repo on PYTHONPATH so `-m agents.<x>` resolves regardless of
    where the orchestrator was launched. The agent then runs its own LLM in the project directory.
    """
    env = {**os.environ, "PYTHONPATH": _REPO_ROOT + os.pathsep + os.environ.get("PYTHONPATH", "")}

    def invoke(task: Task) -> AgentResult:
        agent = reg.TASK_TYPE_TO_AGENT.get(task.task_type)
        if agent is None:
            return AgentResult(
                ok=False, summary="no agent for task_type",
                cause=f"unknown task_type {task.task_type!r}",
            )
        return run_subprocess_agent(
            reg.AGENT_COMMANDS[agent], {"task": task.to_dict()}, cwd=_REPO_ROOT, env=env,
        )
    return invoke
