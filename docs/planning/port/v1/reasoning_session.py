# reasoning_session.py
"""
Persistent multi-turn reasoning sessions for the orchestrator's Reasoning Engine.

A ReasoningSession accumulates the history of all failure descriptions and
guidance responses for a single failing task across every retry attempt.
When the Reasoner calls Claude, it formats this history into a single prompt
so Claude sees the full pattern of what has been tried and why it failed.

Sessions are stored atomically in state/reasoning_sessions/{task_id}.json.
They expire after SESSION_MAX_AGE_HOURS (matching the ProposedChange TTL).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SESSION_MAX_AGE_HOURS: float = 48.0
SESSION_DIR = Path("state/reasoning_sessions")
_SAFE_ID_RE = re.compile(r"[^\w\-]")


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class ReasoningAttempt:
    """One failed attempt and the guidance that was produced for the next one."""
    attempt_number: int
    failure_summary: str        # What went wrong (from AgentResult.summary / triage)
    guidance_given: str         # What the Reasoner told the builder to do
    approach_used: str          # The approach directive ("retry_with_changes" etc.)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ReasoningAttempt":
        return cls(
            attempt_number = int(d.get("attempt_number", 0)),
            failure_summary = str(d.get("failure_summary", "")),
            guidance_given  = str(d.get("guidance_given", "")),
            approach_used   = str(d.get("approach_used", "")),
            timestamp       = float(d.get("timestamp", 0.0)),
        )


@dataclass
class ReasoningSession:
    """
    Accumulated reasoning context for a specific failing task.

    Keyed by task_id. Each call to Reasoner.get_repair_guidance() appends
    one ReasoningAttempt. The full list is serialised into the Claude prompt
    so each call sees all prior attempts.
    """
    session_id: str                          # == task_id of the failing task
    task_type: str = "unknown"
    task_title: str = ""
    namespace: str = "default"
    attempts: List[ReasoningAttempt] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    def is_expired(self, now: Optional[float] = None) -> bool:
        age_h = ((now or time.time()) - self.created_at) / 3600
        return age_h > SESSION_MAX_AGE_HOURS

    # ── Mutation ──────────────────────────────────────────────────────────────

    def add_turn(self, role: str, content: str) -> None:
        """Append a raw turn to the session (used for retention testing and general context).

        Stores turns in metadata["turns"] so they survive to_dict/from_dict.
        Reference: HS8 / Evaluating Memory in LLM Agents (arXiv:2507.05257).
        """
        turns = self.metadata.setdefault("turns", [])
        turns.append({"role": role, "content": content})

    def get_context(self) -> str:
        """Return the full session context as a plain-text string.

        Includes all raw turns (from add_turn) and all reasoning attempt summaries.
        Used by tests to assert that facts injected early are still present.
        Reference: HS8 / Evaluating Memory in LLM Agents (arXiv:2507.05257).
        """
        parts = []
        for turn in self.metadata.get("turns", []):
            parts.append(f"[{turn.get('role', 'unknown')}]: {turn.get('content', '')}")
        for attempt in self.attempts:
            parts.append(
                f"[attempt {attempt.attempt_number}] {attempt.failure_summary} / {attempt.guidance_given}"
            )
        return "\n".join(parts)

    def record_attempt(
        self,
        failure_summary: str,
        guidance_given: str,
        approach_used: str = "",
    ) -> ReasoningAttempt:
        """Append an attempt record and return it."""
        attempt = ReasoningAttempt(
            attempt_number = self.attempt_count + 1,
            failure_summary = failure_summary,
            guidance_given  = guidance_given,
            approach_used   = approach_used,
        )
        self.attempts.append(attempt)
        self.updated_at = time.time()
        return attempt

    def compute_trajectory_health(self) -> tuple:
        """
        Compute (status, notes) from the attempt history.

        status is one of:
          "stable"    — fewer than 2 attempts, or approaches vary without looping
          "degrading" — same approach used consecutively (stuck), or a prior
                        escalation did not resolve the task
          "drift"     — 3+ distinct approaches tried with no convergence

        Inspired by the HTC (Hypothesis Testing Cycle) health model: a healthy
        repair trajectory converges on a root cause; degrading and drift patterns
        signal that more attempts are unlikely to help without human intervention.
        """
        if len(self.attempts) < 2:
            return ("stable", "")

        approaches = [a.approach_used for a in self.attempts]

        # Consecutive repeat — stuck in the same approach loop
        for i in range(1, len(approaches)):
            if approaches[i] and approaches[i] == approaches[i - 1]:
                return (
                    "degrading",
                    f"Approach '{approaches[i]}' repeated consecutively on attempts "
                    f"{i} and {i + 1}.",
                )

        # Prior escalation that did not resolve the task
        if "escalate" in approaches:
            return (
                "degrading",
                "Escalation has already been attempted without resolution.",
            )

        # Drift: 3+ distinct non-empty approaches with no convergence
        unique = {a for a in approaches if a}
        if len(unique) >= 3:
            return (
                "drift",
                f"Trajectory drift: {len(unique)} distinct approaches tried "
                f"({', '.join(sorted(unique))}) — no convergence.",
            )

        return ("stable", f"{len(self.attempts)} attempts; approaches varied.")

    def format_history_for_prompt(self) -> str:
        """
        Return a human-readable summary of all prior attempts suitable for
        inclusion in a Claude prompt. Each attempt is a labelled block.
        """
        if not self.attempts:
            return "(no prior attempts recorded)"
        blocks = []
        for a in self.attempts:
            block = (
                f"### Attempt {a.attempt_number}\n"
                f"**What failed:** {a.failure_summary[:800]}\n"
                f"**Guidance given:** {a.guidance_given[:600]}\n"
                f"**Approach directive:** {a.approach_used}\n"
            )
            blocks.append(block)
        return "\n".join(blocks)

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id":  self.session_id,
            "task_type":   self.task_type,
            "task_title":  self.task_title,
            "namespace":   self.namespace,
            "attempts":    [a.to_dict() for a in self.attempts],
            "created_at":  self.created_at,
            "updated_at":  self.updated_at,
            "metadata":    self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ReasoningSession":
        return cls(
            session_id  = str(d["session_id"]),
            task_type   = str(d.get("task_type", "unknown")),
            task_title  = str(d.get("task_title", "")),
            namespace   = str(d.get("namespace", "default")),
            attempts    = [ReasoningAttempt.from_dict(a) for a in d.get("attempts", [])],
            created_at  = float(d.get("created_at", time.time())),
            updated_at  = float(d.get("updated_at", time.time())),
            metadata    = dict(d.get("metadata", {})),
        )


# ── Store ─────────────────────────────────────────────────────────────────────

class ReasoningSessionStore:
    """
    Manages persistence of ReasoningSession objects.

    All writes are atomic (write to temp file + os.replace). Thread-safety:
    not thread-safe — designed for the single-threaded orchestrator task path.
    """

    def __init__(self, session_dir: Path = SESSION_DIR) -> None:
        self._dir = Path(session_dir)

    def _session_path(self, session_id: str) -> Path:
        safe = _SAFE_ID_RE.sub("_", session_id)
        return self._dir / f"{safe}.json"

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _unlink(self, p: Path) -> None:
        """Best-effort delete; silently ignores errors."""
        try:
            p.unlink()
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, session_id: str) -> Optional[ReasoningSession]:
        """Load a session. Returns None if missing, expired, or corrupt."""
        p = self._session_path(session_id)
        if not p.exists() or p.stat().st_size == 0:
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            session = ReasoningSession.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("reasoning_session: corrupt %s (%s) — discarding", session_id, exc)
            self._unlink(p)
            return None

        if session.is_expired():
            logger.info("reasoning_session: %s expired — discarding", session_id)
            self._unlink(p)
            return None

        return session

    def load_or_create(
        self,
        session_id: str,
        task_type: str = "unknown",
        task_title: str = "",
        namespace: str = "default",
    ) -> ReasoningSession:
        """Load an existing session or create a fresh one."""
        session = self.load(session_id)
        if session is not None:
            return session
        return ReasoningSession(
            session_id = session_id,
            task_type  = task_type,
            task_title = task_title,
            namespace  = namespace,
        )

    def save(self, session: ReasoningSession) -> None:
        """Atomically write the session to disk."""
        self._ensure_dir()
        p = self._session_path(session.session_id)
        payload = json.dumps(session.to_dict(), indent=2, ensure_ascii=False)
        # Write via temp file + rename for atomicity
        tmp = p.with_suffix(".tmp")
        data = payload.encode("utf-8")
        chunk_size = 1024
        with open(tmp, "wb") as f:
            for i in range(0, len(data), chunk_size):
                f.write(data[i:i + chunk_size])
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(p)

    def delete(self, session_id: str) -> None:
        """Delete a session file. Silently ignores missing sessions."""
        p = self._session_path(session_id)
        self._unlink(p)

    def expire_old_sessions(self) -> int:
        """
        Remove sessions older than SESSION_MAX_AGE_HOURS.

        Returns the number of sessions removed.
        """
        if not self._dir.exists():
            return 0
        now = time.time()
        removed = 0
        for p in self._dir.glob("*.json"):
            if p.stat().st_size == 0:
                self._unlink(p)
                removed += 1
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                created_at = float(data.get("created_at", 0.0))
                age_h = (now - created_at) / 3600
                if age_h > SESSION_MAX_AGE_HOURS:
                    self._unlink(p)
                    removed += 1
            except Exception:
                # Corrupt file — remove it
                self._unlink(p)
                removed += 1
        return removed
