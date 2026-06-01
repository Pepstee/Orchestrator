"""dispatch.repository — TaskRepository: the task lifecycle over the event store.

Every transition is driven through the total state machine (L11) and persisted as an event;
`replay()` reconstructs the entire task set from the log alone (crash recovery / resume-from-step).
Illegal transitions are no-ops, never crashes — the structural fix for v1's transition spam.
"""
from __future__ import annotations

from core.models import Event, Task, TaskStatus
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
