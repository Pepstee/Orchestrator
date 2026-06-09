"""
tail_metrics.py — One-shot operational metrics from events.log.

Parses the orchestrator's structured event log and produces a snapshot of
throughput, per-agent timing, and failure patterns over a configurable window.
Reads rotated logs (events.log.1, .2, ...) automatically when the window
extends back beyond the current log.

Zero-token, deterministic: no LLM calls, just JSON parsing and arithmetic.

Examples
--------

Default window (last hour, plain text):
    python3 tail_metrics.py

Last 24 hours:
    python3 tail_metrics.py --hours 24

Since a specific ISO datetime:
    python3 tail_metrics.py --since 2026-05-08T00:00:00+00:00

Machine-readable JSON:
    python3 tail_metrics.py --hours 24 --json

What the output covers
----------------------

- Total event count and a breakdown by event type
- Tasks completed, failed, blocked, requeued
- Throughput: completed-per-hour over the window
- Failure rate: failed / (completed + failed)
- Per-agent mean duration and sample count
- Top failure reasons by frequency
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import public_api as o  # noqa: E402  (Stage 2.5: consume the supported facade, not orchestrator internals)
from agents.cost_tracker import _call_cost_from_extra  # noqa: E402


# ── Event parsing helpers ──────────────────────────────────────────────────────

def _parse_event_line(line: str) -> Optional[Dict[str, Any]]:
    s = line.strip()
    if not s:
        return None
    try:
        ev = json.loads(s)
        return ev if isinstance(ev, dict) else None
    except json.JSONDecodeError:
        return None


def _event_timestamp(event: Dict[str, Any]) -> Optional[datetime]:
    ts = event.get("ts")
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _find_rotated_logs(log_path: Path, max_index: int = 10) -> List[Path]:
    """Return rotated events.log.N files that currently exist, oldest first.

    The orchestrator rotates .1 -> .2 -> .3 with .1 being the most recent
    archive, so iterating from .max_index down to .1 gives us oldest-to-newest.
    """
    paths: List[Path] = []
    for i in range(max_index, 0, -1):
        p = log_path.parent / f"{log_path.name}.{i}"
        if p.exists():
            paths.append(p)
    return paths


def _events_in_window(log_paths: List[Path], since: datetime) -> Iterable[Dict[str, Any]]:
    """Yield events from the given log files whose ts >= since.

    Caller supplies log files in the order they should be read (typically
    oldest rotated -> current).  Lines that don't parse, lines without a
    timestamp, and events before the window are silently skipped.
    """
    for path in log_paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    event = _parse_event_line(raw)
                    if event is None:
                        continue
                    ts = _event_timestamp(event)
                    if ts is None or ts < since:
                        continue
                    yield event
        except OSError:
            continue


# ── Aggregation ────────────────────────────────────────────────────────────────

@dataclass
class Aggregate:
    """Rolled-up counts and timings across a time window."""
    window_start: datetime
    total_events: int = 0
    by_type: Counter = field(default_factory=Counter)
    enqueued: int = 0
    claimed: int = 0
    completed: int = 0
    failed: int = 0
    blocked: int = 0
    requeued: int = 0

    # Per-task correlation state — these survive aggregation for tests/debug
    task_starts: Dict[str, datetime] = field(default_factory=dict)
    task_ends: Dict[str, datetime] = field(default_factory=dict)
    task_agents: Dict[str, str] = field(default_factory=dict)

    # Computed
    agent_durations: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))
    failure_reasons: Counter = field(default_factory=Counter)

    # Cost tracking — populated from cost_usd / token fields in agent_finished events
    total_cost_usd: float = 0.0
    cost_by_agent: Dict[str, float] = field(default_factory=dict)

    # Last N events, mostly for debug output
    recent: List[Dict[str, Any]] = field(default_factory=list)


def _agent_name_from_command(cmd: Any) -> Optional[str]:
    """Extract the agent name from an agent_started 'command' list.

    The command is shaped like ["python3", "agents/explorer.py", "<input.json>"].
    We take the filename stem of arg index 1.
    """
    if not isinstance(cmd, list) or len(cmd) < 2:
        return None
    try:
        return Path(cmd[1]).stem
    except Exception:
        return None


def aggregate_events(
    events: Iterable[Dict[str, Any]],
    window_start: datetime,
    recent_limit: int = 30,
) -> Aggregate:
    agg = Aggregate(window_start=window_start)

    for event in events:
        agg.total_events += 1
        et = event.get("event_type", "")
        agg.by_type[et] += 1

        extra = event.get("extra") or {}
        task_id = extra.get("task_id") if isinstance(extra, dict) else None
        ts = _event_timestamp(event)

        agg.recent.append(event)
        if len(agg.recent) > recent_limit:
            # Keep only the tail
            agg.recent = agg.recent[-recent_limit:]

        if et == "task_enqueued":
            agg.enqueued += 1
        elif et == "task_claimed":
            agg.claimed += 1
            if task_id and ts and task_id not in agg.task_starts:
                agg.task_starts[task_id] = ts
        elif et == "agent_started":
            if task_id and ts:
                # agent_started is the most accurate "work begins" marker
                agg.task_starts[task_id] = ts
            if task_id and isinstance(extra, dict):
                name = _agent_name_from_command(extra.get("command"))
                if name:
                    agg.task_agents[task_id] = name
        elif et == "agent_finished":
            if task_id and ts:
                agg.task_ends[task_id] = ts
            if isinstance(extra, dict):
                agent = extra.get("agent")
                if task_id and isinstance(agent, str):
                    agg.task_agents[task_id] = agent
                # Accumulate cost data (not gated on task_id — cost is trackable
                # even for events that lack a task_id in their extra dict)
                call_cost = _call_cost_from_extra(extra)
                if call_cost is not None:
                    agg.total_cost_usd += call_cost
                    if isinstance(agent, str):
                        agg.cost_by_agent[agent] = (
                            agg.cost_by_agent.get(agent, 0.0) + call_cost
                        )
        elif et == "task_completed":
            agg.completed += 1
            if task_id and ts and task_id not in agg.task_ends:
                agg.task_ends[task_id] = ts
        elif et == "task_failed":
            agg.failed += 1
            reason = event.get("message", "(no message)")
            if isinstance(reason, str):
                agg.failure_reasons[reason] += 1
        elif et == "task_blocked":
            agg.blocked += 1
        elif et == "task_requeued":
            agg.requeued += 1

    # Compute per-agent durations from correlated start/end events
    for task_id, agent in agg.task_agents.items():
        start = agg.task_starts.get(task_id)
        end = agg.task_ends.get(task_id)
        if start is None or end is None:
            continue
        duration = (end - start).total_seconds()
        if duration >= 0:
            agg.agent_durations[agent].append(duration)

    return agg


# ── Output formatting ──────────────────────────────────────────────────────────

def format_human(agg: Aggregate, now: Optional[datetime] = None) -> str:
    if now is None:
        now = datetime.now(timezone.utc)
    window_hours = max((now - agg.window_start).total_seconds() / 3600.0, 0.0)

    lines: List[str] = []
    lines.append(f"Window: from {agg.window_start.isoformat()}  ({window_hours:.2f}h)")
    lines.append("")
    lines.append("Throughput")
    lines.append(f"  total events     {agg.total_events}")
    lines.append(f"  enqueued         {agg.enqueued}")
    lines.append(f"  completed        {agg.completed}")
    lines.append(f"  failed           {agg.failed}")
    lines.append(f"  blocked          {agg.blocked}")
    lines.append(f"  requeued         {agg.requeued}")
    if window_hours > 0:
        lines.append(f"  completed/hour   {agg.completed / window_hours:.2f}")
    total_terminal = agg.completed + agg.failed
    if total_terminal > 0:
        lines.append(f"  failure rate     {100 * agg.failed / total_terminal:.1f}%")

    if agg.total_cost_usd > 0:
        lines.append("")
        lines.append("Cost (USD)")
        lines.append(f"  total            ${agg.total_cost_usd:.4f}")
        if agg.cost_by_agent:
            width = max(len(a) for a in agg.cost_by_agent)
            for agent in sorted(agg.cost_by_agent):
                lines.append(f"  {agent:<{width}}  ${agg.cost_by_agent[agent]:.4f}")

    if agg.agent_durations:
        lines.append("")
        lines.append("Per-agent timing (mean seconds, sample size)")
        width = max(len(a) for a in agg.agent_durations)
        for agent in sorted(agg.agent_durations):
            durs = agg.agent_durations[agent]
            mean = statistics.mean(durs)
            n = len(durs)
            lines.append(f"  {agent:<{width}}  {mean:>8.1f}s   n={n}")

    if agg.failure_reasons:
        lines.append("")
        lines.append("Top failure reasons")
        for reason, count in agg.failure_reasons.most_common(5):
            short = reason if len(reason) <= 90 else reason[:87] + "..."
            lines.append(f"  {count:>3}  {short}")

    return "\n".join(lines)


def to_json_dict(agg: Aggregate) -> Dict[str, Any]:
    return {
        "window_start": agg.window_start.isoformat(),
        "total_events": agg.total_events,
        "by_type": dict(agg.by_type),
        "enqueued": agg.enqueued,
        "completed": agg.completed,
        "failed": agg.failed,
        "blocked": agg.blocked,
        "requeued": agg.requeued,
        "total_cost_usd": round(agg.total_cost_usd, 6),
        "cost_by_agent": {k: round(v, 6) for k, v in agg.cost_by_agent.items()},
        "agent_durations": {
            agent: {
                "mean_seconds": statistics.mean(durs),
                "count": len(durs),
                "max_seconds": max(durs),
                "min_seconds": min(durs),
            }
            for agent, durs in agg.agent_durations.items()
        },
        "top_failure_reasons": [
            {"reason": r, "count": c} for r, c in agg.failure_reasons.most_common(10)
        ],
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tail_metrics",
        description="One-shot operational metrics from the orchestrator events log.",
    )
    p.add_argument(
        "--hours",
        type=float,
        default=1.0,
        help="Window in hours, ending now (default 1).",
    )
    p.add_argument(
        "--since",
        help="ISO datetime; overrides --hours.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human-readable text.",
    )
    return p


def _resolve_window(args: argparse.Namespace) -> datetime:
    if args.since:
        try:
            dt = datetime.fromisoformat(args.since)
        except ValueError as exc:
            raise SystemExit(f"--since: {exc}")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return datetime.now(timezone.utc) - timedelta(hours=args.hours)


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    config = o.Config.load()
    if config.tasks_root:
        o._apply_tasks_root(config.tasks_root)

    window_start = _resolve_window(args)
    log_paths = _find_rotated_logs(o.EVENTS_LOG) + [o.EVENTS_LOG]
    events = _events_in_window(log_paths, window_start)
    agg = aggregate_events(events, window_start)

    if args.json:
        print(json.dumps(to_json_dict(agg), indent=2))
    else:
        print(format_human(agg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
