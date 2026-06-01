"""control.confirm — the confirmation surface (the user gate; the Da Nang one-tap).

A project that passes the automated gates parks at pending_user. You confirm it (CLI now; tray /
mobile later) by dropping a confirmation signal; the daemon ingests it and records the project as
confirmed — truly DONE. Signals are separate files (multi-writer safe), mirroring the inbox.

    python -m control.confirm                # list projects awaiting your confirmation
    python -m control.confirm <project>      # confirm one
"""
from __future__ import annotations

import argparse
from pathlib import Path

from dispatch.repository import TaskRepository
from infra.atomic_io import remove, write_json_atomic
from infra.event_store import EventStore


def default_confirm_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "state" / "confirmations"


def default_log() -> Path:
    return Path(__file__).resolve().parents[1] / "state" / "tasks.events.log"


def _blank() -> dict:
    return {"pending_user": False, "confirmed": False, "hardened": False, "assurance_reason": ""}


def project_states(store: EventStore) -> dict[str, dict]:
    """Fold the log into per-project {pending_user, confirmed, hardened, assurance_reason} state."""
    states: dict[str, dict] = {}
    for ev in store.replay():
        if ev.kind == "project_status":
            states.setdefault(ev.data["project"], _blank())["pending_user"] = bool(ev.data.get("pending_user"))
        elif ev.kind == "project_confirmed":
            states.setdefault(ev.data["project"], _blank())["confirmed"] = True
        elif ev.kind == "assurance_result":
            s = states.setdefault(ev.data["project"], _blank())
            s["hardened"] = bool(ev.data.get("fully_hardened"))
            s["assurance_reason"] = ev.data.get("reason", "")
    return states


def pending(store: EventStore) -> list[str]:
    """Projects finalised and awaiting confirmation (the tray)."""
    return sorted(p for p, s in project_states(store).items() if s["pending_user"] and not s["confirmed"])


def request_confirmation(project: str, confirm_dir: Path | str | None = None) -> Path:
    d = Path(confirm_dir) if confirm_dir else default_confirm_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{project}.json"
    write_json_atomic(path, {"project": project})
    return path


def ingest_confirmations(repo: TaskRepository, confirm_dir: Path | str | None = None) -> int:
    """Apply pending confirmation signals into the daemon's log (and remove them). Returns the count."""
    d = Path(confirm_dir) if confirm_dir else default_confirm_dir()
    if not d.exists():
        return 0
    count = 0
    for f in sorted(d.glob("*.json")):
        repo.record_confirmation(f.stem)
        remove(f)
        count += 1
    return count


def main() -> None:
    p = argparse.ArgumentParser(description="List or confirm projects awaiting your sign-off.")
    p.add_argument("project", nargs="?", help="project to confirm; omit to list the pending tray")
    args = p.parse_args()
    if args.project:
        request_confirmation(args.project)
        print(f"confirmation requested for {args.project!r} (the daemon will mark it DONE)")
    else:
        items = pending(EventStore(default_log()))
        print("Projects awaiting confirmation:" if items else "Nothing awaiting confirmation.")
        for proj in items:
            print(f"  - {proj}")


if __name__ == "__main__":
    main()
