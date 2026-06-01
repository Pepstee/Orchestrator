"""Behavioural: one goal decomposes into a build -> judge graph that respects dependency gating."""
from __future__ import annotations

from pathlib import Path

from control.intake import submit_goal
from core.models import TaskStatus
from dispatch.dispatcher import is_ready
from dispatch.repository import TaskRepository
from infra.event_store import EventStore


def test_submit_goal_decomposes_into_build_and_judge(tmp_path: Path):
    store = str(tmp_path / "tasks.events.log")
    build_id, validate_id = submit_goal("Build a CLI", project="demo",
                                        acceptance=["runs"], store_path=store)
    repo = TaskRepository.replay(EventStore(store))
    build, val = repo.get(build_id), repo.get(validate_id)
    assert build.task_type == "implement" and build.status == TaskStatus.QUEUED
    assert val.task_type == "validate" and val.depends_on == [build_id]
    assert build.project == "demo" == val.project
    assert build.acceptance_criteria == ["runs"] == val.acceptance_criteria


def test_judge_is_gated_on_the_build(tmp_path: Path):
    store = str(tmp_path / "tasks.events.log")
    build_id, validate_id = submit_goal("Build", project="demo", store_path=store)
    repo = TaskRepository.replay(EventStore(store))
    assert is_ready(repo, repo.get(build_id))           # build has no prerequisites
    assert not is_ready(repo, repo.get(validate_id))    # judge waits for the build
