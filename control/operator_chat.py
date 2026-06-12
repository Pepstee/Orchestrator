"""control.operator_chat — the operator's inbound line to the Overseer (DG-10b's return path).

Outbound has existed since 10 Jun: notify() → the operator's whitelisted Telegram chat. This module
is the other direction. Each daemon cycle (throttled) it asks Telegram for new messages
(getUpdates, zero-timeout so the cycle never blocks), keeps ONLY messages from the operator's own
chat_id (sender lock — anyone else's words are dropped unread; an open bot would be a steering
wheel for the whole fleet), and turns each one into a high-priority `oversee` task that rides the
SAME persistent session as the hourly pulses — the operator's words become turns inside the one
continuous mind, not prompts to a stateless wrapper. The overseer replies through notify() in its
own words (verbatim — no plain-speech rewrite for a direct conversation).

Durability: the Telegram update offset is persisted atomically (state/telegram_offset.json) AFTER
enqueueing, so a daemon restart never loses a message; the crash window re-delivers at most once
(at-least-once, like the event log — a repeated question is harmless, a swallowed one is not).
First contact (no offset file yet) drains the backlog WITHOUT enqueueing: messages sent before
this feature existed must not replay as a flood of pulses.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Callable

from core.models import Task
from dispatch.repository import TaskRepository
from infra.atomic_io import write_json_atomic
from infra.notify import telegram_config
from memory.overseer import load_session

POLL_SECONDS = 5.0          # politeness floor between getUpdates calls (the cycle is ~2s)
_HTTP_TIMEOUT = 5           # same budget as outbound notify — the daemon never waits on the phone
MAX_MESSAGE_CHARS = 4000    # one Telegram message; the payload stays bounded (A3)
OFFSET_FILE = "telegram_offset.json"


def _default_state_root() -> Path:
    return Path(__file__).resolve().parents[1] / "state"


def _read_offset(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data["offset"])
    except Exception:
        return None


def _fetch_updates(cfg: dict, offset: int | None, opener=None) -> list[dict]:
    """GET getUpdates. Injectable opener for tests; never raises, never blocks the cycle
    (timeout=0 → Telegram answers immediately with whatever is queued)."""
    try:
        query = {"timeout": 0}
        if offset is not None:
            query["offset"] = offset
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{cfg['token']}/getUpdates?"
            + urllib.parse.urlencode(query))
        open_fn = opener or urllib.request.urlopen
        with open_fn(req, timeout=_HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = data.get("result") if isinstance(data, dict) and data.get("ok") else None
        return result if isinstance(result, list) else []
    except Exception:
        return []


def poll_operator_messages(
    repo: TaskRepository,
    session_path: Path,
    meta: dict,
    *,
    project: str = "__overseer__",
    state_root: Path | None = None,
    context_fn: Callable[[], str] | None = None,
    now: float | None = None,
    opener=None,
    throttle_s: float = POLL_SECONDS,
) -> int:
    """The daemon's per-cycle poll. Returns the number of operator messages enqueued.

    Quiet exits, in order: throttled; no telegram config (feature is config-gated, like
    outbound); no persistent session yet (the overseer must exist before it can be spoken
    to — messages simply wait at Telegram's side, nothing is lost)."""
    now = time.time() if now is None else now
    if now - meta.get("chat_last_poll", 0.0) < throttle_s:
        return 0
    meta["chat_last_poll"] = now
    cfg = telegram_config()
    if not cfg:
        return 0
    session = load_session(session_path)
    if session is None:
        return 0
    root = state_root or _default_state_root()
    offset_path = root / OFFSET_FILE
    offset = _read_offset(offset_path)
    updates = _fetch_updates(cfg, offset, opener)
    if not updates:
        return 0
    newest = max(int(u.get("update_id", 0)) for u in updates)
    if offset is None:
        # First contact: acknowledge history without acting on it (no replay-flood).
        write_json_atomic(offset_path, {"offset": newest + 1})
        return 0
    context = context_fn() if context_fn else ""
    enqueued = 0
    for u in updates:
        msg = u.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        text = str(msg.get("text") or "").strip()
        if chat_id != str(cfg["chat_id"]) or not text:
            continue   # sender lock: not the operator (or not text) — skip, but advance past it
        repo.create(Task(
            task_id=uuid.uuid4().hex[:12],
            title=f"operator: {text[:60]}",
            task_type="oversee",
            project=project,
            priority=10,   # the operator outranks the metronome among ready tasks
            payload={"mode": "operator_message", "message": text[:MAX_MESSAGE_CHARS],
                     "session_id": session.session_id, "resume": True, "context": context},
        ))
        enqueued += 1
    write_json_atomic(offset_path, {"offset": newest + 1})
    return enqueued
