"""scripts/demo_e2e.py — full-stack integration run with the LLM boundary stubbed.

Proves the v2 slices compose into one working lifecycle WITHOUT any LLM call: a goal is decomposed,
built, judged, gated, hardened, parked for the user, shown in the GUI state, confirmed and marked
DONE — and a separate failing goal climbs the failure ladder (PA fast-path) to an escalation the GUI
surfaces. Real LLM agents only run on an authenticated machine (see the README); here the agent
boundary is a deterministic stub so the run is fast, free and reproducible.

    TMPDIR=/tmp python3 scripts/demo_e2e.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control.budget import BudgetGovernor
from control.confirm import ingest_confirmations, request_confirmation
from control.daemon import monitor_projects
from control.inbox import ingest
from control.intake import submit_goal
from control.loop import run as run_loop
from core.models import AgentResult
from dispatch.repository import TaskRepository
from edge.server import build_state
from infra.event_store import EventStore
from pa.rules import Rule, consult
from validation.gates import run_test_gate

_TEST_CMD = ("python3", "-c", "pass")   # stand-in for the project's own suite (exits 0); real runs use pytest


def banner(n: int, title: str) -> None:
    print(f"\n{'=' * 72}\n {n}. {title}\n{'=' * 72}")


def stub_invoke(task) -> AgentResult:
    """The agent boundary, deterministic: greeter succeeds; flaky's build errors; validate approves."""
    if task.project == "flaky" and task.task_type != "validate":
        return AgentResult(ok=False, summary="build failed",
                           cause="ImportError: no module named 'httpx'",
                           metadata={"cost_usd": 0.004})
    if task.task_type == "validate":
        return AgentResult(ok=True, summary="independent review passed",
                           metadata={"score": 0.96, "cost_usd": 0.0})
    return AgentResult(ok=True, summary="built the deliverable",
                       artifacts=["app.py"], metadata={"cost_usd": 0.01})


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="e2e_"))
    projroot = tmp / "projects"
    for proj in ("greeter", "flaky"):
        (projroot / proj).mkdir(parents=True)   # the gate runs the suite here (stubbed via _TEST_CMD)

    tasks_log, budget_log = tmp / "tasks.events.log", tmp / "budget.events.log"
    inbox, confirms = tmp / "inbox", tmp / "confirmations"
    repo = TaskRepository(EventStore(tasks_log))
    gov = BudgetGovernor(EventStore(budget_log), cap_usd=10.0, kill_switch_path=tmp / "KILL")

    # the overseer has previously learned ImportError is a dead-end (an active PA rule)
    pa_rules = [Rule(id="r1", pattern="ImportError", action="escalate", status="active")]

    def pa_consult(cause: str):
        return consult(cause, pa_rules)

    def state() -> dict:
        return build_state(tasks_log=tasks_log, budget_log=budget_log)

    def tiers():
        return [lambda d: run_test_gate(d, command=_TEST_CMD)]   # deterministic hardening (no LLM)

    banner(1, "Submit a goal  (intake -> inbox)")
    ids = submit_goal("Build a greeter CLI with a test", project="greeter",
                      acceptance=["prints a greeting", "has a test"], inbox=str(inbox))
    print(f"   enqueued {len(ids)} tasks: {ids}")

    banner(2, "Daemon ingests the inbox  (live enqueue)")
    print(f"   ingested {ingest(repo, inbox)} tasks -> "
          f"{[t.task_id + ':' + t.status.value for t in repo.list()]}")

    banner(3, "Run the graph under the budget loop  (stubbed agents, PA fast-path armed)")
    run_loop(repo, stub_invoke, gov, pa_consult=pa_consult)
    print(f"   greeter tasks -> "
          f"{[t.task_id + ':' + t.status.value for t in repo.list() if t.project == 'greeter']}")
    print(f"   budget spent  -> ${gov.spent():.4f}")

    banner(4, "Evaluate the four gates + run the assurance loop  (deterministic tier)")
    for o in monitor_projects(repo, {}, projects_root=str(projroot),
                              test_command=_TEST_CMD, tiers=tiers(), governor=gov):
        print(f"   {o.project}: gates={o.gates}  pending_user={o.pending_user}")

    banner(5, "GUI state — what the phone shows")
    s = state()
    print(f"   needs your tap: {s['pending']}")
    print(f"   project badges: {s['projects']}")

    banner(6, "One-tap confirm  (GUI POST -> confirm channel -> daemon ingests)")
    request_confirmation("greeter", confirms)
    ingest_confirmations(repo, confirms)
    s = state()
    print(f"   greeter confirmed: {s['projects']['greeter']['confirmed']}  -> truly DONE")
    print(f"   pending now: {s['pending']}")

    banner(7, "Failure path — a goal whose build keeps erroring")
    submit_goal("Fetch data over HTTP", project="flaky", inbox=str(inbox))
    ingest(repo, inbox)
    run_loop(repo, stub_invoke, gov, pa_consult=pa_consult)
    print("   flaky tasks -> "
          + str([f"{t.task_id}:{t.status.value}(retries={t.retries})"
                 for t in repo.list() if t.project == "flaky"]))

    banner(8, "GUI surfaces the escalation  (PA: ImportError -> escalate, 0 retries)")
    for e in state()["escalations"]:
        print(f"   needs you: task {e['task_id']} — {e['reason']} — {e['cause']}")
    print(f"\n   total budget spent across both runs: ${gov.spent():.4f}")
    print(f"   state dir: {tmp}")


if __name__ == "__main__":
    main()
