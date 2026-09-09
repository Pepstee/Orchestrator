"""Offline historical-v2 integration demo with a synthetic agent boundary.

Creates a real deterministic greeter, executes its tests and acceptance command, scans
its authenticity, and exercises automated certification plus the PA failure ladder.
The judge result is scripted: this demonstrates orchestration wiring, not independent
LLM review or live factory readiness. Notifications are captured locally; no provider,
account, personal corpus, or existing runtime state is used. All evidence remains in a
new temporary directory.

    python3 scripts/demo_e2e.py
"""
from __future__ import annotations

import shlex
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from control.budget import BudgetGovernor
from control.daemon import monitor_projects
from control.inbox import ingest
from control.intake import submit_goal
from control.loop import run as run_loop
from core.models import AgentResult
from dispatch.repository import TaskRepository
from edge.server import build_state
from infra.atomic_io import write_text_atomic
from infra.event_store import EventStore
from pa.rules import Rule, consult
from validation.gates import run_test_gate

_TEST_CMD = (sys.executable, "-B", "-m", "unittest", "discover", "-q")


def banner(n: int, title: str) -> None:
    print(f"\n{'=' * 72}\n {n}. {title}\n{'=' * 72}")


def stub_invoke(task, projects_root: Path) -> AgentResult:
    """Synthetic worker: materialise real source, or return an explicitly scripted judge result."""
    if task.project == "flaky" and task.task_type != "validate":
        return AgentResult(ok=False, summary="build failed",
                           cause="ImportError: no module named 'httpx'",
                           metadata={"cost_usd": 0.0})
    if task.task_type == "validate":
        return AgentResult(ok=True, summary="synthetic judge approval (no independent LLM review)",
                           metadata={"score": 0.96, "cost_usd": 0.0})
    if task.task_type == "plan":
        return AgentResult(ok=True, summary="synthetic planner selected no additional work")
    product = projects_root / task.project
    write_text_atomic(product / "app.py", (
        'import argparse\n\ndef greet(name):\n    return "Hello, " + name.strip() + "!"\n\n'
        'if __name__ == "__main__":\n    parser = argparse.ArgumentParser()\n'
        '    parser.add_argument("name")\n    print(greet(parser.parse_args().name))\n'
    ))
    write_text_atomic(product / "test_app.py", (
        'import unittest\nfrom app import greet\n\nclass GreeterTests(unittest.TestCase):\n'
        '    def test_name(self):\n        self.assertEqual(greet("Ada"), "Hello, Ada!")\n'
        '    def test_whitespace(self):\n        self.assertEqual(greet("  Lin  "), "Hello, Lin!")\n'
    ))
    write_text_atomic(product / "acceptance_check.py", (
        'import subprocess\nimport sys\n\n'
        'result = subprocess.run([sys.executable, "-B", "app.py", "Ada"],\n'
        '                        capture_output=True, text=True, check=True)\n'
        'if result.stdout != "Hello, Ada!\\n":\n'
        '    raise SystemExit("Greeting output differs from declared acceptance")\n'
        'print(result.stdout, end="")\n'
    ))
    write_text_atomic(product / "acceptance", shlex.quote(sys.executable) + " -B acceptance_check.py\n")
    return AgentResult(ok=True, summary="created the deterministic greeter and executable checks",
                       artifacts=["app.py", "test_app.py", "acceptance_check.py", "acceptance"],
                       metadata={"cost_usd": 0.0})


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="e2e_"))
    projroot = tmp / "projects"
    for proj in ("greeter", "flaky"):
        (projroot / proj).mkdir(parents=True)

    tasks_log, budget_log = tmp / "tasks.events.log", tmp / "budget.events.log"
    inbox = tmp / "inbox"
    repo = TaskRepository(EventStore(tasks_log))
    gov = BudgetGovernor(EventStore(budget_log), cap_usd=10.0, kill_switch_path=tmp / "KILL")

    # the overseer has previously learned ImportError is a dead-end (an active PA rule)
    pa_rules = [Rule(id="r1", pattern="ImportError", action="escalate", status="active")]

    def pa_consult(cause: str):
        return consult(cause, pa_rules)

    def invoke(task):
        return stub_invoke(task, projroot)

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
    run_loop(repo, invoke, gov, pa_consult=pa_consult)
    print(f"   greeter tasks -> "
          f"{[t.task_id + ':' + t.status.value for t in repo.list() if t.project == 'greeter']}")
    print(f"   budget spent  -> ${gov.spent():.4f}")

    banner(4, "Evaluate the four gates + run the assurance loop  (deterministic tier)")
    notices = []
    with patch("control.daemon.notify", lambda *args: notices.append(args)):
        outcomes = monitor_projects(repo, {}, projects_root=str(projroot),
                                    test_command=_TEST_CMD, tiers=tiers(), governor=gov)
    assert len(outcomes) == 1 and outcomes[0].complete
    assert outcomes[0].gates == dict.fromkeys(("tests", "acceptance", "judge", "authenticity"), True)
    for outcome in outcomes:
        print(f"   {outcome.project}: gates={outcome.gates}  complete={outcome.complete}")
    print("   judge is synthetic; hardening tier reruns the real deterministic test suite")
    print(f"   captured {len(notices)} local notification(s); none sent")

    banner(5, "GUI state — what the phone shows")
    s = state()
    print(f"   pending confirmations: {s['pending']}")
    print(f"   project badges: {s['projects']}")

    banner(6, "Verify automated certification survives replay (no human confirmation gate)")
    replayed = TaskRepository.replay(EventStore(tasks_log))
    assert "greeter" in replayed.confirmed_projects()
    assert s["projects"]["greeter"]["confirmed"] and s["pending"] == []
    print("   greeter is certified; the historical monitor may enqueue an improvement round")
    print("   further planning uses the same synthetic boundary; no daemon is launched")

    banner(7, "Failure path — a goal whose build keeps erroring")
    submit_goal("Fetch data over HTTP", project="flaky", inbox=str(inbox))
    ingest(repo, inbox)
    run_loop(repo, invoke, gov, pa_consult=pa_consult)
    print("   flaky tasks -> "
          + str([f"{t.task_id}:{t.status.value}(retries={t.retries})"
                 for t in repo.list() if t.project == "flaky"]))

    banner(8, "GUI surfaces the escalation  (PA: ImportError -> escalate, 0 retries)")
    escalations = state()["escalations"]
    assert escalations and any(e["cause"] and "ImportError" in e["cause"] for e in escalations)
    for e in escalations:
        print(f"   needs you: task {e['task_id']} — {e['reason']} — {e['cause']}")
    assert gov.spent() == 0.0
    print(f"\n   synthetic boundary; actual provider calls: 0\n   total budget spent across both runs: ${gov.spent():.4f}")
    print(f"   state dir: {tmp}")


if __name__ == "__main__":
    main()
