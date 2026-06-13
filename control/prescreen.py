"""control.prescreen — a local screen in front of the overseer's observe pulses.

Every expensive call sits behind a cheap screen (operator doctrine, 13 Jun 2026): at each due
pulse the house model reads the same status summary the overseer would receive and answers one
question — does anything here need the persistent mind awake now? QUIET skips the cloud turn
(the saving); WAKE forwards the pulse with a compact advisory note. FAIL-OPEN BY LAW: any
error, timeout, garbage answer, or missing local server wakes the overseer — a broken screen
must never silence the guardian (machine-checked in tests/test_prescreen.py). Boot, reset,
succession and operator-chat turns never pass through here: the daemon consults the screen
only on the ordinary pulse branch (structural, not configurable)."""
from __future__ import annotations

import os

from infra.llm import call_llm

PRESCREEN_MODEL = os.environ.get("AGENTIC_PRESCREEN_MODEL", "qwen3:8b")
_TIMEOUT_S = 120   # a screen that dawdles is a screen that wakes

_SYSTEM = (
    "You are the pre-screen for an autonomous orchestrator's overseer (an expensive persistent "
    "agent). Read the status summary and decide if it must wake NOW. WAKE on any of: failed or "
    "stuck tasks, anything pending user confirmation, budget or rate-limit anomalies, gate "
    "failures, stalled or churning projects, security-relevant text, or anything you do not "
    "understand. Answer QUIET only when work is plainly proceeding or idle by design. "
    "First line: exactly WAKE or QUIET. Then 2-6 lines of rationale; on WAKE make them a "
    "briefing with concrete identifiers (task ids, project names) drawn from the summary."
)


def prescreen_pulse(status_summary: str, *, call=call_llm) -> tuple[bool, str]:
    """(wake, note). Only a well-formed QUIET skips a pulse; everything else fails open."""
    if call is call_llm and os.environ.get("PYTEST_CURRENT_TEST"):
        # Hermetic under pytest (cf. notify's hard mute): a test suite must never call a model.
        return True, "screen bypassed under pytest"
    if os.environ.get("AGENTIC_PRESCREEN", "").strip().lower() in ("off", "0", "false"):
        return True, "screen disabled by AGENTIC_PRESCREEN"
    try:
        res = call("ollama", PRESCREEN_MODEL, status_summary, system=_SYSTEM, timeout=_TIMEOUT_S)
        text = (res.text or "").strip()
        lines = text.splitlines()
        first = lines[0].strip().upper() if lines else ""
        note = "\n".join(lines[1:]).strip()[:800]
        if first == "QUIET":
            return False, note or "screen: quiet"
        return True, note or text[:800]
    except Exception as exc:   # fail-open is the contract — never re-raise, never silence
        return True, f"pre-screen unavailable ({type(exc).__name__}: {exc}) - waking by default"
