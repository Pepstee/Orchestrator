"""
velocity_monitor.py — Orchestrator health and stall-detection subsystem.

Runs as a periodic hook inside the orchestrator main loop (NOT a thread).
Collects 6 filesystem signals every tick_interval_s seconds, drives a
5-state health machine, diagnoses stall root-causes, and dispatches
targeted interventions via enqueue_fn.

State is persisted atomically to state/velocity_monitor.json so restarts
recover cleanly.  A heartbeat file (state/orchestrator_heartbeat) is
written each tick so an external watchdog can detect a completely-frozen
orchestrator process.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from io_utils import write_json_atomic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class HealthState(str, Enum):
    HEALTHY     = "HEALTHY"
    WARNING     = "WARNING"
    STALLED     = "STALLED"
    INTERVENING = "INTERVENING"
    ESCALATED   = "ESCALATED"


class StallDiagnosis(str, Enum):
    NONE          = "NONE"
    PAUSED        = "PAUSED"
    EMPTY_QUEUE   = "EMPTY_QUEUE"
    GHOST_TASK    = "GHOST_TASK"
    IDLE_QUEUE    = "IDLE_QUEUE"
    BUSY_FAILING  = "BUSY_FAILING"
    PLANNING_LOOP = "PLANNING_LOOP"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class VelocityMonitorConfig:
    enabled: bool = True

    # How often tick() actually does work (seconds between real ticks).
    tick_interval_s: float = 30.0

    # Rolling window for throughput and fail-rate calculations (seconds).
    warning_window_s: float = 600.0
    stall_window_s:   float = 600.0

    # Minimum dwell in WARNING before escalating to STALLED (seconds).
    warning_dwell_s: float = 120.0

    # Minimum dwell in STALLED before triggering an intervention (seconds).
    stall_dwell_s: float = 60.0

    # Recovery: how many new done-tasks confirm a heal from STALLED/INTERVENING.
    recovery_done_delta: int = 2

    # Intervention rate limiting.
    intervention_cooldown_s: float = 900.0   # 15 min between same-type interventions
    max_interventions_per_type: int = 3       # then → ESCALATED

    # Stall-diagnosis thresholds.
    planning_loop_ratio:   float = 0.70   # plan tasks / total queued > this → PLANNING_LOOP
    busy_failing_rate:     float = 0.80   # fail / (done + fail) in window > this → BUSY_FAILING
    ghost_task_multiplier: float = 2.0    # in_progress age > multiplier * agent_timeout_s

    # How long an in-progress task may run before being considered a ghost (seconds).
    agent_timeout_s: float = 600.0

    # Grace period after process start before monitoring begins (seconds).
    bootstrap_s: float = 300.0


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    """Snapshot of all filesystem signals at one instant."""
    ts:               float = 0.0
    queued:           int   = 0
    in_progress:      int   = 0
    done_total:       int   = 0   # cumulative count in tasks/done/
    failed_total:     int   = 0   # cumulative count in tasks/failed/
    blocked:          int   = 0
    plan_queued:      int   = 0   # subset of queued with task_type == "plan"
    oldest_ip_age_s:  float = 0.0 # age (s) of oldest in-progress task


@dataclass
class _WindowPoint:
    """A done/fail snapshot stored in the rolling window."""
    ts:    float
    done:  int
    failed: int


@dataclass
class _State:
    """Mutable state persisted to disk."""
    health:              str   = HealthState.HEALTHY.value
    diagnosis:           str   = StallDiagnosis.NONE.value
    start_ts:            float = field(default_factory=time.time)
    last_tick_ts:        float = 0.0

    # Timestamps of last health transitions.
    entered_warning_ts:      float = 0.0
    entered_stalled_ts:      float = 0.0
    entered_intervening_ts:  float = 0.0
    entered_escalated_ts:    float = 0.0

    # Baseline done count stored when entering STALLED/INTERVENING for
    # recovery detection.
    baseline_done_total: int = 0

    # Rolling window: list of {ts, done, failed} dicts (serialised as list).
    window: List[Dict] = field(default_factory=list)

    # Per-diagnosis intervention counts and last-fired timestamps.
    intervention_counts:    Dict[str, int]   = field(default_factory=dict)
    intervention_last_ts:   Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "_State":
        s = cls()
        for k, v in d.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s


# ---------------------------------------------------------------------------
# VelocityMonitor
# ---------------------------------------------------------------------------

class VelocityMonitor:
    """
    Orchestrator health monitor.  Call tick() from the main loop; it
    throttles itself to at most one real tick per tick_interval_s seconds.

    Parameters
    ----------
    root        : Path to the repository root (tasks/ subdirs live here).
    config      : VelocityMonitorConfig instance.
    enqueue_fn  : Callable[[dict], None] — enqueues a task dict; used for
                  intervention tasks.
    log_fn      : Callable[[str, str, **kw], None] — log_event compatible
                  signature (event_type, message, **kwargs).
    is_paused_fn: Optional callable returning bool; True means orchestrator
                  is intentionally paused (suppresses stall interventions).
    """

    STATE_FILE      = Path("state/velocity_monitor.json")
    HEARTBEAT_FILE  = Path("state/orchestrator_heartbeat")
    ATTENTION_FILE  = Path("NEEDS_ATTENTION")

    def __init__(
        self,
        root: Path,
        config: VelocityMonitorConfig,
        enqueue_fn:   Callable[[dict], None],
        log_fn:       Callable[..., None],
        is_paused_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._root        = root
        self._cfg         = config
        self._enqueue     = enqueue_fn
        self._log         = log_fn
        self._is_paused   = is_paused_fn or (lambda: False)
        self._state       = self._load_state()
        self._process_start = time.time()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tick(self) -> None:
        """Called frequently from the main loop; self-throttles."""
        if not self._cfg.enabled:
            return

        now = time.time()

        # Bootstrap grace period — don't act on a cold start.
        if now - self._process_start < self._cfg.bootstrap_s:
            self._write_heartbeat(now)
            return

        # Throttle: only do real work once per tick_interval_s.
        if now - self._state.last_tick_ts < self._cfg.tick_interval_s:
            return

        self._state.last_tick_ts = now
        obs = self._collect(now)
        self._update_window(obs)
        self._run_state_machine(obs, now)
        self._save_state()
        self._write_heartbeat(now)

    def current_health(self) -> HealthState:
        return HealthState(self._state.health)

    def current_diagnosis(self) -> StallDiagnosis:
        return StallDiagnosis(self._state.diagnosis)

    def status_dict(self) -> dict:
        """Return a snapshot dict suitable for the dashboard API."""
        return {
            "health":    self._state.health,
            "diagnosis": self._state.diagnosis,
            "last_tick": self._state.last_tick_ts,
        }

    # ------------------------------------------------------------------
    # Signal collection
    # ------------------------------------------------------------------

    def _collect(self, now: float) -> Observation:
        obs = Observation(ts=now)

        tasks_root = self._root / "tasks"
        obs.queued      = self._count_files(tasks_root / "queue")
        obs.in_progress = self._count_files(tasks_root / "in_progress")
        obs.done_total  = self._count_files(tasks_root / "done")
        obs.failed_total = self._count_files(tasks_root / "failed")
        obs.blocked     = self._count_files(tasks_root / "blocked")

        # plan_queued: tasks in queue whose task_type == "plan"
        obs.plan_queued = self._count_plan_tasks(tasks_root / "queue")

        # oldest in-progress task age
        obs.oldest_ip_age_s = self._oldest_age(tasks_root / "in_progress", now)

        return obs

    @staticmethod
    def _count_files(directory: Path) -> int:
        """Count non-tombstone (non-zero-byte) files in directory."""
        try:
            return sum(
                1 for p in directory.iterdir()
                if p.is_file() and p.stat().st_size > 0
            )
        except FileNotFoundError:
            return 0
        except OSError:
            return 0

    @staticmethod
    def _count_plan_tasks(directory: Path) -> int:
        """Count queued tasks whose task_type is 'plan'."""
        count = 0
        try:
            for p in directory.iterdir():
                if not p.is_file() or p.stat().st_size == 0:
                    continue
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if data.get("task_type") == "plan":
                        count += 1
                except (json.JSONDecodeError, OSError):
                    pass
        except (FileNotFoundError, OSError):
            pass
        return count

    @staticmethod
    def _oldest_age(directory: Path, now: float) -> float:
        """Return age in seconds of the oldest file in directory, or 0."""
        oldest_mtime = None
        try:
            for p in directory.iterdir():
                if not p.is_file() or p.stat().st_size == 0:
                    continue
                try:
                    mt = p.stat().st_mtime
                    if oldest_mtime is None or mt < oldest_mtime:
                        oldest_mtime = mt
                except OSError:
                    pass
        except (FileNotFoundError, OSError):
            pass
        if oldest_mtime is None:
            return 0.0
        return max(0.0, now - oldest_mtime)

    # ------------------------------------------------------------------
    # Rolling window management
    # ------------------------------------------------------------------

    def _update_window(self, obs: Observation) -> None:
        cutoff = obs.ts - max(
            self._cfg.warning_window_s,
            self._cfg.stall_window_s,
        )
        self._state.window = [
            w for w in self._state.window if w["ts"] >= cutoff
        ]
        self._state.window.append({
            "ts":     obs.ts,
            "done":   obs.done_total,
            "failed": obs.failed_total,
        })

    def _window_deltas(self, window_s: float, now: float) -> Tuple[int, int]:
        """Return (done_delta, failed_delta) over the last window_s seconds."""
        cutoff = now - window_s
        points = [w for w in self._state.window if w["ts"] >= cutoff]
        if len(points) < 2:
            return 0, 0
        oldest = points[0]
        newest = points[-1]
        return (
            max(0, newest["done"]   - oldest["done"]),
            max(0, newest["failed"] - oldest["failed"]),
        )

    # ------------------------------------------------------------------
    # Diagnosis
    # ------------------------------------------------------------------

    def _diagnose(self, obs: Observation, now: float) -> StallDiagnosis:
        """Identify WHY the orchestrator has stalled."""
        cfg = self._cfg

        if self._is_paused():
            return StallDiagnosis.PAUSED

        if obs.in_progress > 0 and obs.oldest_ip_age_s > cfg.ghost_task_multiplier * cfg.agent_timeout_s:
            return StallDiagnosis.GHOST_TASK

        done_w, fail_w = self._window_deltas(cfg.stall_window_s, now)
        total_w = done_w + fail_w
        if total_w > 0 and (fail_w / total_w) >= cfg.busy_failing_rate:
            return StallDiagnosis.BUSY_FAILING

        if obs.queued == 0 and obs.in_progress == 0:
            return StallDiagnosis.EMPTY_QUEUE

        if obs.queued > 0 and done_w == 0 and fail_w == 0:
            if obs.queued > 0 and obs.plan_queued > 0:
                if obs.plan_queued / obs.queued >= cfg.planning_loop_ratio:
                    return StallDiagnosis.PLANNING_LOOP
            return StallDiagnosis.IDLE_QUEUE

        return StallDiagnosis.NONE

    # ------------------------------------------------------------------
    # Health state machine
    # ------------------------------------------------------------------

    def _run_state_machine(self, obs: Observation, now: float) -> None:
        cfg    = self._cfg
        state  = self._state
        health = HealthState(state.health)

        done_w, fail_w = self._window_deltas(cfg.warning_window_s, now)
        total_w = done_w + fail_w

        # ── Recovery check (STALLED / INTERVENING only) ──────────────────
        # WARNING heals when _is_stalling returns False. The done-delta counter
        # only applies once a meaningful baseline has been stored (on STALLED entry).
        if health in (HealthState.STALLED, HealthState.INTERVENING):
            done_since = obs.done_total - state.baseline_done_total
            if done_since >= cfg.recovery_done_delta:
                self._transition(HealthState.HEALTHY, StallDiagnosis.NONE, obs, now)
                logger.info("VelocityMonitor: recovered → HEALTHY (+%d done tasks)", done_since)
                return

        # ── HEALTHY ─────────────────────────────────────────────────────
        if health == HealthState.HEALTHY:
            if self._is_stalling(obs, done_w, fail_w, total_w, now):
                self._transition(HealthState.WARNING, StallDiagnosis.NONE, obs, now)
                logger.warning("VelocityMonitor: HEALTHY → WARNING")
            return

        # ── WARNING ─────────────────────────────────────────────────────
        if health == HealthState.WARNING:
            if not self._is_stalling(obs, done_w, fail_w, total_w, now):
                self._transition(HealthState.HEALTHY, StallDiagnosis.NONE, obs, now)
                logger.info("VelocityMonitor: WARNING → HEALTHY (resolved)")
                return
            dwell = now - state.entered_warning_ts
            if dwell >= cfg.warning_dwell_s:
                diag = self._diagnose(obs, now)
                self._transition(HealthState.STALLED, diag, obs, now)
                logger.warning("VelocityMonitor: WARNING → STALLED (%s) after %.0fs", diag.value, dwell)
            return

        # ── STALLED ─────────────────────────────────────────────────────
        if health == HealthState.STALLED:
            dwell = now - state.entered_stalled_ts
            if dwell >= cfg.stall_dwell_s:
                diag = self._diagnose(obs, now)
                fired = self._maybe_intervene(diag, obs, now)
                if fired:
                    self._transition(HealthState.INTERVENING, diag, obs, now)
                    logger.warning("VelocityMonitor: STALLED → INTERVENING (%s)", diag.value)
                else:
                    # Rate-limited or max exceeded → escalate
                    self._transition(HealthState.ESCALATED, diag, obs, now)
                    logger.error("VelocityMonitor: STALLED → ESCALATED (%s) — intervention suppressed", diag.value)
                    self._write_attention_file(diag)
            return

        # ── INTERVENING ─────────────────────────────────────────────────
        if health == HealthState.INTERVENING:
            # Wait for recovery; if still stalling after another stall_window,
            # re-diagnose and try another intervention or escalate.
            dwell = now - state.entered_intervening_ts
            if dwell >= cfg.stall_window_s:
                diag = self._diagnose(obs, now)
                fired = self._maybe_intervene(diag, obs, now)
                if fired:
                    # Reset dwell so we wait again.
                    state.entered_intervening_ts = now
                    state.diagnosis = diag.value
                    logger.warning("VelocityMonitor: still INTERVENING, re-fired (%s)", diag.value)
                else:
                    self._transition(HealthState.ESCALATED, diag, obs, now)
                    logger.error("VelocityMonitor: INTERVENING → ESCALATED (%s)", diag.value)
                    self._write_attention_file(diag)
            return

        # ── ESCALATED ───────────────────────────────────────────────────
        # Sticky until human acknowledges (deletes NEEDS_ATTENTION) or
        # recovery_done_delta tasks complete (handled at top of function).

    def _is_stalling(
        self, obs: Observation,
        done_w: int, fail_w: int, total_w: int,
        now: float,
    ) -> bool:
        """True when any stall signal is active."""
        cfg = self._cfg
        # High fail rate — agents are running but failing
        if total_w > 0 and (fail_w / total_w) >= cfg.busy_failing_rate:
            return True
        # Ghost task: in_progress but silent for far too long
        if obs.in_progress > 0 and obs.oldest_ip_age_s > cfg.ghost_task_multiplier * cfg.agent_timeout_s:
            return True
        # Nothing completing AND nothing in progress — queue growing with no workers
        if done_w == 0 and obs.queued > 0 and obs.in_progress == 0:
            return True
        return False

    def _transition(
        self,
        new_health: HealthState,
        diag: StallDiagnosis,
        obs: Observation,
        now: float,
    ) -> None:
        state = self._state
        old   = state.health
        state.health    = new_health.value
        state.diagnosis = diag.value

        ts_map = {
            HealthState.WARNING:     "entered_warning_ts",
            HealthState.STALLED:     "entered_stalled_ts",
            HealthState.INTERVENING: "entered_intervening_ts",
            HealthState.ESCALATED:   "entered_escalated_ts",
        }
        if new_health in ts_map:
            setattr(state, ts_map[new_health], now)

        if new_health in (HealthState.STALLED, HealthState.INTERVENING):
            state.baseline_done_total = obs.done_total

        self._log(
            "velocity_health_transition",
            f"{old} → {new_health.value}",
            diagnosis=diag.value,
            queued=obs.queued,
            in_progress=obs.in_progress,
        )

    # ------------------------------------------------------------------
    # Interventions
    # ------------------------------------------------------------------

    _INTERVENTION_MAP: Dict[str, str] = {
        StallDiagnosis.EMPTY_QUEUE.value:   "Request new tasks from idle-optimiser",
        StallDiagnosis.GHOST_TASK.value:    "Reclaim stale in-progress tasks",
        StallDiagnosis.IDLE_QUEUE.value:    "Nudge task_manager to unblock queue",
        StallDiagnosis.BUSY_FAILING.value:  "Audit recent failures for root cause",
        StallDiagnosis.PLANNING_LOOP.value: "Break planning loop — inject concrete implement task",
    }

    def _maybe_intervene(
        self, diag: StallDiagnosis, obs: Observation, now: float
    ) -> bool:
        """
        Fire an intervention task for *diag* if rate limits allow.
        Returns True if a task was enqueued, False if suppressed.
        """
        if diag in (StallDiagnosis.NONE, StallDiagnosis.PAUSED):
            return False

        key = diag.value
        cfg = self._cfg

        count    = self._state.intervention_counts.get(key, 0)
        last_ts  = self._state.intervention_last_ts.get(key, 0.0)

        if count >= cfg.max_interventions_per_type:
            logger.warning("VelocityMonitor: intervention cap reached for %s", key)
            return False

        if now - last_ts < cfg.intervention_cooldown_s:
            logger.debug("VelocityMonitor: intervention cooldown active for %s", key)
            return False

        task = self._build_intervention_task(diag, obs, now)
        try:
            self._enqueue(task)
        except Exception as exc:  # pragma: no cover
            logger.error("VelocityMonitor: enqueue failed: %s", exc)
            return False

        self._state.intervention_counts[key] = count + 1
        self._state.intervention_last_ts[key] = now

        self._log(
            "velocity_intervention",
            f"Intervention enqueued: {diag.value}",
            task_id=task.get("task_id", "?"),
            count=count + 1,
        )
        logger.warning(
            "VelocityMonitor: intervention #%d fired (%s) task_id=%s",
            count + 1, key, task.get("task_id", "?"),
        )
        return True

    def _build_intervention_task(
        self, diag: StallDiagnosis, obs: Observation, now: float
    ) -> dict:
        import uuid

        base = {
            "task_id":   str(uuid.uuid4()),
            "status":    "queued",
            "priority":  10,
            "depends_on": [],
            "acceptance_criteria": [],
            "trigger":   "velocity_monitor",
        }

        if diag == StallDiagnosis.EMPTY_QUEUE:
            base.update({
                "task_type": "manage",
                "title":     "Velocity monitor: queue is empty — generate new tasks",
                "description": (
                    "The task queue has been empty for an extended period.  "
                    "Survey the current project state and enqueue the highest-value "
                    "next actions.  Prefer concrete implement or repair tasks."
                ),
            })

        elif diag == StallDiagnosis.GHOST_TASK:
            base.update({
                "task_type": "repair",
                "title":     "Velocity monitor: reclaim ghost in-progress tasks",
                "description": (
                    f"One or more tasks have been in-progress for >"
                    f"{self._cfg.ghost_task_multiplier * self._cfg.agent_timeout_s:.0f}s "
                    f"without completing.  Identify and move them back to queued or failed."
                ),
            })

        elif diag == StallDiagnosis.IDLE_QUEUE:
            base.update({
                "task_type": "manage",
                "title":     "Velocity monitor: queue has tasks but nothing is processing",
                "description": (
                    "Tasks are queued but none are being picked up.  "
                    "Check for dependency deadlocks, missing agent commands, "
                    "or blocked preconditions, and resolve them."
                ),
            })

        elif diag == StallDiagnosis.BUSY_FAILING:
            base.update({
                "task_type": "audit",
                "title":     "Velocity monitor: high failure rate — audit recent errors",
                "description": (
                    "The orchestrator is completing tasks but most are failing.  "
                    "Read the last 10 failed task files and the event log, identify "
                    "the root cause, and enqueue a repair task."
                ),
            })

        elif diag == StallDiagnosis.PLANNING_LOOP:
            base.update({
                "task_type": "implement",
                "title":     "Velocity monitor: break planning loop — execute something concrete",
                "description": (
                    "The queue is dominated by plan-type tasks that are not producing "
                    "output.  Pick the most mature plan already in the queue and "
                    "convert it into a concrete implement task right now."
                ),
            })

        return base

    # ------------------------------------------------------------------
    # Attention file
    # ------------------------------------------------------------------

    def _write_attention_file(self, diag: StallDiagnosis) -> None:
        path = self._root / self.ATTENTION_FILE
        try:
            path.write_text(
                f"ESCALATED: {diag.value}\n"
                f"The orchestrator has stalled and all automatic interventions "
                f"have been exhausted.\n"
                f"Please inspect the task queues and event log, then delete "
                f"this file to resume monitoring.\n",
                encoding="utf-8",
            )
            logger.error("VelocityMonitor: wrote %s", path)
        except OSError as exc:  # pragma: no cover
            logger.error("VelocityMonitor: could not write attention file: %s", exc)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def _write_heartbeat(self, now: float) -> None:
        path = self._root / self.HEARTBEAT_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(now), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _state_path(self) -> Path:
        return self._root / self.STATE_FILE

    def _load_state(self) -> _State:
        path = self._state_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return _State.from_dict(data)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return _State(start_ts=time.time())

    def _save_state(self) -> None:
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, self._state.as_dict())
