"""
supervisor.py — Process supervisor for the orchestrator.

Run this INSTEAD of orchestrator.py:

    python supervisor.py

The supervisor starts orchestrator.py as a managed subprocess and handles:
  - Automatic restart on crash (with 5-second back-off).
  - Graceful restart when state/RESTART_REQUESTED is written (the overseer
    agent writes this file when it needs the orchestrator to restart cleanly).
  - Writing state/supervisor_health.json so the overseer can confirm the
    supervisor itself is alive.
  - A max-restart guard (default 20) that stops the loop if something is
    repeatedly crashing to prevent runaway API spend.

The orchestrator process is unmodified — it still reads orchestrator.py.
The supervisor just wraps it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT              = Path(__file__).resolve().parent
STATE_DIR         = ROOT / "state"
RESTART_FILE      = STATE_DIR / "RESTART_REQUESTED"
HEALTH_FILE       = STATE_DIR / "supervisor_health.json"
ORCHESTRATOR_CMD  = [sys.executable, str(ROOT / "orchestrator.py")]

MAX_RESTARTS      = 20          # give up after this many crashes in one session
RESTART_BACKOFF_S = 5.0         # wait between restart attempts
HEALTH_WRITE_S    = 10.0        # how often to write supervisor_health.json
POLL_INTERVAL_S   = 2.0         # how often to check the subprocess + sentinel

_restart_count  = 0
_session_start  = datetime.now(timezone.utc).isoformat()


def _write_health(pid: int, status: str, restart_count: int) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        HEALTH_FILE.write_text(
            json.dumps({
                "supervisor_pid":  os.getpid(),
                "orchestrator_pid": pid,
                "status":          status,
                "restart_count":   restart_count,
                "session_start":   _session_start,
                "last_heartbeat":  datetime.now(timezone.utc).isoformat(),
            }, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{ts}  SUPERVISOR  {msg}", flush=True)


def _terminate(proc: subprocess.Popen, reason: str) -> int:
    """Ask orchestrator to stop cleanly; force-kill after 30 s."""
    # Write SAFE_STOP so the orchestrator drains in-flight tasks
    safe_stop = ROOT / "SAFE_STOP"
    try:
        safe_stop.write_text(reason, encoding="utf-8")
    except OSError:
        pass

    _log(f"Stopping orchestrator (PID {proc.pid}): {reason}")
    deadline = time.time() + 30.0
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(0.5)

    if proc.poll() is None:
        _log(f"Orchestrator did not exit cleanly — force-killing PID {proc.pid}")
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                proc.kill()
        except Exception:
            pass
        proc.wait()

    try:
        safe_stop.unlink(missing_ok=True)
    except OSError:
        pass

    return proc.returncode or 0


def _run_once() -> int:
    """Start orchestrator, monitor it, return exit code."""
    global _restart_count

    _log(f"Starting orchestrator (restart #{_restart_count})")
    proc = subprocess.Popen(ORCHESTRATOR_CMD, cwd=ROOT)
    _write_health(proc.pid, "running", _restart_count)

    last_health_write = time.time()
    restart_reason: str = ""

    try:
        while True:
            # Update health file periodically
            if time.time() - last_health_write >= HEALTH_WRITE_S:
                _write_health(proc.pid, "running", _restart_count)
                last_health_write = time.time()

            # Check if process exited on its own
            rc = proc.poll()
            if rc is not None:
                _log(f"Orchestrator exited with code {rc}")
                _write_health(proc.pid, f"exited(rc={rc})", _restart_count)
                return rc

            # Check restart sentinel
            if RESTART_FILE.exists():
                try:
                    restart_reason = RESTART_FILE.read_text(encoding="utf-8").strip()
                    RESTART_FILE.unlink(missing_ok=True)
                except OSError:
                    restart_reason = "(reason unreadable)"
                _log(f"RESTART_REQUESTED: {restart_reason}")
                _terminate(proc, f"restart requested: {restart_reason}")
                _write_health(proc.pid, "restarting", _restart_count)
                return -1   # signal: restart, not crash

            time.sleep(POLL_INTERVAL_S)

    except KeyboardInterrupt:
        _log("KeyboardInterrupt — shutting down orchestrator")
        _terminate(proc, "supervisor KeyboardInterrupt")
        _write_health(proc.pid, "stopped", _restart_count)
        raise


def main() -> None:
    global _restart_count

    _log(f"Supervisor started (PID {os.getpid()}) — managing {' '.join(ORCHESTRATOR_CMD)}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # BUG-11: remove any stale SAFE_STOP left over from a previous supervisor
    # crash during _terminate(). A SAFE_STOP at startup is definitionally orphaned.
    stale_stop = ROOT / "SAFE_STOP"
    if stale_stop.exists():
        _log("Removing stale SAFE_STOP from previous session")
        try:
            stale_stop.unlink(missing_ok=True)
        except OSError:
            pass

    try:
        while _restart_count < MAX_RESTARTS:
            rc = _run_once()
            _restart_count += 1

            if rc == 0:
                # Clean exit (SAFE_STOP or natural completion) — do not restart
                _log("Orchestrator exited cleanly — supervisor stopping")
                break

            if rc == -1:
                # Restart was explicitly requested
                _log(f"Restarting orchestrator now (restart {_restart_count}/{MAX_RESTARTS})")
                time.sleep(1.0)
                continue

            # Crashed — brief back-off then restart
            _log(
                f"Orchestrator crashed (rc={rc}). "
                f"Restart {_restart_count}/{MAX_RESTARTS} — backing off {RESTART_BACKOFF_S:.0f}s."
            )
            time.sleep(RESTART_BACKOFF_S)

        else:
            _log(f"Max restarts ({MAX_RESTARTS}) reached — supervisor giving up.")

    except KeyboardInterrupt:
        _log("Supervisor interrupted by keyboard — stopping.")

    finally:
        _write_health(pid=0, status="supervisor_exited", restart_count=_restart_count)


if __name__ == "__main__":
    main()