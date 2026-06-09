"""infra.llm — provider-abstracted LLM invocation (the seam for the Claude->local migration).

Shells out to a provider's CLI and returns text + cost. The Claude path is implemented and its
JSON parser is unit-tested against the real CLI output shape. The OpenAI/Codex path is wired but
deliberately raises until its parser is validated against real `codex exec --json` output (the
Judge slice) — never ship an unverified parser as if it works (probe-before-you-build).
"""
from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass

# Classification is the triage module's job (one taxonomy, L1). Names re-exported here because
# the dispatcher/repository historically import them from infra.llm.
from infra.triage import RATE_LIMIT_HINTS as RATE_LIMIT_HINTS
from infra.triage import is_transient_cause as is_transient_cause


@dataclass
class LLMResult:
    text: str
    cost_usd: float
    model: str
    session_id: str = ""   # the Claude session this turn ran in (for resumable, persistent agents)


class RateLimited(RuntimeError):
    """Provider usage/rate limit hit — transient (resets, e.g. the Claude Max 5-hour window). The
    caller should back off and retry, NOT treat it as a task failure."""


def _looks_rate_limited(text: str) -> bool:
    low = (text or "").lower()
    return any(hint in low for hint in RATE_LIMIT_HINTS)


# Deterministic CLI / argument errors: retrying these byte-for-byte will fail identically forever, so
# they are HARD failures the operator should see (escalated), never silently looped. Everything else
# — including a bare non-zero exit with NO diagnostic output, which is exactly how the Claude CLI
# surfaces a usage cap — is treated as transient (see the default branch of _fail_provider).
_HARD_CLI_ERROR_HINTS = (
    "unknown option", "unknown argument", "unknown command", "unrecognized",
    "invalid model", "usage: claude", "no such file", "command not found",
    "permission denied", "missing required",
)

# A resume aimed at a session that is missing / expired / not a valid id. NOT a hard failure: the work
# shouldn't die with the session — _run_claude falls back to a fresh session and carries on.
_SESSION_ERROR_HINTS = (
    "--resume requires", "does not match any session", "no conversation found",
    "is not a uuid", "session not found", "no session",
)


def _is_hard_cli_error(text: str) -> bool:
    low = (text or "").lower()
    return any(hint in low for hint in _HARD_CLI_ERROR_HINTS)


def _looks_session_error(text: str) -> bool:
    low = (text or "").lower()
    return any(hint in low for hint in _SESSION_ERROR_HINTS)


def _fail_provider(provider: str, rc: int, raw: str) -> None:
    """Classify a non-zero provider exit and raise. Rate-limit wording -> RateLimited (transient). A
    recognised deterministic CLI/arg error -> RuntimeError (hard, surfaced). Anything else, INCLUDING
    an opaque exit with no diagnostic output -> RateLimited: a bare `claude exited 1` with no message
    is the signature of a hit usage cap, so it must back off and resume after the reset, never escalate
    into a permanent failure (the bug that stranded a whole night's work). 'usage limit' is in the
    message so the dispatcher's is_transient_cause classifies it transient via the single hint list."""
    if _looks_rate_limited(raw):
        raise RateLimited(f"{provider} usage/rate limit: {raw[-300:]}")
    if _is_hard_cli_error(raw):
        raise RuntimeError(f"{provider} exited {rc}: {raw[-300:]}")
    raise RateLimited(
        f"{provider} exited {rc} with no recognisable error — treating as transient usage limit "
        f"(back off and retry, do not escalate): {raw[-200:]!r}"
    )


def _parse_claude_output(stdout: str) -> LLMResult:
    """Parse `claude -p --output-format json` output (the shape the real CLI emits)."""
    data = json.loads(stdout)
    text = data.get("result", "") or ""
    cost = float(data.get("total_cost_usd", 0.0) or 0.0)
    model = ""
    usage = data.get("modelUsage")
    if isinstance(usage, dict) and usage:
        model = next(iter(usage.keys()), "")
    return LLMResult(text=text, cost_usd=cost, model=model, session_id=str(data.get("session_id", "") or ""))


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
    session_id: str | None = None,
    resume: bool = False,
) -> LLMResult:
    """Invoke a provider. For a persistent, resumable agent (e.g. the Overseer meta-agent), pass a
    caller-owned ``session_id``: ``resume=False`` CREATES that session, ``resume=True`` CONTINUES it
    with the full prior context. Only the Claude path supports sessions; other providers ignore the
    args and run stateless (the abstraction degrades gracefully)."""
    if provider == "claude":
        full = f"{system}\n\n{prompt}" if system else prompt
        base = ["claude", "-p", "--output-format", "json", "--model", model]
        if cwd:
            # file-writing mode: run in the project dir and allow the editing tools headlessly.
            # NB: this flag is NOT sticky across --resume, so it must be re-passed every call.
            base.append("--dangerously-skip-permissions")

        def _run(session_args: list[str]) -> subprocess.CompletedProcess:
            return subprocess.run(base + session_args, input=full, capture_output=True,
                                  text=True, timeout=timeout, cwd=cwd)

        # We OWN the UUID (reliable), rather than scraping it back. --resume continues the conversation
        # with full context; --session-id starts a new one under that id.
        session_args = []
        if session_id:
            session_args = ["--resume", session_id] if resume else ["--session-id", session_id]
        proc = _run(session_args)

        if proc.returncode != 0:
            raw = proc.stderr or proc.stdout or ""
            # Resume-fallback: a resume against a missing / expired / invalid session must NOT kill the
            # agent. Start a FRESH session under a new valid UUID once and carry on — continuity restarts
            # here rather than the whole task failing (the persistent overseer self-heals instead of
            # looping the same broken --resume forever). The new id is returned so the caller persists it.
            if resume and session_id and _looks_session_error(raw) and not _looks_rate_limited(raw):
                fresh_id = str(uuid.uuid4())
                proc = _run(["--session-id", fresh_id])
                if proc.returncode == 0:
                    result = _parse_claude_output(proc.stdout)
                    result.session_id = result.session_id or fresh_id
                    return result
                raw = proc.stderr or proc.stdout or ""   # fall through to classify the fresh attempt
            _fail_provider("claude", proc.returncode, raw)
        result = _parse_claude_output(proc.stdout)
        if session_id and not result.session_id:
            result.session_id = session_id   # fall back to the id we supplied (output echo is flaky)
        return result
    if provider == "openai":
        full = f"{system}\n\n{prompt}" if system else prompt
        proc = subprocess.run(
            ["codex", "exec", "--json", full],
            capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
        if proc.returncode != 0:
            raw = proc.stderr or proc.stdout or ""
            _fail_provider("codex", proc.returncode, raw)
        return _parse_codex_output(proc.stdout)
    raise ValueError(f"unknown provider {provider!r}")
