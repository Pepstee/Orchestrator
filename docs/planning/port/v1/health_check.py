"""
health_check.py — Is the orchestrator alive and recently active?

Inspects the PID file and current_state.json to produce one of three verdicts:

    healthy   — PID file exists, process is alive, state was updated recently.
    degraded  — Process is alive but state is missing or stale.
    down      — No PID file, or PID points at a dead process.

Designed for cron, manual checking, and watch-mode polling.  Exit codes are
machine-friendly: 0 healthy, 1 down, 2 degraded.  Returns no false-positives
on macOS notifications unless explicitly requested with --notify.

Examples
--------

One-shot check, human output:
    python3 health_check.py

Silent unless something is wrong (cron-friendly):
    python3 health_check.py --quiet

Send a macOS notification on unhealthy state:
    python3 health_check.py --notify

JSON output for scripts:
    python3 health_check.py --json

Watch mode — poll every 30s, alert only when verdict changes:
    python3 health_check.py --watch

Tune the staleness threshold (default 5 minutes):
    python3 health_check.py --stale-minutes 10
"""
from __future__ import annotations

import argparse
import contextlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import public_api as o  # noqa: E402  (Stage 2.5: consume the supported facade, not orchestrator internals)


DEFAULT_STALE_MINUTES = 5
DEFAULT_WATCH_INTERVAL = 30


# ── Probes ─────────────────────────────────────────────────────────────────────

def _read_pid() -> Optional[int]:
    if not o.PID_FILE.exists():
        return None
    try:
        return int(o.PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _read_state() -> Optional[Dict[str, Any]]:
    if not o.CURRENT_STATE_FILE.exists():
        return None
    try:
        return json.loads(o.CURRENT_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _state_age_seconds(state: Dict[str, Any]) -> Optional[float]:
    last_cycle = state.get("last_cycle_at")
    if not isinstance(last_cycle, str):
        return None
    try:
        dt = datetime.fromisoformat(last_cycle)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _notify(title: str, message: str) -> None:
    """Send a desktop notification — macOS only.  Silent on other platforms."""
    if platform.system() != "Darwin":
        return
    script = (
        f'display notification "{message}" '
        f'with title "Orchestrator" subtitle "{title}"'
    )
    with contextlib.suppress(Exception):
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=3)


# ── Core check ─────────────────────────────────────────────────────────────────

def check_health(stale_minutes: int = DEFAULT_STALE_MINUTES) -> Dict[str, Any]:
    """Inspect the orchestrator and return a structured verdict.

    Returns a dict with at minimum a 'verdict' key set to one of
    'healthy', 'degraded', or 'down', plus diagnostic fields and a
    'reasons' list explaining the verdict.
    """
    # Bootstrap so we read the right paths if tasks_root is set.
    config = o.Config.load()
    if config.tasks_root:
        o._apply_tasks_root(config.tasks_root)

    result: Dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "down",
        "pid_file_exists": False,
        "pid": None,
        "process_alive": False,
        "state_file_exists": False,
        "system_status": None,
        "last_cycle_age_seconds": None,
        "stale_threshold_seconds": stale_minutes * 60,
        "reasons": [],
    }

    pid = _read_pid()
    if pid is None:
        result["reasons"].append("No PID file — orchestrator does not appear to be running.")
        return result

    result["pid_file_exists"] = True
    result["pid"] = pid

    if not o._pid_is_alive(pid):
        result["reasons"].append(
            f"PID file points to {pid}, but no live process with that PID exists."
        )
        return result

    result["process_alive"] = True

    state = _read_state()
    if state is None:
        result["reasons"].append("current_state.json is missing or unreadable.")
        result["verdict"] = "degraded"
        return result

    result["state_file_exists"] = True
    result["system_status"] = state.get("system_status")

    age = _state_age_seconds(state)
    result["last_cycle_age_seconds"] = age

    if age is None:
        result["reasons"].append("current_state.json has no parseable last_cycle_at field.")
        result["verdict"] = "degraded"
        return result

    if age > stale_minutes * 60:
        result["reasons"].append(
            f"last_cycle_at is {int(age)}s old (threshold {stale_minutes * 60}s) — "
            f"orchestrator may be hung."
        )
        result["verdict"] = "degraded"
        return result

    result["verdict"] = "healthy"
    return result


# ── Output formatting ──────────────────────────────────────────────────────────

_VERDICT_GLYPHS = {"healthy": "[OK]", "degraded": "[!!]", "down": "[XX]"}


def format_human(result: Dict[str, Any]) -> str:
    verdict = result["verdict"]
    glyph = _VERDICT_GLYPHS.get(verdict, "[??]")

    lines = [f"{glyph} Orchestrator: {verdict.upper()}"]

    if result["pid_file_exists"]:
        alive = "alive" if result["process_alive"] else "DEAD"
        lines.append(f"  PID {result['pid']} ({alive})")
    else:
        lines.append("  PID file: (missing)")

    if result["system_status"] is not None:
        age = result["last_cycle_age_seconds"]
        age_str = f"{int(age)}s ago" if age is not None else "unknown"
        lines.append(f"  status: {result['system_status']}  (last cycle {age_str})")

    for reason in result["reasons"]:
        lines.append(f"  ! {reason}")

    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────────────

_EXIT_CODES = {"healthy": 0, "down": 1, "degraded": 2}


def _emit(result: Dict[str, Any], args: argparse.Namespace) -> None:
    if args.json:
        print(json.dumps(result, indent=2), flush=True)
    elif not args.quiet or result["verdict"] != "healthy":
        print(format_human(result), flush=True)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="health_check",
        description="Check whether the orchestrator is alive and recently active.",
    )
    p.add_argument(
        "--stale-minutes",
        type=int,
        default=DEFAULT_STALE_MINUTES,
        help=f"Mark as degraded if last_cycle_at exceeds this age (default {DEFAULT_STALE_MINUTES}).",
    )
    p.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress output when verdict is 'healthy'.",
    )
    p.add_argument(
        "--notify",
        action="store_true",
        help="Send a macOS notification when verdict is not 'healthy'.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable text.",
    )
    p.add_argument(
        "--watch",
        action="store_true",
        help="Poll continuously; alert only on verdict change.",
    )
    p.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_WATCH_INTERVAL,
        help=f"Watch-mode poll interval in seconds (default {DEFAULT_WATCH_INTERVAL}).",
    )
    return p


def _watch_loop(args: argparse.Namespace) -> int:
    previous: Optional[str] = None
    try:
        while True:
            result = check_health(args.stale_minutes)
            verdict = result["verdict"]
            if verdict != previous:
                _emit(result, args)
                if args.notify and verdict != "healthy":
                    reason = result["reasons"][0] if result["reasons"] else verdict
                    _notify("Health check", f"{verdict.upper()} — {reason}")
                previous = verdict
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.watch:
        return _watch_loop(args)

    result = check_health(args.stale_minutes)
    _emit(result, args)
    if args.notify and result["verdict"] != "healthy":
        reason = result["reasons"][0] if result["reasons"] else result["verdict"]
        _notify("Health check", f"{result['verdict'].upper()} — {reason}")
    return _EXIT_CODES.get(result["verdict"], 1)


if __name__ == "__main__":
    sys.exit(main())
