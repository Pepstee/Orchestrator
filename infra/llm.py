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


def _parse_codex_output(stdout: str) -> LLMResult:
    """Parse `codex exec --json` JSONL: take the last agent_message text.

    Validated against real Codex output (2026-06-01). Usage is reported in tokens, not dollars
    (subscription-covered), so marginal cost is 0.0; token counts remain in the raw stream if a
    later slice wants to impute them.
    """
    text = ""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue  # skip any interleaved log lines
        if ev.get("type") == "item.completed":
            item = ev.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                text = item["text"]  # keep the last agent_message
    return LLMResult(text=text, cost_usd=0.0, model="codex")


def call_llm(
    provider: str,
    model: str,
    prompt: str,
    *,
    system: str | None = None,
    cwd: str | None = None,
    timeout: int = 600,
) -> LLMResult:
    if provider == "claude":
        full = f"{system}\n\n{prompt}" if system else prompt
        cmd = ["claude", "-p", "--output-format", "json", "--model", model]
        if cwd:
            # file-writing mode: run in the project dir and allow the editing tools headlessly
            cmd.append("--dangerously-skip-permissions")
        proc = subprocess.run(
            cmd, input=full, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude exited {proc.returncode}: {(proc.stderr or '')[-300:]}")
        return _parse_claude_output(proc.stdout)
    if provider == "openai":
        full = f"{system}\n\n{prompt}" if system else prompt
        proc = subprocess.run(
            ["codex", "exec", "--json", full],
            capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"codex exited {proc.returncode}: {(proc.stderr or '')[-300:]}")
        return _parse_codex_output(proc.stdout)
    raise ValueError(f"unknown provider {provider!r}")
