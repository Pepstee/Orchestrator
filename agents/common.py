"""agents.common — the agent IO contract: read one payload (stdin), emit one AgentResult (stdout).

Every agent subprocess uses these. safe_main guarantees the boundary discipline: an agent always
emits a result, and a crash becomes a self-explaining failed AgentResult — never a bare traceback
the orchestrator can't parse (finding F10).
"""
from __future__ import annotations

import json
import sys
from typing import Callable

from core.models import AgentResult


def read_payload() -> dict:
    raw = sys.stdin.read()
    return json.loads(raw) if raw.strip() else {}


def emit(result: AgentResult) -> None:
    sys.stdout.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def safe_main(run: Callable[[dict], AgentResult], agent_name: str) -> None:
    try:
        result = run(read_payload())
    except Exception as exc:
        result = AgentResult(
            ok=False,
            summary=f"{agent_name} crashed",
            cause=f"{type(exc).__name__}: {exc}",
        )
    emit(result)
