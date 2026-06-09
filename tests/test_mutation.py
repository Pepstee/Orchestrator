"""Behavioural: real mutation testing — a strong suite kills mutants, a weak one fails the gate.

This is the anti-collusion gate: it proves the tests can actually fail, so 'green tests' written to
agree with a stub score near zero and are caught.
"""
from __future__ import annotations

from pathlib import Path

from validation.mutation import run_mutation_gate

SRC = "def add(a, b):\n    return a + b\n\n\ndef is_pos(x):\n    return x > 0\n"
STRONG_TEST = (
    "from calc import add, is_pos\n\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n    assert add(-1, 1) == 0\n\n\n"
    "def test_is_pos():\n    assert is_pos(3) is True\n    assert is_pos(-2) is False\n"
)


def _make(tmp_path: Path, test_body: str) -> None:
    (tmp_path / "calc.py").write_text(SRC, encoding="utf-8")
    (tmp_path / "test_calc.py").write_text(test_body, encoding="utf-8")


def test_strong_suite_kills_mutants(tmp_path: Path):
    _make(tmp_path, STRONG_TEST)
    r = run_mutation_gate(str(tmp_path), threshold=0.8)
    assert r.passed and r.name == "mutation", r.detail


def test_weak_suite_fails_the_gate(tmp_path: Path):
    _make(tmp_path, "def test_nothing():\n    assert True\n")
    r = run_mutation_gate(str(tmp_path), threshold=0.8)
    assert not r.passed and "mutation score" in r.detail


def test_no_mutable_sites_passes_vacuously(tmp_path: Path):
    (tmp_path / "const.py").write_text('NAME = "writing-assistant"\n', encoding="utf-8")
    assert run_mutation_gate(str(tmp_path)).passed


def test_real_tree_is_not_left_mutated(tmp_path: Path):
    _make(tmp_path, STRONG_TEST)
    run_mutation_gate(str(tmp_path), threshold=0.8)
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == SRC   # original restored
