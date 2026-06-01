"""infra.llm — provider-abstracted LLM invocation (the seam for the Claude->local migration).

Shells out to a provider's CLI and returns text + cost. The Claude path is implemented and its
JSON parser is unit-tested against the real CLI output shape. The OpenAI/Codex path is wired but
deliberately raises until its parser is validated against real `codex exec --json` output (the
Judge slice) — never ship an unverified parser as if it works (probe-before-you-build).
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass
class LLMResult:
    text: str
    cost_usd: float
    model: str


def _parse_claude_output(stdout: str) -> LLMResult:
    """Parse `claude -p --output-format json` output (the shape the real CLI emits)."""
    data = json.loads(stdout)
    text = data.get("result", "") or ""
    cost = float(data.get("total_cost_usd", 0.0) or 0.0)
    model = ""
    usage = data.get("modelUsage")
    if isinstance(usage, dict) and usage:
        model = next(iter(usage.keys()), "")
    return LLMResult(text=text, cost_usd=cost, model=model)


def call_llm(
    provider: str,
    model: str,
    prompt: str,
    *,
    system: str | None = None,
    timeout: int = 600,
) -> LLMResult:
    if provider == "claude":
        full = f"{system}\n\n{prompt}" if system else prompt
        cmd = ["claude", "-p", "--output-format", "json", "--model", model]
        proc = subprocess.run(cmd, input=full, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"claude exited {proc.returncode}: {(proc.stderr or '')[-300:]}")
        return _parse_claude_output(proc.stdout)
    if provider == "openai":
        raise NotImplementedError(
            "openai/codex path: parser must be validated against real `codex exec --json` "
            "output before use (Judge slice)"
        )
    raise ValueError(f"unknown provider {provider!r}")
