"""infra.notify — best-effort desktop notification (the Da Nang nudge: "something needs your tap").

On macOS this uses ``osascript``; on any other platform, or if the call fails for any reason, it is a
silent no-op so it can NEVER crash the daemon. Notifications are advisory only — the durable event
log stays the single source of truth, and nothing in the system depends on a notification arriving.
"""
from __future__ import annotations

import platform
import shutil
import subprocess


def notify(title: str, message: str) -> bool:
    """Show a desktop notification. Returns True if dispatched, False if unavailable. Never raises."""
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
