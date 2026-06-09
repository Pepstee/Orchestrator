"""dispatch.repository — TaskRepository: the task lifecycle over the event store.

Every transition is driven through the total state machine (L11) and persisted as an event;
`replay()` reconstructs the entire task set from the log alone (crash recovery / resume-from-step).
Illegal transitions are no-ops, never crashes — the structural fix for v1's transition spam.
"""
from __future__ import annotations

from collections import Counter

from core.models import AgentResult, Event, Task, TaskStatus
from core.state_machine import transition
from infra.event_store import EventStore
from infra.llm import is_transient_cause


# Ported from v1 (port/v1/error_triage.py): even "self-resolving" transient causes get a finite
# requeue budget per task. Misclassification is inevitable (a task's own output may contain a
# rate-limit phrase); after this many transient requeues the task falls to the BOUNDED ladder.
MAX_TRANSIENT_REQUEUES = 5


class TaskRepository:
    def __init__(self, store: EventStore) -> None:
        self._store = store
        self._tasks: dict[str, Task] = {}
        self._confirmed: set[str] = set()
        self._hard_failures: Counter = Counter()       # task_id -> non-transient failure count
        self._transient_failures: Counter = Counter()  # task_id -> transient failure count

    def create(self, task: Task) -> Task:
        self._tasks[task.task_id] = task
        self._store.append("task_created", {"task": task.to_dict()})
        return task

    def apply(self, task_id: str, event: Event) -> Task:
        task = self._tasks[task_id]
        new_status = transition(task.status, event)
        if new_status is None:
            return task  # no-op transition — nothing persisted, never an error
        old = task.status
        task.status = new_status
        self._store.append(
            "task_transition",
            {"task_id": task_id, "event": event.value, "from": old.value, "to": new_status.value},
        )
        return task

    def cancel_task(self, task_id: str, *, cause: str = "") -> None:
        """Terminally cancel a non-terminal task (the overseer abandoning a doomed project). QUEUED has
        no direct ->FAIL in the state machine, so it passes through BLOCKED first. No-op on a task that
        is already terminal or absent. Reversible: the work can be re-enqueued; this only stops it."""
        task = self._tasks.get(task_id)
        if task is None or task.status in (TaskStatus.DONE, TaskStatus.FAILED):
            return
        if task.status == TaskStatus.QUEUED:
            self.apply(task_id, Event.BLOCK)     # QUEUED -> BLOCKED (legal), so we can then FAIL
        self.apply(task_id, Event.FAIL)          # IN_PROGRESS / BLOCKED -> FAILED
        self._store.append("task_cancelled", {"task_id": task_id, "cause": cause})

    def set_priority(self, task_id: str, priority: int) -> None:
        """Set a task's scheduling priority (the overseer reprioritising work). Persisted as its own
        event so it survives replay; select_next_task runs higher-priority ready tasks first."""
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.priority = int(priority)
        self._store.append("task_reprioritised", {"task_id": task_id, "priority": int(priority)})

    def record_result(self, task_id: str, result: AgentResult) -> None:
        """Persist an agent's result to the durable log (audit; a failure carries its cause).
        Failure budgets are counted HERE, off the durable record, so they survive restart —
        a replay reconstructs the same counts and a restart can never launder a retry budget."""
        if not result.ok:
            if is_transient_cause(result.cause or ""):
                self._transient_failures[task_id] += 1
            else:
                self._hard_failures[task_id] += 1
        self._store.append(
            "task_result",
            {
                "task_id": task_id,
                "ok": result.ok,
                "summary": result.summary,
                "cause": result.cause,
                "artifacts": result.artifacts,
            },
        )

    def record_project_status(self, project: str, *, gates: dict, pending_user: bool) -> None:
        """Persist a project's completion status (the durable signal a confirmation tray reads)."""
        self._store.append(
            "project_status",
            {"project": project, "gates": gates, "pending_user": pending_user},
        )

    def record_confirmation(self, project: str) -> None:
        """Persist the certification that makes the project DONE (self-certified under DG-2)."""
        self._confirmed.add(project)
        self._store.append("project_confirmed", {"project": project})

    def confirmed_projects(self) -> frozenset[str]:
        """Projects with a recorded certification (BG-2 reads this to lift the breadth cap)."""
        return frozenset(self._confirmed)

    def record_assurance(self, project: str, *, fully_hardened: bool, reason: str) -> None:
        """Persist the progressive-assurance outcome for a project (surfaced in the tray)."""
        self._store.append(
            "assurance_result",
            {"project": project, "fully_hardened": fully_hardened, "reason": reason},
        )

    def record_abandoned(self, project: str, *, reason: str) -> None:
        """The orchestrator gave up on a project it couldn't complete autonomously (planner + overseer
        exhausted). Logged for the record; nothing waits on the operator. Re-enqueueable later."""
        self._store.append("project_abandoned", {"project": project, "reason": reason})

    def record_escalation(self, task_id: str, *, cause: str, reason: str, project: str = "") -> None:
        """Persist that a failure was escalated to the user (PA fast-path or retries exhausted)."""
        self._store.append(
            "escalation",
            {"task_id": task_id, "cause": cause, "reason": reason, "project": project},
        )

    def hard_failure_count(self, task_id: str) -> int:
        """Durable count of non-transient failures (the restart-proof retry budget, BG-3)."""
        return self._hard_failures[task_id]

    def transient_count(self, task_id: str) -> int:
        """Durable count of transient failures (caps the 'no-penalty' requeue path, BG-3)."""
        return self._transient_failures[task_id]

    def last_results(self) -> dict[str, dict]:
        """task_id -> the latest {ok, cause, summary} (the planner reads failure causes to replan)."""
        out: dict[str, dict] = {}
        for ev in self._store.replay():
            if ev.kind == "task_result":
                out[ev.data["task_id"]] = {"ok": ev.data.get("ok"), "cause": ev.data.get("cause"),
                                           "summary": ev.data.get("summary")}
        return out

    def failure_causes(self) -> list[str]:
        """Every recorded failure cause (the overseer mines these to evolve the PA)."""
        return [
            ev.data.get("cause", "")
            for ev in self._store.replay()
            if ev.kind == "task_result" and not ev.data.get("ok") and ev.data.get("cause")
        ]

    def reclaim_orphans(self) -> int:
        """Re-queue tasks left IN_PROGRESS by a crash or restart (L11 recovery). Their subprocess died
        with the old daemon, so nothing would ever finish them; RECLAIM returns them to QUEUED. Run on
        startup — essential when the daemon is restarted on the Claude Max 5-hour cadence."""
        count = 0
        for task in list(self._tasks.values()):
            if task.status == TaskStatus.IN_PROGRESS:
                self.apply(task.task_id, Event.RECLAIM)
                count += 1
        return count

    def revive_transient_failures(self) -> int:
        """Re-queue tasks that FAILED for a TRANSIENT cause — a provider limit, a restart-kill, or a git
        merge conflict. Such a failure is infra, not the task's fault, so it must never be terminal: on
        restart, retry it. Under the per-project cap (one agent per tree) a revived conflict re-runs
        alone and merges cleanly. This also clears stale 'needs you' escalations recorded before the cap
        was in force (their cause is now classified transient, so the GUI filters them too). Run once on
        startup, right after reclaim_orphans."""
        causes = self.last_results()
        count = 0
        for task in list(self._tasks.values()):
            if task.status != TaskStatus.FAILED:
                continue
            res = causes.get(task.task_id)
            if (res and not res.get("ok") and is_transient_cause(res.get("cause") or "")
                    and self._transient_failures[task.task_id] <= MAX_TRANSIENT_REQUEUES):
                self.apply(task.task_id, Event.REQUEUE)   # under budget — infra fault, retry
                count += 1
        return count

    def claim_next(self, *, per_project_cap: int = 1,
                   allowed_projects: "set[str] | None" = None) -> Task | None:
        """Pick the next ready, non-`control` task, mark it IN_PROGRESS, and return it (or None).
        Ready = QUEUED with every prerequisite DONE.

        `per_project_cap` bounds how many tasks of ONE project may run concurrently (0 = unbounded).
        At the default of 1 a project is effectively serialised: two agents never edit the same
        project tree at once, so the intra-project merge-conflict thrash (concurrent agents touching
        the same lines → worktree conflict → retry → wasted tokens) cannot occur. Cross-project
        concurrency is untouched — all active projects still advance in parallel, so throughput tracks
        the number of live projects. Raise the cap (env `AGENTIC_PROJECT_CONCURRENCY`) to trade some
        conflict risk for intra-project parallelism; the worktree isolation (infra.worktree) stays in
        place either way and makes >1 safe.

        Claim-on-select means the next claim can't hand out the same task. Called only from the
        dispatcher's main thread, so the IN_PROGRESS tally below is race-free."""
        running = Counter(
            t.project for t in self._tasks.values() if t.status == TaskStatus.IN_PROGRESS
        )
        for task in self._tasks.values():
            if task.status != TaskStatus.QUEUED or task.task_type == "control":
                continue
            if (allowed_projects is not None and not task.project.startswith("__")
                    and task.project not in allowed_projects):
                continue   # BG-2: depth before breadth — project not in the current allowance
            if per_project_cap and running.get(task.project, 0) >= per_project_cap:
                continue
            if all(self._tasks.get(d) is not None and self._tasks[d].status == TaskStatus.DONE
                   for d in task.depends_on):
                self.apply(task.task_id, Event.CLAIM)
                return task
        return None

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(self, status: TaskStatus | None = None) -> list[Task]:
        return [t for t in self._tasks.values() if status is None or t.status == status]

    @classmethod
    def replay(cls, store: EventStore) -> "TaskRepository":
        """Reconstruct the full task set from the log alone (resume-from-step)."""
        repo = cls(store)
        for ev in store.replay():
            if ev.kind == "task_created":
                t = Task.from_dict(ev.data["task"])
                repo._tasks[t.task_id] = t
            elif ev.kind == "task_transition":
                t = repo._tasks.get(ev.data["task_id"])
                if t is not None:
                    t.status = TaskStatus(ev.data["to"])
            elif ev.kind == "task_reprioritised":
                t = repo._tasks.get(ev.data["task_id"])
                if t is not None:
                    t.priority = int(ev.data.get("priority", 0))
            elif ev.kind == "project_confirmed":
                repo._confirmed.add(ev.data.get("project", ""))
            elif ev.kind == "task_result" and not ev.data.get("ok"):
                if is_transient_cause(ev.data.get("cause") or ""):
                    repo._transient_failures[ev.data["task_id"]] += 1
                else:
                    repo._hard_failures[ev.data["task_id"]] += 1
        return repo
