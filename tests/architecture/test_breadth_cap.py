"""BG-2 — depth before breadth: flagship-only dispatch until a first certification exists."""
from __future__ import annotations

from pathlib import Path

from control.breadth import breadth_allowance, read_flagship
from core.models import Task
from dispatch.repository import TaskRepository
from infra.event_store import EventStore

ROOT = Path(__file__).resolve().parents[2]


def _repo(tmp_path) -> TaskRepository:
    return TaskRepository(EventStore(tmp_path / "events.log"))


def test_claim_next_honours_the_allowance(tmp_path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="a1", title="a", task_type="implement", project="alpha"))
    repo.create(Task(task_id="b1", title="b", task_type="implement", project="beta"))
    task = repo.claim_next(allowed_projects={"beta"})
    assert task is not None and task.project == "beta"
    assert repo.claim_next(allowed_projects={"beta"}) is None  # alpha stays parked


def test_empty_allowance_parks_everything_buildable(tmp_path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="a1", title="a", task_type="implement", project="alpha"))
    assert repo.claim_next(allowed_projects=set()) is None


def test_reserved_meta_projects_always_dispatch(tmp_path):
    repo = _repo(tmp_path)
    repo.create(Task(task_id="o1", title="pulse", task_type="oversee", project="__overseer__"))
    task = repo.claim_next(allowed_projects=set())
    assert task is not None and task.project == "__overseer__"


def test_allowance_is_flagship_until_certification_then_lifts(tmp_path):
    repo = _repo(tmp_path)
    assert breadth_allowance(repo, "dubbing-studio") == {"dubbing-studio"}
    assert breadth_allowance(repo, None) == set()
    repo.record_confirmation("dubbing-studio")
    assert breadth_allowance(repo, "dubbing-studio") is None


def test_certifications_survive_replay(tmp_path):
    store = EventStore(tmp_path / "events.log")
    TaskRepository(store).record_confirmation("alpha")
    assert "alpha" in TaskRepository.replay(EventStore(tmp_path / "events.log")).confirmed_projects()


def test_read_flagship(tmp_path):
    assert read_flagship(tmp_path) is None
    (tmp_path / "flagship").write_text("  dubbing-studio\n", encoding="utf-8")
    assert read_flagship(tmp_path) == "dubbing-studio"
    (tmp_path / "flagship").write_text("\n", encoding="utf-8")
    assert read_flagship(tmp_path) is None


def test_daemon_wires_the_breadth_cap():
    src = (ROOT / "control" / "daemon.py").read_text(encoding="utf-8")
    assert "read_flagship(state)" in src
    assert "breadth_allowance(repo, flagship)" in src


def test_flagship_is_human_only_configuration():
    """No source file may even reference the flagship path except the two sanctioned readers."""
    sanctioned = {Path("control/breadth.py"), Path("control/daemon.py")}
    # Runtime layers only: the charter is law-data and may NAME the flagship concept; what no
    # runtime code may do is touch the file.
    layers = ["core", "infra", "registry", "memory", "agents", "pa", "validation",
              "dispatch", "scheduling", "control", "edge", "selfdev"]
    offenders = []
    for layer in layers:
        for p in (ROOT / layer).rglob("*.py"):
            rel = p.relative_to(ROOT)
            if "flagship" in p.read_text(encoding="utf-8") and rel not in sanctioned:
                offenders.append(str(rel))
    assert not offenders, f"flagship referenced outside sanctioned readers: {offenders}"
