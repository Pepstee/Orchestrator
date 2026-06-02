"""dispatch.repository — TaskRepository: the task lifecycle over the event store.

Every transition is driven through the total state machine (L11) and persisted as an event;
`replay()` reconstructs the entire task set from the log alone (crash recovery / resume-from-step).
Illegal transitions are no-ops, never crashes — the structural fix for v1's transition spam.
"""
from __future__ import annotations

from core.models import AgentResult, Event, Task, TaskStatus
from core.state_machine import transition
from infra.event_store import EventStore


class TaskRepository:
    def __init__(self, store: EventStore) -> None:
        self._store = store
        self._tasks: dict[str, Task] = {}

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

    def record_result(self, task_id: str, result: AgentResult) -> None:
        """Persist an agent's result to the durable log (audit; a failure carries its cause)."""
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
        """Persist the user's confirmation — the fourth gate, making the project truly DONE."""
        self._store.append("project_confirmed", {"project": project})

    def record_assurance(self, project: str, *, fully_hardened: bool, reason: str) -> None:
        """Persist the progressive-assurance outcome for a project (surfaced in the tray)."""
        self._store.append(
            "assurance_result",
            {"project": project, "fully_hardened": fully_hardened, "reason": reason},
        )

    def record_escalation(self, task_id: str, *, cause: str, reason: str, project: str = "") -> None:
        """Persist that a failure was escalated to the user (PA fast-path or retries exhausted)."""
        self._store.append(
            "escalation",
            {"task_id": task_id, "cause": cause, "reason": reason, "project": project},
        )

    def failure_causes(self) -> list[str]:
        """Every recorded failure cause (the overseer mines these to evolve the PA)."""
        return [
            ev.data.get("cause", "")
            for ev in self._store.replay()
            if ev.kind == "task_result" and not ev.data.get("ok") and ev.data.get("cause")
        ]

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
        return repo
