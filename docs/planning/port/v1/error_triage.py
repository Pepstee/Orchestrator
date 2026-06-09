"""
error_triage.py — Classify agent failures so the orchestrator can route
them to the correct recovery strategy.

Three error classes
-------------------
TRANSIENT   — Ephemeral environment fault (git lock, resource, network).
               Requeue immediately without spending a retry.  After
               MAX_TRANSIENT_REQUEUES the same task is treated as RECOVERABLE
               so a broken environment doesn't loop forever.

RECOVERABLE — Logic or test failure the agent might fix on a second attempt,
               or that a repair agent can address.  Uses the normal retry
               budget.  On the final allowed retry a `repair` task is spawned
               with the failure context attached.

PERMANENT   — Hard constraint violation or irrecoverable condition.  Move
               straight to failed; do not spend any more retries.

Usage
-----
    from error_triage import classify, ErrorClass

    ec, reason = classify(result.summary, result.error, task.task_type,
                          transient_requeue_count=task.payload.get("_transient_requeues", 0))
    if ec == ErrorClass.TRANSIENT:
        ...
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: After this many consecutive transient requeues of the same task, give up
#: treating it as transient and fall through to RECOVERABLE so the repair
#: agent can investigate the environment.
MAX_TRANSIENT_REQUEUES: int = 5


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------

class ErrorClass(str, Enum):
    TRANSIENT   = "transient"    # requeue, no retry penalty
    RECOVERABLE = "recoverable"  # retry; spawn repair on last attempt
    PERMANENT   = "permanent"    # fail immediately, no requeue


# ---------------------------------------------------------------------------
# Pattern tables
# ---------------------------------------------------------------------------

# Matched against the combined text of summary + error.
# First matching pattern wins; tables are checked in order:
# PERMANENT first (highest confidence), then TRANSIENT, then default RECOVERABLE.

_PERMANENT_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    # Policy hard-rule violations — never retry, they will fail the same way.
    r"hard.rule.{0,30}(violation|blocked|prevented|cannot|refused)",
    r"tier.3.*never.touch",
    r"never.touch.*tier.3",
    r"policy.{0,20}violation.{0,50}(agent|self.dev|orchestrator|tier)",
    # Explicit validator escalation keywords that indicate a human gate.
    r"escalat.*tier.3",
    r"requires.*confidence.*0\.9",
    # Malformed task payload that can't be repaired by retrying.
    r"missing required field[:\s]{0,5}task_id",
    r"agent not found in _AGENT_MAP",
    r"unknown task.?type.*no agent",
]]

_TRANSIENT_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    # Git lock / index corruption.
    r"index file corrupt",
    r"bad signature.*0x0+",
    r"\.git[\\/].*\.lock.*exists",
    r"unable to create.*\.lock",
    r"failed to lock",
    r"could not lock",
    # OS / resource errors.
    r"resource temporarily unavailable",
    r"no space left on device",
    r"cannot allocate memory",
    r"memoryerror",                  # Python MemoryError during agent startup
    r"too many open files",
    r"oserror.*errno",
    r"permissionerror",
    # Process timeouts / signals.
    r"timed? ?out",  # matches "timed out", "time out", "timeout"
    r"sigkill",
    r"killed.*signal",
    r"agent.*exited.*code.*-9",
    r"subprocess.*timeout",
    # Network transients.
    r"connection (refused|reset|timed? out|aborted)",
    r"name or service not known",
    r"temporary failure in name resolution",
    r"read.*connection.*reset",
    r"broken pipe",
    # API rate limits (treat as transient — back off and retry).
    r"rate.?limit",
    r"too many requests",
    r"529.*overloaded",
    r"service.?unavailable",
    r"anthropic.*error.*529",
    # Windows subprocess DLL initialization failure (rc=3221226505, STATUS_DLL_INIT_FAILED).
    # Environmental, not an agent error; transient and safe to retry with backoff.
    r"exit\s*3221226505",
    r"status_dll_init_fail",
    # R-10: Windows CTRL+C / taskkill exit codes.
    # 0xC000013A = 3221225786 = STATUS_CONTROL_C_EXIT — raised when taskkill /F
    # terminates a process on timeout (the orchestrator sends SIGTERM then
    # taskkill, so this is always an environmental kill, not an agent logic error).
    r"exit\s*(?:code\s*)?(?:0xC000013A|3221225786)",
    r"process.*was forcibly terminated",
    r"forcibly terminated.*process",
]]

_RECOVERABLE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    # Test failures.
    r"FAILED tests/",
    r"pytest.*failed",
    r"test.*error",
    r"\d+ failed",
    # Python errors that a repair agent can fix.
    r"syntaxerror",
    r"indentationerror",
    r"importerror",
    r"modulenotfounderror",
    r"nameerror",
    r"attributeerror",
    r"typeerror",
    r"assertionerror",
    # Patch / diff failures.
    r"patch.*failed",
    r"hunk.*failed",
    r"error.*applying.*patch",
    r"git apply.*failed",
    # Build errors.
    r"compilation error",
    r"build.*failed",
    r"npm.*error",
    # Logic failures from agents.
    r"acceptance criteria.*not met",
    r"verification.*failed",
    r"could not.*complete",
]]


# Fine-grained sub-classifiers for the diagnoser pre-classification hint.
# Applied in order; first match wins.  Maps to the diagnoser's failure_class
# vocabulary without duplicating the broad TRANSIENT/RECOVERABLE pattern tables.
_DIAGNOSER_HINT_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"Killed|SIGKILL|exit code 137|signal 9\b|exit status 9\b", re.IGNORECASE),
     "oom_kill", "process received SIGKILL or was killed (OOM or hard limit)"),
    (re.compile(r"TimeoutExpired|timed out|timeout exceeded|wall.?clock", re.IGNORECASE),
     "timeout", "wall-clock timeout exceeded"),
    (re.compile(
        r"ConnectionRefusedError|ConnectionError|RemoteDisconnected|"
        r"requests\.exceptions|HTTP 5[0-9][0-9]|BrokenPipeError",
        re.IGNORECASE,
    ), "transient_network", "network or remote connection failure"),
    (re.compile(
        r"overloaded_error|rate.?limit|529|anthropic.*error|claude.*unavailable",
        re.IGNORECASE,
    ), "transient_api", "Anthropic / Claude API transient error"),
    (re.compile(r"MemoryError|cannot allocate|malloc.*failed|out of memory", re.IGNORECASE),
     "resource_exhaustion", "memory allocation failure"),
]


def pre_classify_hint(combined_text: str) -> str:
    """Return a pre-classification hint string for the diagnoser's LLM prompt.

    Scans *combined_text* (failure reasons + stdout captures joined together)
    against fine-grained pattern rules and returns a human-readable hint.
    Returns '' when no pattern matches so the LLM has no prior to anchor on.
    """
    for pat, cls, label in _DIAGNOSER_HINT_RULES:
        if pat.search(combined_text):
            return f'Pre-classification hint: {label} → likely failure_class="{cls}"'
    return ""


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def classify(
    summary: str,
    error: Optional[str],
    task_type: str = "",
    transient_requeue_count: int = 0,
) -> Tuple[ErrorClass, str]:
    """
    Classify an agent failure.

    Parameters
    ----------
    summary               : AgentResult.summary text.
    error                 : AgentResult.error text (may be None).
    task_type             : Task.task_type — used for heuristics.
    transient_requeue_count: Number of times this task has already been
                            requeued as TRANSIENT.  Once this reaches
                            MAX_TRANSIENT_REQUEUES, TRANSIENT is downgraded
                            to RECOVERABLE.

    Returns
    -------
    (ErrorClass, reason_string)
    """
    combined = _combine(summary, error)

    # ── PERMANENT check ───────────────────────────────────────────────────
    for pat in _PERMANENT_PATTERNS:
        if pat.search(combined):
            return ErrorClass.PERMANENT, f"permanent pattern matched: {pat.pattern!r}"

    # ── TRANSIENT check ───────────────────────────────────────────────────
    for pat in _TRANSIENT_PATTERNS:
        if pat.search(combined):
            if transient_requeue_count >= MAX_TRANSIENT_REQUEUES:
                return (
                    ErrorClass.RECOVERABLE,
                    f"transient pattern {pat.pattern!r} matched but "
                    f"transient_requeue_count={transient_requeue_count} >= "
                    f"MAX_TRANSIENT_REQUEUES={MAX_TRANSIENT_REQUEUES}; "
                    f"downgraded to RECOVERABLE",
                )
            return ErrorClass.TRANSIENT, f"transient pattern matched: {pat.pattern!r}"

    # ── RECOVERABLE check (explicit pattern) ─────────────────────────────
    for pat in _RECOVERABLE_PATTERNS:
        if pat.search(combined):
            return ErrorClass.RECOVERABLE, f"recoverable pattern matched: {pat.pattern!r}"

    # ── Default ───────────────────────────────────────────────────────────
    # Unknown error text → RECOVERABLE.  We never silently discard a failure.
    return ErrorClass.RECOVERABLE, "no pattern matched; defaulting to recoverable"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _combine(summary: str, error: Optional[str]) -> str:
    parts = [summary or ""]
    if error:
        parts.append(error)
    return "\n".join(parts)
