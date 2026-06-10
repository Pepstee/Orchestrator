"""Behavioural: the acceptance-by-execution gate runs the real product and reads its output."""
from __future__ import annotations

from pathlib import Path

from validation.acceptance_exec import run_acceptance_gate


def test_declared_command_that_produces_output_passes(tmp_path: Path):
    r = run_acceptance_gate(str(tmp_path), command="echo deals found: 3")
    assert r.passed and "deals found: 3" in r.detail


def test_nonzero_exit_fails(tmp_path: Path):
    r = run_acceptance_gate(str(tmp_path), command="echo boom >&2; exit 1")
    assert not r.passed and "exited 1" in r.detail


def test_clean_exit_but_no_output_fails(tmp_path: Path):
    # The classic stub: it "runs" but does nothing real.
    r = run_acceptance_gate(str(tmp_path), command="true")
    assert not r.passed and "no output" in r.detail


def test_command_is_read_from_acceptance_file(tmp_path: Path):
    (tmp_path / "acceptance").write_text("# how to run the product\npython -c \"print('hi from product')\"\n",
                                         encoding="utf-8")
    r = run_acceptance_gate(str(tmp_path))
    assert r.passed and "hi from product" in r.detail


def test_no_declaration_fails(tmp_path: Path):
    # DG-6: under zero-touch there are no default-pass gates — a product that never declares
    # how to demonstrate itself is not demonstrated. (This was the flagship's actual state.)
    r = run_acceptance_gate(str(tmp_path))
    assert not r.passed and "declare" in r.detail


def test_mock_path_is_refused(tmp_path: Path):
    r = run_acceptance_gate(str(tmp_path), command="python acceptance.py sample.srt --mock")
    assert not r.passed and "mock" in r.detail


def test_every_declared_criterion_must_pass(tmp_path: Path):
    (tmp_path / "acceptance").write_text(
        "# two criteria, second fails\necho first ok\nexit 3\n", encoding="utf-8")
    r = run_acceptance_gate(str(tmp_path))
    assert not r.passed and "1/2" in r.detail


def test_all_criteria_passing_passes(tmp_path: Path):
    (tmp_path / "acceptance").write_text(
        "echo demo one\necho demo two\n", encoding="utf-8")
    r = run_acceptance_gate(str(tmp_path))
    assert r.passed and "2 criteria demonstrated" in r.detail


def test_runs_in_the_project_directory(tmp_path: Path):
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    r = run_acceptance_gate(str(tmp_path), command="ls")
    assert r.passed and "marker.txt" in r.detail   # cwd is the project dir
