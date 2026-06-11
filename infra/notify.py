"""infra.notify — best-effort notification: desktop + Telegram (the Da Nang nudge, remotely).

Desktop uses ``osascript`` on macOS. Telegram (ratified 10 Jun, H3 — the FIRST whitelisted
exception to the stop-and-don't outbound policy, DG-10b) sends to the OPERATOR'S OWN chat only,
config-gated: it activates iff ``state/telegram.json`` exists with ``{"token": ..., "chat_id":
...}`` (gitignored — secrets never enter the repo). Any failure anywhere is a silent no-op so a
notification can NEVER crash the daemon. Notifications are advisory only — the durable event
log stays the single source of truth, and nothing in the system depends on one arriving.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "state" / "telegram.json"
_TG_TIMEOUT = 5

# Plain-speech mode (operator request, 11 Jun): phone messages are rewritten for a non-engineer
# before sending — the event log keeps the technical truth; the phone gets the human version.
# Disable with AGENTIC_NOTIFY_PLAIN=0 or {"plain": false} in telegram.json.
_PLAIN_PROMPT = (
    "You translate terse status messages from an autonomous software factory into plain speech "
    "for its owner's phone. Rewrite the message below so a non-engineer mate instantly gets "
    "what happened and whether anything is needed from him. Rules: at most 3 short sentences; "
    "keep exact numbers, names and times; no jargon or acronyms — say it in everyday words; "
    "lead with the practical meaning; if it's good news say so plainly; if something needs the "
    "owner, say exactly what. Output ONLY the rewritten message.\n\nMessage: "
)


def _plain_enabled(cfg: dict) -> bool:
    if os.environ.get("AGENTIC_NOTIFY_PLAIN", "") in ("0", "false", "no"):
        return False
    return bool(cfg.get("plain", True))


def _plainify(title: str, message: str, translator=None) -> str:
    """Best-effort plain-speech rewrite. NEVER raises and NEVER goes silent: any failure,
    empty output, or slow call falls back to the original technical message."""
    original = f"{title}: {message}"
    try:
        if translator is None:
            from infra.llm import call_llm

            def translator(prompt: str) -> str:
                return call_llm("claude", "haiku", prompt, timeout=30).text
        out = (translator(_PLAIN_PROMPT + original) or "").strip()
        return out[:1000] if out else original
    except Exception:
        return original


def _desktop(title: str, message: str) -> bool:
    try:
        if platform.system() == "Darwin" and shutil.which("osascript"):
            head = title.replace('"', "'")
            text = message.replace('"', "'")
            subprocess.run(
                ["osascript", "-e", f'display notification "{text}" with title "{head}"'],
                check=False, capture_output=True, timeout=5,
            )
            return True
    except Exception:
        return False
    return False


def _telegram_config(path: Path | None = None) -> dict | None:
    p = path or CONFIG_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, dict) and data.get("token") and data.get("chat_id"):
        return data
    return None


def _send_telegram(text: str, cfg: dict, opener=None) -> bool:
    """POST to the operator's own chat. Injectable opener for tests; never raises."""
    try:
        data = urllib.parse.urlencode(
            {"chat_id": cfg["chat_id"], "text": text[:4000]}
        ).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{cfg['token']}/sendMessage", data=data)
        open_fn = opener or urllib.request.urlopen
        with open_fn(req, timeout=_TG_TIMEOUT) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def notify(title: str, message: str) -> bool:
    """Fan out to every available channel. Returns True if ANY dispatched. Never raises.
    Desktop gets the technical message; the phone gets the plain-speech rewrite."""
    sent = _desktop(title, message)
    cfg = _telegram_config()
    if cfg:
        text = _plainify(title, message) if _plain_enabled(cfg) else f"{title}: {message}"
        sent = _send_telegram(text, cfg) or sent
    return sent
