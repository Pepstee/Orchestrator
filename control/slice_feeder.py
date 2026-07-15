"""control.slice_feeder — the charter's slice ritual, automated (16 §4, made hands-off).

The v3 build charter mandates: feed ONE slice, wait for it to certify, feed the next — never all
ten at once (depth before breadth). That ritual is deterministic, so this companion process runs
it: it watches the durable event log and, when the current slice is certified AND the project's
graph is fully terminal, drops the next slice's plan task into the inbox. The daemon ingests it
on its next cycle — the feeder never touches the daemon's state, only the multi-writer-safe
intake channel (same discipline as edge.server: read the log, act through existing channels).

Trigger, per slice n (1-based; Slice 1 ships seeded):
    certifications(orchestrator-v3) >= n  AND  every orchestrator-v3 task is terminal
    -> enqueue the Slice n+1 plan task, advance the durable cursor (state/v3_slice.json).

Run alongside the daemon (survives daemon restarts; safe to restart itself — the cursor and the
inbox are both durable and idempotent):

    nohup python3 -m control.slice_feeder > slice_feeder.log 2>&1 &

Stops by itself after feeding Slice 10, or with the repo-root STOP sentinel.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from control.inbox import drop
from core.models import Task, TaskStatus
from dispatch.repository import TaskRepository
from infra.atomic_io import read_json, write_json_atomic
from infra.event_store import EventStore
from infra.notify import notify

PROJECT = "orchestrator-v3"
POLL_SECONDS = 60.0
FINAL_SLICE = 16   # 2-10: the build charter (16 §3); 11-16: the GIGA capability wave (planning/18)

# Slices 2-10, verbatim from the charter's table (16 §3), with the ratified pure-Python ME shape
# (ports + manifests + fail-closed loader — spec 17 ME-1..3) folded into slices 2-3 where it is
# nearly free to bake in and expensive to retrofit. Containers/broker/selfdev stay post-P0 (17 §10).
SLICES: dict[int, tuple[str, list[str]]] = {
    2: ("Build orchestrator-v3 Slice 2 — the enforcement toolchain — in projects/orchestrator-v3/, "
        "on top of the seeded core+spine. Inherit v2's enforcement patterns; do not reinvent.",
        ["lint-imports passes an inward-only layer contract (core <- infra <- dispatch <- ...)",
         "charter/laws.py declares every law as data; test_every_law_has_a_check is green",
         "a boot self-test refuses to dispatch when the test suite is missing or red — proven by a "
         "test that hides a required test and asserts the refusal",
         "a module manifest format exists as data (name, port, capabilities, tests) with a "
         "fail-closed loader: an invalid manifest or red declared test means the module does not "
         "load — proven by test (ME-1/ME-2 shape, pure Python, no containers)",
         "ruff + pytest + lint-imports all green; no mocks in any shipped module"]),
    3: ("Build orchestrator-v3 Slice 3 — the agent contract, runner, and registry — in "
        "projects/orchestrator-v3/. Payload on stdin, exactly one AgentResult on stdout.",
        ["agents/common.py implements the IO contract; a crash becomes a caused AgentResult, "
         "never a bare traceback",
         "dispatch/runner.py routes task_type -> agent -> command via registry/agents.py; "
         "test_registry_single_source is green",
         "the registry is generated from module manifests, not hand-edited (ME-3: modules are "
         "islands; an architecture test forbids module-to-module imports)",
         "a dummy agent runs end-to-end through the runner in a test",
         "ruff + pytest + lint-imports green; no mocks in shipped modules"]),
    4: ("Build orchestrator-v3 Slice 4 — the dispatcher, concurrent pool, and failure ladder — in "
        "projects/orchestrator-v3/. Port v1's failure taxonomy verbatim (TRANSIENT/RECOVERABLE/"
        "PERMANENT); every requeue path is finite.",
        ["run_concurrent drives ready tasks with a per-project concurrency cap of 1 by default",
         "failure ladder: transient requeue (budget-capped) -> bounded retry -> escalate; budgets "
         "derive from the event log and survive restart",
         "a poison task consumes exactly its retry budget then terminal-fails — proven by a drill test",
         "a merge-conflict class failure is bounded and surfaced, never looped",
         "ruff + pytest + lint-imports green; no mocks in shipped modules"]),
    5: ("Build orchestrator-v3 Slice 5 — the completion gates — in projects/orchestrator-v3/. "
        "Done means demonstrated, not asserted.",
        ["completion contract = tests AND acceptance AND judge AND authenticity, all automated",
         "authenticity gate: stubs/TODO/mock identifiers in shipped code fail the gate",
         "acceptance-by-execution: no declaration fails; a mock tell in a criterion fails",
         "cross-provider judge wired behind the provider seam",
         "negative control proven: the gate set FAILS a deliberately-stubbed sample project and "
         "PASSES a known-good one",
         "the adversarial/hardening rung is severity-aware: minor findings log to the improvement "
         "backlog without blocking certification; blocker/major findings block (the 14 Jul "
         "infinite-treadmill lesson — a binary adversarial verdict makes 'hardened' unreachable)",
         "ruff + pytest + lint-imports green"]),
    6: ("Build orchestrator-v3 Slice 6 — the economic layer — in projects/orchestrator-v3/.",
        ["budget cap + kill-switch reachable three ways and honoured mid-batch — drilled by test",
         "per-task attempt and token budgets enforced at dispatch",
         "burn-rate breaker: trailing success ratio below 40% pauses paid work and notifies",
         "a usage-cap exit (bare non-zero, no diagnostic) is a transient pause-until-reset, never a "
         "task failure; a recognisable auth error fails FAST and notifies — both drilled",
         "ruff + pytest + lint-imports green"]),
    7: ("Build orchestrator-v3 Slice 7 — the load-bearing knowledge base — port memory/knowledge.py "
        "and its tests from v2 into projects/orchestrator-v3/; adapt import paths only.",
        ["the KB module is in with its tests green",
         "three fail-closed seam-gates wired: a task cannot complete without a KB entry; the "
         "planner's context includes recall(); the boot self-test asserts both",
         "each seam-gate is proven fail-closed by a test that removes the capability and asserts refusal",
         "ruff + pytest + lint-imports green"]),
    8: ("Build orchestrator-v3 Slice 8 — deep research — port agents/researcher.py and "
        "validation/research_contract.py with tests from v2 into projects/orchestrator-v3/.",
        ["a Tier-1-only, link-dump, uncorroborated, or paywalled bundle FAILS the research gate — "
         "one test per refusal class",
         "research findings land as KB entries (composes with Slice 7)",
         "research runs under the Slice 6 budgets",
         "ruff + pytest + lint-imports green"]),
    9: ("Build orchestrator-v3 Slice 9 — overseer, daemon, and supervisor — in "
        "projects/orchestrator-v3/. The P0 certification slice.",
        ["persistent overseer with disk memory via the KB digest; --resume is an optimisation whose "
         "failure is non-fatal; session ids are canonical dashed UUIDs",
         "a supervised run-forever loop honours a repo-root STOP; a deterministic boot refusal "
         "(self-test red) stays down instead of relaunch-looping",
         "DV-7 dev-mode sentinel: state/DEVMODE whitelists operator edits and disables auto-apply",
         "P0 drill: one real sample project driven end-to-end through all four gates unattended; a "
         "forced kill -9 mid-task resumes from step; kill-switch and budget cap halt spend",
         "ruff + pytest + lint-imports green"]),
    10: ("Build orchestrator-v3 Slice 10 — remote control and GUI — in projects/orchestrator-v3/.",
         ["a token-authed GUI shows health, projects, and a NEEDS-YOU tray",
          "notifications plus a signals/queries surface reachable over SSH or Tailscale",
          "stop and confirm actions work from a phone browser",
          "the GUI reads durable state and acts only through channels the daemon already ingests",
          "ruff + pytest + lint-imports green"]),
    # ── The GIGA capability wave (post-P0; docs/planning/18) — evals are the hub ──────────
    11: ("Build orchestrator-v3 Slice 11 — the eval harness (law A2 made ACTIVE) — in "
         "projects/orchestrator-v3/. Behaviour evals as a load-bearing organ, not a deferred law.",
         ["an EvalPort module: eval cases as data (input, rubric, grader model), results in a "
          "durable eval store (append-only, replayable)",
          "LLM-graded rubric evals run as a gate tier: a behaviour change (prompt, agent, model) "
          "cannot land without a non-regressing eval run — proven by a test that regresses a "
          "rubric score and asserts refusal",
          "the selfdev promotion pipeline consults the eval store: a candidate with regressed "
          "evals is refused promotion (the ME-5 hook)",
          "execution-shaped validation enforced: a validate task whose instructions forbid "
          "execution FAILS the gate (the 12 Jul review-only gaming class, closed by test)",
          "ruff + pytest + lint-imports green"]),
    12: ("Build orchestrator-v3 Slice 12 — eval-driven model routing — in projects/orchestrator-v3/. "
         "Port v1's benchmark harness (docs/planning/port/v1); routing is earned by receipts.",
         ["a benchmark module runs a fixed prompt set across configured provider/model pairs and "
          "writes scores to the eval store",
          "registry model assignments carry a benchmark reference; a change to an agent's model "
          "without an eval-store receipt fails an architecture test",
          "per-agent env overrides remain the documented outage lever (reversible, receipt-exempt)",
          "ruff + pytest + lint-imports green"]),
    13: ("Build orchestrator-v3 Slice 13 — the feedback distiller (the operator's taste becomes "
         "regression tests) — in projects/orchestrator-v3/.",
         ["operator corrections are captured as KB entries: Telegram vetoes/instructions, "
          "constitution-window rejections, manual requeues, fence quarantines",
          "each captured correction generates a CANDIDATE eval case (promoted to active via the "
          "curated gate, like PA rules — never autonomously)",
          "a test proves the loop: a simulated operator correction yields a KB entry and a "
          "candidate eval case",
          "ruff + pytest + lint-imports green"]),
    14: ("Build orchestrator-v3 Slice 14 — the personal knowledge corpus (life-shaped memory, "
         "not code-shaped) — in projects/orchestrator-v3/.",
         ["the KB MemoryPort accepts external corpora: operator-configured directories of notes, "
          "journal, research, transcripts, ingested as manifest-gated connector modules",
          "planner and overseer context includes recall() over the personal corpus, budget-capped "
          "(context minimalism: smallest high-signal set — the 500k-token session lesson)",
          "ingestion is read-only over the source directories (an architecture test proves no "
          "write path into the corpus)",
          "ruff + pytest + lint-imports green"]),
    15: ("Build orchestrator-v3 Slice 15 — the scheduler and morning briefing (the AI-OS surface) "
         "— in projects/orchestrator-v3/. The scheduling/ seam earns its existence.",
         ["a SchedulerPort module: cron-style schedule data drives task creation through the "
          "normal inbox channel (never direct log writes)",
          "a daily briefing composes from the KB + ledger: what changed, why it matters, "
          "suggested actions — delivered via notify and the GUI",
          "suggested actions execute one-tap through EXISTING channels (confirm/inbox/focus) — "
          "an architecture test proves the briefing surface cannot bypass a law",
          "ruff + pytest + lint-imports green"]),
    16: ("Build orchestrator-v3 Slice 16 — leverage metrics (measure the thesis) — in "
         "projects/orchestrator-v3/.",
         ["the scorecard computes operator-touches-per-certification (every operator channel "
          "event counted: confirms, vetoes, Telegram directives, manual requeues)",
          "window-cost per project derives from focus_changed events and per-call usage rows",
          "both metrics render in the GUI and the briefing; the eval store trends alongside",
          "ruff + pytest + lint-imports green"]),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def certifications(repo: TaskRepository, project: str = PROJECT) -> int:
    """How many certification events the project has accumulated (one per certified slice)."""
    store = repo._store  # noqa: SLF001 — companion process reading the same durable log
    return sum(1 for ev in store.replay()
               if ev.kind == "project_confirmed" and ev.data.get("project") == project)


def all_terminal(repo: TaskRepository, project: str = PROJECT) -> bool:
    tasks = [t for t in repo.list() if t.project == project]
    return bool(tasks) and all(t.status in (TaskStatus.DONE, TaskStatus.FAILED) for t in tasks)


def next_slice_due(repo: TaskRepository, cursor: int) -> bool:
    """Slice `cursor` is the last one fed (1 = the seeded core+spine). The next is due when the
    project holds at least `cursor` certifications AND its graph is fully terminal."""
    if cursor >= FINAL_SLICE:
        return False
    return certifications(repo) >= cursor and all_terminal(repo)


def build_slice_task(n: int) -> Task:
    """Each slice's plan opens a FRESH contract era (payload mode='rescope', honoured by the
    daemon's _era_counts): 20 planner passes + the full overseer-intervention budget PER SLICE,
    not per build. Without this, all ten slices share one era — 10 Jul: Slice 2 arrived with
    Slice 1's spent ledger and was abandoned mid-hardening. A rescope also revives a parked
    (abandoned) project: the new task passes the abandonment watermark deliberately."""
    goal, accept = SLICES[n]
    return Task(task_id=uuid.uuid4().hex[:12], title=goal, task_type="plan",
                project=PROJECT, acceptance_criteria=list(accept),
                payload={"mode": "rescope"})


def read_cursor(path: Path) -> int:
    data = read_json(path)
    return int(data.get("last_fed", 1)) if isinstance(data, dict) else 1


def feed_next(root: Path, cursor: int) -> int:
    """Drop the Slice cursor+1 plan task into the inbox and persist the advanced cursor."""
    n = cursor + 1
    drop(build_slice_task(n), root / "state" / "inbox")
    write_json_atomic(root / "state" / "v3_slice.json", {"last_fed": n})
    notify("Slice feeder", f"Slice {cursor} certified — fed Slice {n} to the orchestrator")
    return n


def main() -> None:
    root = _repo_root()
    cursor_path = root / "state" / "v3_slice.json"
    while not (root / "STOP").exists():
        cursor = read_cursor(cursor_path)
        if cursor >= FINAL_SLICE:
            notify("Slice feeder", "Slice 10 fed — the charter is fully dispatched; feeder exiting")
            return
        try:
            repo = TaskRepository.replay(EventStore(root / "state" / "tasks.events.log"))
            if next_slice_due(repo, cursor):
                feed_next(root, cursor)
        except Exception:
            pass  # a torn read of the live log is retried next poll; never crash the ritual
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
