"""Behavioural: the four-gate completion contract + the concrete test gate."""
from __future__ import annotations

from pathlib import Path

from validation.gates import evaluate_completion, run_test_gate


def test_all_gates_pass_is_done():
    r = evaluate_completion({"tests": True, "acceptance": True, "judge": True,
                             "authenticity": True, "user": True})
    assert r.done and r.unmet == []


def test_missing_automated_gate_blocks_done():
    # a missing automated gate blocks completion; there is NO human gate anymore
    r = evaluate_completion({"tests": True, "acceptance": True, "judge": True})  # missing authenticity
    assert not r.done and "authenticity" in r.unmet and "user" not in r.unmet


def test_failed_gate_is_listed():
    r = evaluate_completion({"tests": True, "acceptance": False, "judge": True,
                             "authenticity": True, "user": True})
    assert not r.done and r.unmet == ["acceptance"]


def test_run_test_gate_passes(tmp_path: Path):
    r = run_test_gate(str(tmp_path), command=("python", "-c", "raise SystemExit(0)"))
    assert r.passed and r.name == "tests"


def test_run_test_gate_fails(tmp_path: Path):
    r = run_test_gate(str(tmp_path), command=("python", "-c", "raise SystemExit(1)"))
    assert not r.passed
