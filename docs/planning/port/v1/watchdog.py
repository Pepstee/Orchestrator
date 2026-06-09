"""
watchdog.py - Programmatic health monitor for the orchestrator.

Runs as a background thread inside the orchestrator.  Makes zero LLM calls.
On every tick it:
  1. Reads new journal lines incrementally (never re-reads old ones).
  2. Checks sentinel files and state/ directories.
  3. Emits WatchdogAlerts to state/watchdog_alerts.json.
  4. Auto-fixes simple issues it recognises (stale pause file, corrupt JSON).
  5. Escalates unresolved HIGH/CRITICAL alerts to the overseer via task injection.

Design intent: over time the watchdog pattern library should grow (via
teach_watchdog actions from the overseer) until it can handle most issues
programmatically, reducing LLM calls toward zero.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class AlertType(str, Enum):
    DEVELOPMENT_PAUSED_STALE  = "development_paused_stale"
    NO_READY_TASKS            = "no_ready_tasks"
    AGENT_PARSE_FAILURE_LOOP  = "agent_parse_failure_loop"
    STUCK_TASKS_CORRUPT       = "stuck_tasks_corrupt"
    VALIDATE_TASKS_ORPHANED   = "validate_tasks_orphaned"
    VELOCITY_ESCALATED        = "velocity_escalated"
    ORCHESTRATOR_IDLE         = "orchestrator_idle"
    NEEDS_ATTENTION_FILE      = "needs_attention_file"
    CONFIG_CORRUPT            = "config_corrupt"
    JOURNAL_TAIL_ERRORS       = "journal_tail_errors"
    # New alert types for extended monitoring
    STALE_HEARTBEAT           = "stale_heartbeat"
    NO_HEARTBEAT              = "no_heartbeat"
    HIGH_QUEUE_DEPTH          = "high_queue_depth"
    STUCK_TASK                = "stuck_task"
    JOURNAL_GAP               = "journal_gap"


class Severity(str, Enum):
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


_OVERSEER_COOLDOWN_S: float = 300.0
_IDLE_THRESHOLD_S:    float = 1800.0
_HEARTBEAT_STALE_S:   float = 1200.0   # 20 min — supervisor heartbeat too old
_QUEUE_DEPTH_ALERT:   int   = 50       # task files in queue before alert
_STUCK_TASK_S:        float = 900.0    # 15 min — in-progress task assumed stuck
_JOURNAL_GAP_S:       float = 600.0    # 10 min — no new journal entries


@dataclass
class WatchdogAlert:
    alert_id:   str
    alert_type: str
    severity:   str
    first_seen: float
    last_seen:  float
    count:      int
    evidence:   str
    auto_fixed: bool = False
    resolved:   bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WatchdogAlert":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


class Watchdog:
    """Stateful health monitor.  Call tick() periodically from a thread."""

    ALERTS_FILE     = "state/watchdog_alerts.json"
    TICK_INTERVAL_S = 30.0

    def __init__(self, root: Path, enqueue_fn: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self.root     = root
        self._enqueue = enqueue_fn
        self._alerts: Dict[str, WatchdogAlert] = {}
        self._lock    = threading.Lock()
        self._journal_pos: int = 0
        self._journal_inode: Optional[int] = None  # BUG-08: track inode for rotation detection
        self._journal_path = root / "journal" / "events.log"
        self._last_overseer_trigger: float = 0.0
        self._last_task_completed_at: float = time.time()
        self._parse_failure_times: List[float] = []
        self._load_alerts()

    def tick(self) -> List[WatchdogAlert]:
        try:
            self._read_journal_incremental()
            self._check_development_paused()
            self._check_needs_attention()
            self._check_stuck_tasks_integrity()
            self._check_velocity_state()
            self._check_config_files()
            self._check_orchestrator_idle()
            self._check_ready_tasks()       # BUG-03
            self._check_validate_orphans()  # BUG-04
            self._check_supervisor_heartbeat()
            self._check_queue_depth()
            self._check_stuck_in_progress()
            self._check_journal_gap()
            self._save_alerts()
            self._maybe_trigger_overseer()
        except Exception:
            pass
        return self.get_active_alerts()

    def get_active_alerts(self) -> List[WatchdogAlert]:
        with self._lock:
            return [a for a in self._alerts.values() if not a.resolved]

    def resolve_alert(self, alert_id: str) -> None:
        with self._lock:
            if alert_id in self._alerts:
                self._alerts[alert_id].resolved = True

    def alert_summary(self) -> str:
        active = self.get_active_alerts()
        if not active:
            return "No active watchdog alerts."
        # BUG-02: use integer weight map so CRITICAL > HIGH > MEDIUM > LOW
        _SEV_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        lines = [f"ACTIVE WATCHDOG ALERTS ({len(active)}):"]
        for a in sorted(active, key=lambda x: (_SEV_ORDER.get(x.severity, 0), x.count), reverse=True)[:8]:
            age_min = int((time.time() - a.first_seen) / 60)
            lines.append(f"  [{a.severity}] {a.alert_type} (x{a.count}, {age_min}min): {a.evidence[:100]}")
        return "\n".join(lines)

    def _read_journal_incremental(self) -> None:
        if not self._journal_path.exists():
            return
        try:
            stat = self._journal_path.stat()
            # BUG-08: detect rotation by inode change OR shrinkage
            if stat.st_ino != self._journal_inode or stat.st_size < self._journal_pos:
                self._journal_pos = 0
                self._journal_inode = stat.st_ino
            with open(self._journal_path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._journal_pos)
                new_text = fh.read()
                self._journal_pos = fh.tell()
            parse_fail_count = 0
            error_count = 0
            for line in new_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg   = ev.get("message", "")
                etype = ev.get("event_type", "")
                if etype == "task_completed":
                    self._last_task_completed_at = time.time()
                if "could not parse" in msg.lower() or "unparseable" in msg.lower():
                    self._parse_failure_times.append(time.time())
                    self._parse_failure_times = self._parse_failure_times[-20:]
                    parse_fail_count += 1
                if etype in ("agent_error", "worker_exception"):
                    error_count += 1
            recent_pf = [t for t in self._parse_failure_times if time.time() - t < 600]
            if len(recent_pf) >= 3:
                self._emit(AlertType.AGENT_PARSE_FAILURE_LOOP, Severity.HIGH, f"{len(recent_pf)} parse failures in last 10 min")
            else:
                self._resolve_if_present(AlertType.AGENT_PARSE_FAILURE_LOOP)
            if error_count >= 5:
                self._emit(AlertType.JOURNAL_TAIL_ERRORS, Severity.MEDIUM, f"{error_count} error events in latest journal batch")
        except OSError:
            pass

    def _check_development_paused(self) -> None:
        pause_file = self.root / "DEVELOPMENT_PAUSED"
        if not pause_file.exists():
            self._resolve_if_present(AlertType.DEVELOPMENT_PAUSED_STALE)
            return
        try:
            content = pause_file.read_text(encoding="utf-8", errors="replace").strip()
            age_s   = time.time() - pause_file.stat().st_mtime
        except OSError:
            return
        if age_s < 120:
            return
        m = re.search(r"[0-9a-f]{8}(?:-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?", content)
        if m:
            tid = m.group(0).replace("-", "")[:8]
            if list((self.root / "tasks" / "in_progress").glob(f"{tid}*.json")):
                return
        try:
            pause_file.unlink()
            self._emit(AlertType.DEVELOPMENT_PAUSED_STALE, Severity.HIGH, f"Stale DEVELOPMENT_PAUSED ({int(age_s/60)}min) - auto-removed: {content[:80]}", auto_fixed=True)
        except OSError:
            self._emit(AlertType.DEVELOPMENT_PAUSED_STALE, Severity.HIGH, f"Stale DEVELOPMENT_PAUSED ({int(age_s/60)}min), cannot remove: {content[:80]}")

    def _check_needs_attention(self) -> None:
        # BUG-06: check both state/NEEDS_ATTENTION and the root-level NEEDS_ATTENTION
        candidates = (
            self.root / "state" / "NEEDS_ATTENTION",
            self.root / "NEEDS_ATTENTION",
        )
        for na in candidates:
            if na.exists():
                try:
                    content = na.read_text(encoding="utf-8", errors="replace").strip()
                    age_min = int((time.time() - na.stat().st_mtime) / 60)
                except OSError:
                    content, age_min = "(unreadable)", 0
                self._emit(AlertType.NEEDS_ATTENTION_FILE, Severity.HIGH, f"NEEDS_ATTENTION present {age_min}min: {content[:120]}")
                return
        self._resolve_if_present(AlertType.NEEDS_ATTENTION_FILE)

    def _check_stuck_tasks_integrity(self) -> None:
        path = self.root / "state" / "stuck_tasks.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(data, dict):
                raise ValueError("root is not a dict")
            self._resolve_if_present(AlertType.STUCK_TASKS_CORRUPT)
        except Exception as exc:
            try:
                path.write_text("{}", encoding="utf-8")
                self._emit(AlertType.STUCK_TASKS_CORRUPT, Severity.HIGH, f"stuck_tasks.json corrupt ({exc}) - auto-reset", auto_fixed=True)
            except OSError:
                self._emit(AlertType.STUCK_TASKS_CORRUPT, Severity.HIGH, f"stuck_tasks.json corrupt and unwritable: {exc}")

    def _check_config_files(self) -> None:
        for fname in ("orchestrator_config.json", "self_dev_policy.json"):
            p = self.root / fname
            if not p.exists():
                continue
            try:
                json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                self._emit(AlertType.CONFIG_CORRUPT, Severity.CRITICAL, f"{fname} invalid JSON: {str(exc)[:100]}")
                return
        self._resolve_if_present(AlertType.CONFIG_CORRUPT)

    def _check_velocity_state(self) -> None:
        ckpt = self.root / "state" / "session_checkpoint.json"
        if not ckpt.exists():
            return
        try:
            data   = json.loads(ckpt.read_text(encoding="utf-8", errors="replace"))
            vstate = data.get("velocity_state", "")
            if vstate in ("ESCALATED", "STALLED"):
                self._emit(AlertType.VELOCITY_ESCALATED, Severity.HIGH, f"VelocityMonitor is {vstate}")
            else:
                self._resolve_if_present(AlertType.VELOCITY_ESCALATED)
        except Exception:
            pass

    def _check_orchestrator_idle(self) -> None:
        queue_dir = self.root / "tasks" / "queue"
        prog_dir  = self.root / "tasks" / "in_progress"
        idle_s    = time.time() - self._last_task_completed_at
        has_queued = queue_dir.exists() and any(f.stat().st_size > 0 for f in queue_dir.glob("*.json"))
        has_active = prog_dir.exists() and any(f.stat().st_size > 0 for f in prog_dir.glob("*.json"))
        if has_queued and not has_active and idle_s > _IDLE_THRESHOLD_S:
            self._emit(AlertType.ORCHESTRATOR_IDLE, Severity.HIGH, f"Queue non-empty, nothing in-progress, no completions in {int(idle_s/60)}min")
        elif not has_queued or has_active:
            self._resolve_if_present(AlertType.ORCHESTRATOR_IDLE)

    def _check_ready_tasks(self) -> None:
        """BUG-03: Emit NO_READY_TASKS when all task directories are empty."""
        dirs = [
            self.root / "tasks" / "queue",
            self.root / "tasks" / "in_progress",
            self.root / "tasks" / "blocked",
        ]
        for d in dirs:
            if d.exists() and any(f.stat().st_size > 0 for f in d.glob("*.json")):
                self._resolve_if_present(AlertType.NO_READY_TASKS)
                return
        idle_s = time.time() - self._last_task_completed_at
        if idle_s > _IDLE_THRESHOLD_S:
            self._emit(
                AlertType.NO_READY_TASKS,
                Severity.MEDIUM,
                f"All task directories empty; no completions in {int(idle_s / 60)}min",
            )
        else:
            self._resolve_if_present(AlertType.NO_READY_TASKS)

    def _check_validate_orphans(self) -> None:
        """BUG-04: Emit VALIDATE_TASKS_ORPHANED for validate tasks with no parent develop task."""
        _ORPHAN_AGE_S = 600  # 10 minutes
        now = time.time()
        all_task_dirs = [
            self.root / "tasks" / "queue",
            self.root / "tasks" / "in_progress",
            self.root / "tasks" / "blocked",
            self.root / "tasks" / "done",
            self.root / "tasks" / "failed",
        ]
        # Collect all known develop task IDs across every status directory
        develop_ids: set = set()
        for d in all_task_dirs:
            if not d.exists():
                continue
            for f in d.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
                    if data.get("task_type") == "develop":
                        develop_ids.add(data.get("task_id", ""))
                except Exception:
                    pass

        orphan_count = 0
        for d in (self.root / "tasks" / "queue", self.root / "tasks" / "blocked"):
            if not d.exists():
                continue
            for f in d.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
                    if data.get("task_type") != "validate":
                        continue
                    age_s = now - f.stat().st_mtime
                    if age_s < _ORPHAN_AGE_S:
                        continue
                    parent_id = (data.get("payload") or {}).get("develop_task_id", "")
                    if parent_id and parent_id not in develop_ids:
                        orphan_count += 1
                except Exception:
                    pass

        if orphan_count:
            self._emit(
                AlertType.VALIDATE_TASKS_ORPHANED,
                Severity.MEDIUM,
                f"{orphan_count} validate task(s) with no parent develop task (>10min old)",
            )
        else:
            self._resolve_if_present(AlertType.VALIDATE_TASKS_ORPHANED)


    def _check_supervisor_heartbeat(self) -> None:
        """Emit STALE_HEARTBEAT / NO_HEARTBEAT based on supervisor_health.json."""
        health_path = self.root / "state" / "supervisor_health.json"
        if not health_path.exists():
            self._emit(
                AlertType.NO_HEARTBEAT,
                Severity.HIGH,
                "state/supervisor_health.json not found — supervisor may not be running",
            )
            return
        self._resolve_if_present(AlertType.NO_HEARTBEAT)
        try:
            data = json.loads(health_path.read_text(encoding="utf-8", errors="replace"))
            last_hb = data.get("last_heartbeat", "")
            if not last_hb:
                return
            # Parse ISO 8601 timestamp
            from datetime import datetime, timezone
            try:
                ts = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
                age_s = (datetime.now(timezone.utc) - ts).total_seconds()
            except (ValueError, TypeError):
                return
            if age_s > _HEARTBEAT_STALE_S:
                self._emit(
                    AlertType.STALE_HEARTBEAT,
                    Severity.HIGH,
                    f"Supervisor heartbeat is {int(age_s / 60)}min old (threshold {int(_HEARTBEAT_STALE_S/60)}min)",
                )
            else:
                self._resolve_if_present(AlertType.STALE_HEARTBEAT)
        except Exception:
            pass

    def _check_queue_depth(self) -> None:
        """Emit HIGH_QUEUE_DEPTH when the task queue has too many files."""
        queue_dir = self.root / "tasks" / "queue"
        if not queue_dir.exists():
            self._resolve_if_present(AlertType.HIGH_QUEUE_DEPTH)
            return
        count = sum(1 for f in queue_dir.glob("*.json") if f.stat().st_size > 0)
        if count >= _QUEUE_DEPTH_ALERT:
            self._emit(
                AlertType.HIGH_QUEUE_DEPTH,
                Severity.HIGH,
                f"Task queue depth is {count} (threshold {_QUEUE_DEPTH_ALERT})",
            )
        else:
            self._resolve_if_present(AlertType.HIGH_QUEUE_DEPTH)

    def _check_stuck_in_progress(self) -> None:
        """Emit STUCK_TASK when an in-progress task file is older than _STUCK_TASK_S."""
        prog_dir = self.root / "tasks" / "in_progress"
        if not prog_dir.exists():
            self._resolve_if_present(AlertType.STUCK_TASK)
            return
        now = time.time()
        stuck = []
        for f in prog_dir.glob("*.json"):
            try:
                age_s = now - f.stat().st_mtime
                if age_s > _STUCK_TASK_S and f.stat().st_size > 0:
                    stuck.append((f.name, int(age_s / 60)))
            except OSError:
                pass
        if stuck:
            names = ", ".join(f"{n}({m}min)" for n, m in stuck[:3])
            self._emit(
                AlertType.STUCK_TASK,
                Severity.HIGH,
                f"{len(stuck)} stuck in-progress task(s): {names}",
            )
        else:
            self._resolve_if_present(AlertType.STUCK_TASK)

    def _check_journal_gap(self) -> None:
        """Emit JOURNAL_GAP when no new journal entries appear for _JOURNAL_GAP_S seconds."""
        if not self._journal_path.exists():
            return
        try:
            age_s = time.time() - self._journal_path.stat().st_mtime
            if age_s > _JOURNAL_GAP_S:
                self._emit(
                    AlertType.JOURNAL_GAP,
                    Severity.MEDIUM,
                    f"No journal activity for {int(age_s / 60)}min (threshold {int(_JOURNAL_GAP_S/60)}min)",
                )
            else:
                self._resolve_if_present(AlertType.JOURNAL_GAP)
        except OSError:
            pass

    # ── Alert primitives ───────────────────────────────────────────────────────

    def _emit(
        self,
        alert_type: AlertType,
        severity: Severity,
        evidence: str,
        *,
        auto_fixed: bool = False,
    ) -> None:
        key = alert_type.value
        now = time.time()
        with self._lock:
            existing = self._alerts.get(key)
            if existing is None or existing.resolved:
                self._alerts[key] = WatchdogAlert(
                    alert_id=key,
                    alert_type=key,
                    severity=severity.value,
                    first_seen=now,
                    last_seen=now,
                    count=1,
                    evidence=evidence,
                    auto_fixed=auto_fixed,
                    resolved=False,
                )
            else:
                existing.count += 1
                existing.last_seen = now
                existing.evidence = evidence
                existing.severity = severity.value
                if auto_fixed:
                    existing.auto_fixed = True

    def _resolve_if_present(self, alert_type: AlertType) -> None:
        key = alert_type.value
        with self._lock:
            if key in self._alerts:
                self._alerts[key].resolved = True

    # ── Persistence ────────────────────────────────────────────────────────────

    def _save_alerts(self) -> None:
        alerts_file = self.root / self.ALERTS_FILE
        tmp_file = alerts_file.with_suffix(".tmp")
        try:
            alerts_file.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {k: v.to_dict() for k, v in self._alerts.items()}
            tmp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_file.replace(alerts_file)
        except OSError:
            pass

    def _load_alerts(self) -> None:
        alerts_file = self.root / self.ALERTS_FILE
        if not alerts_file.exists():
            return
        try:
            data = json.loads(alerts_file.read_text(encoding="utf-8"))
            with self._lock:
                for k, v in data.items():
                    self._alerts[k] = WatchdogAlert.from_dict(v)
        except Exception:
            pass

    # ── Overseer escalation ────────────────────────────────────────────────────

    def _maybe_trigger_overseer(self) -> None:
        if self._enqueue is None:
            return
        now = time.time()
        if now - self._last_overseer_trigger < _OVERSEER_COOLDOWN_S:
            return
        with self._lock:
            active = list(self._alerts.values())
        high_plus = [
            a for a in active
            if not a.resolved
            and not a.auto_fixed
            and a.severity in (Severity.HIGH.value, Severity.CRITICAL.value)
        ]
        if not high_plus:
            return
        queue_dir = self.root / "tasks" / "queue"
        if queue_dir.exists():
            for f in queue_dir.glob("*.json"):
                try:
                    if json.loads(f.read_text(encoding="utf-8")).get("task_type") == "overseer":
                        return
                except Exception:
                    pass
        self._last_overseer_trigger = now
        summary = "; ".join(f"{a.severity} {a.alert_type}" for a in high_plus[:3])
        # Include task_id + status: enqueue_task validates the full Task schema
        # (which requires both), so a spec missing them is rejected and the
        # escalation is silently dropped — defeating the watchdog's recovery arm.
        self._enqueue({
            "task_id": str(uuid.uuid4()),
            "task_type": "overseer",
            "title": f"Watchdog escalation: {summary}",
            "priority": 90,
            "status": "queued",
        })


class WatchdogThread(threading.Thread):
    """Daemon thread that drives a Watchdog instance at its configured tick interval.

    Usage::
        wt = WatchdogThread(watchdog_instance)
        wt.start()
        ...
        wt.stop()
        wt.join(timeout=5.0)
    """

    def __init__(self, watchdog: Watchdog) -> None:
        super().__init__(name="watchdog", daemon=True)
        self._watchdog = watchdog
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._watchdog.tick()
            except Exception:
                pass
            self._stop_event.wait(timeout=self._watchdog.TICK_INTERVAL_S)

    def stop(self) -> None:
        """Signal the thread to exit on its next iteration."""
        self._stop_event.set()
