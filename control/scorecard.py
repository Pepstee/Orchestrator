"""control.scorecard — deterministic measurement of the work done (09 §7, port of v1 tail_metrics).

Everything is computed from the durable records alone — the event log, the budget log, and the
project git trees — no LLM, no estimates. Run it any time, daemon up or down:

    python3 -m control.scorecard                # everything
    python3 -m control.scorecard --since-hours 12

What it measures and why:
  runs/success ratio        — the burn-vs-progress headline (June ran at 6.8% and nobody saw)
  wall-clock per run        — on a Max subscription the CLI reports ~$0, so TIME-IN-AGENT is
                              the honest proxy for the scarce usage window
  waste counters            — requeues, BG-3 refusals, breaker trips: bounded-failure receipts
  per-project               — merges landed (real integrated work), gates, assurance, certs
  milestone                 — runs-per-certification once certifications exist (the efficiency
                              north star until token capture improves)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_events(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not Path(path).exists():
        return rows
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # tolerate a truncated final line
    return rows


def summarise(rows: list[dict], budget_rows: list[dict], *, since_ts: float = 0.0) -> dict:
    """Fold the logs into the scorecard numbers. Pure; unit-tested."""
    rows = [r for r in rows if r.get("ts", 0) >= since_ts]
    titles: dict[str, dict] = {}
    for r in rows:
        if r["kind"] == "task_created":
            t = r["data"]["task"]
            titles[t["task_id"]] = t
    claims: dict[str, float] = {}
    durations: list[float] = []
    ok = fail = 0
    by_type: Counter = Counter()
    fail_causes: Counter = Counter()
    per_project: dict[str, Counter] = defaultdict(Counter)
    requeues = refusals = 0
    gates: dict[str, dict] = {}
    assurance: dict[str, dict] = {}
    confirmations: list[str] = []
    for r in rows:
        k, d = r["kind"], r["data"]
        if k == "task_transition":
            if d["event"] == "claim":
                claims[d["task_id"]] = r["ts"]
            elif d["event"] == "requeue":
                requeues += 1
        elif k == "task_result":
            tid = d["task_id"]
            t = titles.get(tid, {})
            ttype = t.get("task_type", "?")
            project = t.get("project", "?")
            if tid in claims:
                durations.append(r["ts"] - claims.pop(tid))
            if d.get("ok"):
                ok += 1
                by_type[f"{ttype}:ok"] += 1
                per_project[project]["ok"] += 1
            else:
                fail += 1
                by_type[f"{ttype}:fail"] += 1
                per_project[project]["fail"] += 1
                fail_causes[(d.get("cause") or "?")[:48]] += 1
        elif k == "escalation" and "identical re-attempt refused" in str(d.get("reason", "")):
            refusals += 1
        elif k == "project_status":
            gates[d["project"]] = d.get("gates", {})
        elif k == "assurance_result":
            assurance[d["project"]] = d
        elif k == "project_confirmed":
            confirmations.append(d.get("project", "?"))
    breaker_trips = sum(1 for r in budget_rows
                        if r.get("kind") == "burn_pause" and r.get("ts", 0) >= since_ts)
    total = ok + fail
    return {
        "runs": total, "ok": ok, "fail": fail,
        "success_ratio": (ok / total) if total else None,
        "agent_hours": sum(durations) / 3600,
        "mean_run_minutes": (sum(durations) / len(durations) / 60) if durations else None,
        "by_type": dict(by_type),
        "top_fail_causes": fail_causes.most_common(5),
        "requeues": requeues, "bg3_refusals": refusals, "breaker_trips": breaker_trips,
        "per_project": {p: dict(c) for p, c in per_project.items()},
        "gates": gates, "assurance": {p: {"fully_hardened": a.get("fully_hardened"),
                                          "reason": a.get("reason", "")[:60]}
                                      for p, a in assurance.items()},
        "confirmations": confirmations,
        "runs_per_certification": (total / len(confirmations)) if confirmations else None,
    }


def git_merges(project_dir: Path) -> int:
    try:
        proc = subprocess.run(["git", "-C", str(project_dir), "rev-list", "--merges",
                               "--count", "HEAD"], capture_output=True, text=True, timeout=10)
        return int(proc.stdout.strip()) if proc.returncode == 0 else 0
    except Exception:
        return 0


def render(s: dict, merges: dict[str, int]) -> str:
    ratio = f"{s['success_ratio']:.0%}" if s["success_ratio"] is not None else "n/a"
    mean = f"{s['mean_run_minutes']:.1f} min" if s["mean_run_minutes"] is not None else "n/a"
    lines = [
        "== ORCHESTRATOR SCORECARD ==",
        f"runs: {s['runs']}  (ok {s['ok']} / fail {s['fail']})   success: {ratio}",
        f"time-in-agent: {s['agent_hours']:.1f} h   mean run: {mean}",
        f"waste, bounded: requeues {s['requeues']} · BG-3 refusals {s['bg3_refusals']}"
        f" · breaker trips {s['breaker_trips']}",
    ]
    if s["top_fail_causes"]:
        lines.append("top failure causes: " + "; ".join(f"{n}x {c}" for c, n in s["top_fail_causes"]))
    for p, counts in sorted(s["per_project"].items()):
        g = s["gates"].get(p, {})
        gate_str = "".join("+" if g.get(k) else "-" for k in ("tests", "acceptance", "judge", "authenticity")) if g else "...."
        a = s["assurance"].get(p, {})
        hard = "HARDENED" if a.get("fully_hardened") else (a.get("reason") or "")
        lines.append(f"  {p:22s} ok {counts.get('ok', 0):3d} / fail {counts.get('fail', 0):3d}"
                     f"   merges {merges.get(p, 0):3d}   gates[{gate_str}] {hard}")
    certs = s["confirmations"]
    lines.append(f"certifications: {len(certs)}" + (f" ({', '.join(certs)})" if certs else " — none yet"))
    if s["runs_per_certification"]:
        lines.append(f"runs-per-certification: {s['runs_per_certification']:.0f}  (the efficiency north star)")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="deterministic scorecard from the durable logs")
    ap.add_argument("--since-hours", type=float, default=0.0)
    args = ap.parse_args()
    since = time.time() - args.since_hours * 3600 if args.since_hours else 0.0
    rows = load_events(ROOT / "state" / "tasks.events.log")
    budget = load_events(ROOT / "state" / "budget.events.log")
    s = summarise(rows, budget, since_ts=since)
    merges = {p.name: git_merges(p) for p in sorted((ROOT / "projects").iterdir())
              if p.is_dir() and (p / ".git").exists()} if (ROOT / "projects").exists() else {}
    print(render(s, merges))


if __name__ == "__main__":
    main()
