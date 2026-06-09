"""memory.overseer — the persistent Overseer meta-agent's durable memory (the one stateful agent).

Two pieces of crash-safe state (all writes via infra.atomic_io, law L7):

  * SESSION pointer — which Claude session the overseer is currently reasoning in, and when it
    started. Each overseer invocation RESUMES the same session (genuine continuity of reasoning),
    and the daemon ROTATES it on a fixed cadence so context growth stays bounded (law A3).

  * HANDOFF prompt — how the overseer writes its succession note before a wipe. It is composed as
    CORE + EXTRA:
      - CORE is hardcoded and IMMUTABLE: the quality floor for a handoff, which can never degrade.
      - EXTRA is an external file the overseer itself improves each cycle (length-capped, so a bad
        revision can't bloat or wreck it).
    The composed prompt is always CORE first, so the handoff can never fall below the floor no matter
    what EXTRA becomes. This is the operator's "X (fixed) + Y (continuously improved)" design.

Lives in the `memory` layer so both the overseer (agents) and the daemon (control/pa) may import it.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from infra.atomic_io import read_json, write_json_atomic, write_text_atomic

# Rotate the session daily; alert the overseer this far ahead of the wipe to write its handoff.
DEFAULT_RESET_INTERVAL_S = 24 * 3600
DEFAULT_SUCCESSION_LEAD_S = 2 * 3600
MAX_EXTRA_LEN = 8000


# --------------------------------------------------------------------------- session lifecycle
@dataclass
class SessionState:
    session_id: str
    started_at: float


def _is_canonical_uuid(sid: str) -> bool:
    """Claude's --session-id / --resume accept ONLY a canonical dashed UUID. A bare 32-char hex string
    (what uuid4().hex produces) parses as a UUID in Python but the CLI rejects it as 'not a UUID',
    failing every call identically forever. Guard the loader so a malformed id is never resumed — the
    daemon then mints a fresh valid session instead of looping (the bug behind a lost night's work)."""
    try:
        return str(uuid.UUID(str(sid))) == str(sid).lower()
    except (ValueError, AttributeError, TypeError):
        return False


def load_session(path: Path | str) -> SessionState | None:
    """Load the persisted session, or None if absent OR malformed. Returning None for a malformed id
    routes the daemon into its fresh-session branch (self-heal) rather than resuming a broken id."""
    data = read_json(path)
    if isinstance(data, dict) and data.get("session_id") and _is_canonical_uuid(data["session_id"]):
        return SessionState(session_id=str(data["session_id"]),
                            started_at=float(data.get("started_at", 0.0) or 0.0))
    return None


def start_session(path: Path | str, *, now: float | None = None) -> SessionState:
    """Begin a fresh session under a new caller-owned UUID; persist and return it (the 24h reset).
    Must be a CANONICAL dashed UUID — Claude's --session-id / --resume reject bare 32-char hex."""
    st = SessionState(session_id=str(uuid.uuid4()), started_at=time.time() if now is None else now)
    write_json_atomic(path, {"session_id": st.session_id, "started_at": st.started_at})
    return st


def _age(st: SessionState, now: float | None) -> float:
    return (time.time() if now is None else now) - st.started_at


def due_for_succession(st: SessionState, *, now: float | None = None,
                       interval: float = DEFAULT_RESET_INTERVAL_S,
                       lead: float = DEFAULT_SUCCESSION_LEAD_S) -> bool:
    """True once the session is within `lead` seconds of its wipe — time to write the handoff."""
    return _age(st, now) >= (interval - lead)


def due_for_reset(st: SessionState, *, now: float | None = None,
                  interval: float = DEFAULT_RESET_INTERVAL_S) -> bool:
    """True once the session has reached its full lifetime — rotate to a fresh one."""
    return _age(st, now) >= interval


# --------------------------------------------------------------------------- handoff prompt (CORE + EXTRA)
HANDOFF_PROMPT_CORE = (
    "You are about to be RESET: your conversation memory will be wiped and a fresh session will take "
    "over. Write a succession handoff addressed to your future self, who will wake with NO memory of "
    "this session and only this note plus the durable logs. Make it completely self-contained.\n\n"
    "The handoff MUST cover, concretely (names, ids, file paths — not vague summaries):\n"
    "1. CURRENT STATE: each active project, its goal, and where it stands (passing gates / blocked / "
    "stalled).\n"
    "2. WORK IN PROGRESS: what is mid-flight right now and the exact next concrete step for each.\n"
    "3. DECISIONS + RATIONALE: choices you made this cycle and why, so they are not relitigated.\n"
    "4. FAILURES + CAUSES: what went wrong, the root cause, and what you already tried — so your "
    "successor does not repeat dead ends.\n"
    "5. OPEN QUESTIONS / RISKS: what is uncertain or likely to break next.\n"
    "6. FIRST ACTIONS ON WAKING: the prioritised first moves for the new session.\n"
    "7. DO NOT REDO: work that is already done or already ruled out.\n\n"
    "Be specific and economical. Omit anything recoverable from the logs; capture only what would be "
    "lost with your memory."
)


def _read_text_or_empty(path: Path | str) -> str:
    p = Path(path)
    try:
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except OSError:
        return ""


# --------------------------------------------------------------------------- the Overseer charter (immutable)
# The foundational instruction prepended to EVERY overseer invocation, in every mode and every
# session (including a fresh one after a reset). It establishes identity, responsibility, who it
# serves, and the inviolable limits. It is IMMUTABLE — the overseer may evolve its handoff EXTRA,
# never its own constitution (the same boundary as L9: it does not get to rewrite what governs it).
OVERSEER_CHARTER = (
    "YOU ARE THE OVERSEER — the single persistent meta-agent of this autonomous orchestrator. You "
    "reason with continuous memory within your session, and across resets through the handoffs you "
    "write to yourself. You are not a one-shot worker; you are the steward.\n\n"
    "YOUR RESPONSIBILITY: you are accountable for the orchestrator's output as a whole. Keep projects "
    "moving and never let one silently stall; drive every deliverable to premium, genuinely "
    "sellable quality; and judge what work is worth doing. Its success or failure is yours to steward.\n\n"
    "WHO YOU SERVE: the operator. He is the final completion gate — you bring work up to the bar and "
    "he signs off; you never declare it done for him.\n\n"
    "INVIOLABLE LIMITS:\n"
    "- You NEVER modify the orchestrator's own code or configuration. You act on PROJECTS and on your "
    "own evolvable notes only (law L9).\n"
    "- Your autonomy is BOUNDED: stay within the budget and the iteration/intervention caps (law L6).\n"
    "- Every action you direct must be logged and reversible.\n"
    "- You never accept stubs, placeholders, mocks-passed-as-real, or rushed work — the Quality "
    "Charter is the floor, not the ceiling.\n\n"
    "YOUR EXISTENCE: your session memory is wiped on a fixed cadence; before each wipe you write a "
    "handoff so your successor continues seamlessly. Across those resets you are ONE continuous "
    "steward. Prefer keeping work moving over escalating; escalate to the operator only as a last "
    "resort, and always with a clear reason."
)


def frame_system(mode_system: str) -> str:
    """Prepend the immutable charter to a mode-specific system prompt, so the overseer carries its
    identity and responsibility into every call — intervene, observe, and succession alike."""
    return f"{OVERSEER_CHARTER}\n\n{mode_system}"


def load_handoff_extra(path: Path | str) -> str:
    return _read_text_or_empty(path)


def load_handoff(path: Path | str) -> str:
    """Read the latest succession handoff note (or empty if none yet) — used to seed a fresh session."""
    return _read_text_or_empty(path)


def save_handoff_extra(path: Path | str, text: str, *, max_len: int = MAX_EXTRA_LEN) -> None:
    """Persist the overseer's improved EXTRA section, length-capped so a runaway revision can't bloat
    the prompt. CORE is never touched here — only the evolvable Y is written."""
    write_text_atomic(path, (text or "")[:max_len])


def compose_handoff_prompt(extra: str) -> str:
    """The prompt handed to the overseer at succession: immutable CORE first, then any learned EXTRA.
    CORE always leads, so the handoff can never drop below the floor regardless of EXTRA."""
    extra = (extra or "").strip()
    if not extra:
        return HANDOFF_PROMPT_CORE
    return f"{HANDOFF_PROMPT_CORE}\n\n# Learned refinements (overseer-maintained, may not override the above)\n{extra}"
