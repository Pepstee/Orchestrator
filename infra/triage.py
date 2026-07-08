"""infra.triage — the failure-cause taxonomy (ported from v1 `error_triage`; manifest row B1).

Three classes route a failure to its recovery strategy:

TRANSIENT   — infra/provider fault that self-resolves (rate/usage limit, restart-kill, env
              hiccup: git lock, OOM, timeout, network). Requeued without retry penalty, but
              BUDGETED (BG-3): misclassification is inevitable, so the repository caps these
              at MAX_TRANSIENT_REQUEUES rather than trusting the classifier.
RECOVERABLE — the default: a logic/test failure that another attempt or a replan may fix.
              Spends the ordinary bounded retry budget. Never silently discarded.
PERMANENT   — deterministic dead-end (malformed CLI invocation, unknown provider/agent,
              prerequisite cascade, overseer abandonment). Retrying burns a full agent run to
              fail identically — fail fast, surface it.

Within RECOVERABLE, `is_input_deterministic` marks causes (merge/patch conflicts) whose
outcome cannot change unless the INPUTS change — the dispatcher refuses an identical
re-attempt against an unchanged base rev (BG-3's input-hash rule).

One module, one taxonomy (L1): the dispatcher (ladder), repository (budgets, revival), PA
(rule hygiene) and GUI (what counts as 'needs you') all read THIS file, so they cannot drift.
PERMANENT patterns are deliberately tight: a false PERMANENT kills recoverable work, which is
worse than a few wasted retries — when in doubt, RECOVERABLE.
"""
from __future__ import annotations

import re
from enum import Enum


class ErrorClass(str, Enum):
    TRANSIENT = "transient"
    RECOVERABLE = "recoverable"
    PERMANENT = "permanent"


# The SINGLE source of rate/usage-limit hints, matched (case-insensitive) against provider output
# and failure causes. Covers the real Claude Max wordings — the bare "5-hour limit reached ∙ resets
# 5am" carries none of the generic phrases, so it MUST be listed explicitly or a limit reads as a
# hard failure. Kept specific to avoid false positives.
RATE_LIMIT_HINTS = (
    "rate limit", "rate_limit", "ratelimited", "rate_limit_error",
    "usage limit", "5-hour limit", "5 hour limit", "weekly limit",
    "try again later", "try again after",
    "429", "529", "quota", "too many requests", "overloaded", "overloaded_error",
)

# Deterministic dead-ends. Provider-CLI shapes are anchored on the `<provider> exited N:` prefix
# that infra.llm._fail_provider emits (possibly wrapped, possibly spanning lines — DOTALL).
_PERMANENT_PATTERNS = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in (
    r"(claude|codex) exited \d+:.*(unknown (option|argument|command)|unrecognized"
    r"|invalid model|usage: claude|no such file|command not found|missing required)",
    r"unknown provider",
    r"unknown task.?type",
    r"agent not found",
    r"prerequisite failed",
    r"abandoned by overseer",
    # Auth failures are deterministic until a human runs `claude login` — retrying burns a full
    # agent run to fail identically (the 401-as-transient overnight loop, HANDOFF §4). Anchored on
    # the "<provider> auth error" prefix infra.llm._fail_provider emits, plus the CLI's own
    # unambiguous wordings; deliberately NOT a bare "401" (false PERMANENTs are worse).
    r"(claude|codex) auth error",
    r"authentication[_ ](error|failed)",
    r"oauth token (has )?(expired|revoked)",
    r"please run /login",
    r"not logged in",
)]

# Environment faults that self-resolve (ported from v1's _TRANSIENT_PATTERNS, trimmed to the
# classes observed in this stack: git locks, resources, timeouts, kills, network).
_TRANSIENT_ENV_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"\.git[\\/].*\.lock", r"failed to lock", r"could not lock", r"index file corrupt",
    r"resource temporarily unavailable", r"no space left on device",
    r"cannot allocate memory", r"memoryerror", r"too many open files",
    r"timed? ?out", r"timeoutexpired", r"sigkill", r"killed.*signal",
    r"connection (refused|reset|timed? ?out|aborted)", r"broken pipe",
    r"temporary failure in name resolution",
)]

# RECOVERABLE causes whose outcome is a pure function of the inputs: re-attempting against the
# same base rev with the same payload MUST fail identically (the 90-retry oscillator's class).
_INPUT_DETERMINISTIC_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"merge conflict", r"hunk.*failed", r"git apply.*failed", r"patch.*failed",
)]


def is_transient_cause(cause: str) -> bool:
    """The SINGLE definition of a transient (not-the-task's-fault) failure cause: a provider
    rate/usage limit, the daemon being killed mid-task (KeyboardInterrupt on restart/Ctrl-C),
    or a self-resolving environment fault. These requeue WITHOUT a retry penalty — bounded by
    the durable transient budget (BG-3), never unbounded.

    A merge conflict is deliberately NOT here: it goes through the BOUNDED retry ladder (a fresh
    re-run off current main clears a stale-branch conflict; a genuine overlapping-diff conflict
    does NOT self-resolve, so it is capped and surfaced, never looped — an unbounded conflict
    requeue burns a full agent run per iteration, which is exactly what it once did)."""
    low = (cause or "").lower()
    if "keyboardinterrupt" in low or any(hint in low for hint in RATE_LIMIT_HINTS):
        return True
    return any(pat.search(low) for pat in _TRANSIENT_ENV_PATTERNS)


def classify(cause: str) -> tuple[ErrorClass, str]:
    """Classify a failure cause. PERMANENT is checked first (highest confidence), then
    TRANSIENT; everything else — including an empty cause — is RECOVERABLE (never discard)."""
    text = cause or ""
    for pat in _PERMANENT_PATTERNS:
        if pat.search(text):
            return ErrorClass.PERMANENT, f"permanent pattern: {pat.pattern!r}"
    if is_transient_cause(text):
        return ErrorClass.TRANSIENT, "transient cause (self-resolving; budgeted requeue)"
    return ErrorClass.RECOVERABLE, "default: a retry or replan may fix it"


def is_input_deterministic(cause: str) -> bool:
    """True for RECOVERABLE causes that cannot change outcome unless the inputs change
    (BG-3: such a task may only be re-attempted against a changed base rev / payload)."""
    text = cause or ""
    return any(pat.search(text) for pat in _INPUT_DETERMINISTIC_PATTERNS)
