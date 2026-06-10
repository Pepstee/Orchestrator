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
import platform
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "state" / "telegram.json"
_TG_TIMEOUT = 5


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


def _send_telegram(title: str, message: str, cfg: dict, opener=None) -> bool:
    """POST to the operator's own chat. Injectable opener for tests; never raises."""
    try:
        data = urllib.parse.urlencode(
            {"chat_id": cfg["chat_id"], "text": f"{title}: {message}"[:4000]}
        ).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{cfg['token']}/sendMessage", data=data)
        open_fn = opener or urllib.request.urlopen
        with open_fn(req, timeout=_TG_TIMEOUT) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def notify(title: str, message: str) -> bool:
    """Fan out to every available channel. Returns True if ANY dispatched. Never raises."""
    sent = _desktop(title, message)
    cfg = _telegram_config()
    if cfg:
        sent = _send_telegram(title, message, cfg) or sent
    return sent
