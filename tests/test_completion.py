"""Behavioural: the four-gate completion contract + the concrete test gate."""
from __future__ import annotations

from pathlib import Path

from validation.gates import evaluate_completion, run_test_gate


def test_all_four_gates_pass_is_done():
    r = evaluate_completion({"tests": True, "acceptance": True, "judge": True, "user": True})
    assert r.done and r.unmet == []


def test_missing_user_gate_blocks_done():
    # all automated gates pass, but no user confirmation yet -> not done (two-tier contract)
    r = evaluate_completion({"tests": True, "acceptance": True, "judge": True})
    assert not r.done and "user" in r.unmet


def test_failed_gate_is_listed():
    r = evaluate_completion({"tests": True, "acceptance": False, "judge": True, "user": True})
    assert not r.done and r.unmet == ["acceptance"]


def test_run_test_gate_passes(tmp_path: Path):
    r = run_test_gate(str(tmp_path), command=("python", "-c", "raise SystemExit(0)"))
    assert r.passed and r.name == "tests"


def test_run_test_gate_fails(tmp_path: Path):
    r = run_test_gate(str(tmp_path), command=("python", "-c", "raise SystemExit(1)"))
    assert not r.passed
