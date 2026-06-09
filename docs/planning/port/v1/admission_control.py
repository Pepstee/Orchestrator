"""
admission_control.py — AIMD-based concurrency control for agent API calls.

Implements Additive Increase / Multiplicative Decrease (AIMD) to prevent
rate-limit cascades when many concurrent agents hammer the Claude API.

Algorithm
---------
  Window starts at max_concurrent (from Config).
  On each successful task completion  : window = min(window + 1, max)
  On each rate-limit signal detected  : window = max(1,  window * 0.5)

The orchestrator dispatch loop calls current_limit() instead of reading
the static max_concurrent_agents config value.  Because the window is
bounded above by max_concurrent_agents the change is backward-compatible:
under zero congestion the limit converges back to the config value.
"""

from __future__ import annotations

import re
import threading

_lock = threading.Lock()
_window: float = 4.0   # current effective concurrency cap (float for smooth AIMD)
_max: int = 4          # ceiling from Config.max_concurrent_agents

# Rate-limit signal patterns — these match the API-rate-limit subset of the
# transient patterns in error_triage._TRANSIENT_PATTERNS.  Kept here rather
# than imported from error_triage to keep the dependency one-way
# (admission_control ← orchestrator, not admission_control ← error_triage).
_RATE_LIMIT_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"rate.?limit",
    r"too many requests",
    r"529.*overloaded",
    r"anthropic.*error.*529",
    r"service.?unavailable",
    r"overloaded.*rate",
]]


def reset(max_concurrent: int) -> None:
    """Initialise (or re-initialise) the AIMD window to *max_concurrent*.

    Call once at orchestrator startup after Config.load().  Safe to call
    again if max_concurrent_agents is reconfigured at runtime.
    """
    global _window, _max
    with _lock:
        _max = max(1, int(max_concurrent))
        _window = float(_max)


def current_limit() -> int:
    """Return the current effective concurrency cap (always ≥ 1)."""
    with _lock:
        return max(1, int(_window))


def on_success() -> None:
    """Additive increase: step the window one unit toward the ceiling."""
    global _window
    with _lock:
        _window = min(_window + 1.0, float(_max))


def on_rate_limit() -> None:
    """Multiplicative decrease: halve the window on a rate-limit signal."""
    global _window
    with _lock:
        _window = max(1.0, _window * 0.5)


def is_rate_limit_signal(text: str) -> bool:
    """Return True when *text* matches a known API rate-limit error pattern."""
    if not text:
        return False
    for pat in _RATE_LIMIT_PATTERNS:
        if pat.search(text):
            return True
    return False
