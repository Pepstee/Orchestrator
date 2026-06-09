"""Behavioural: the authenticity gate fails stubbed/placeholder/mock code and passes real code.

This is the gate that makes the cheapest path to green (stub it and move on) fail — so it is tested
adversarially: every species of fake must be caught, and legitimate interface code must NOT be.
"""
from __future__ import annotations

from pathlib import Path

from validation.authenticity import scan_authenticity


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_real_implementation_passes(tmp_path: Path):
    _write(tmp_path, "pkg/core.py",
           '"""Real module."""\n\n\ndef add(a: int, b: int) -> int:\n'
           '    """Return the sum of a and b."""\n    return a + b\n')
    r = scan_authenticity(str(tmp_path))
    assert r.passed and r.name == "authenticity"


def test_not_implemented_stub_fails(tmp_path: Path):
    _write(tmp_path, "pkg/core.py",
           "def compute(x):\n    raise NotImplementedError\n")
    r = scan_authenticity(str(tmp_path))
    assert not r.passed and "compute" in r.detail


def test_pass_only_body_fails(tmp_path: Path):
    _write(tmp_path, "pkg/core.py", "def handler(event):\n    pass\n")
    assert not scan_authenticity(str(tmp_path)).passed


def test_ellipsis_body_fails(tmp_path: Path):
    _write(tmp_path, "pkg/core.py", "def handler(event):\n    ...\n")
    assert not scan_authenticity(str(tmp_path)).passed


def test_todo_marker_fails(tmp_path: Path):
    _write(tmp_path, "pkg/core.py",
           "def f(x):\n    # TODO: finish this properly\n    return x\n")
    r = scan_authenticity(str(tmp_path))
    assert not r.passed and "TODO" in r.detail


def test_mock_class_in_shipped_code_fails(tmp_path: Path):
    _write(tmp_path, "pkg/client.py",
           "class MockPaymentClient:\n    def charge(self, amount):\n        return True\n")
    assert not scan_authenticity(str(tmp_path)).passed


def test_abstract_method_is_not_flagged(tmp_path: Path):
    _write(tmp_path, "pkg/base.py",
           "from abc import ABC, abstractmethod\n\n\nclass Store(ABC):\n"
           "    @abstractmethod\n    def get(self, key):\n        ...\n")
    assert scan_authenticity(str(tmp_path)).passed


def test_protocol_body_is_not_flagged(tmp_path: Path):
    _write(tmp_path, "pkg/iface.py",
           "from typing import Protocol\n\n\nclass Reader(Protocol):\n"
           "    def read(self) -> bytes: ...\n")
    assert scan_authenticity(str(tmp_path)).passed


def test_test_files_are_ignored(tmp_path: Path):
    # Mocks and stubs in the test suite are legitimate — only shipped code is scanned.
    _write(tmp_path, "tests/test_core.py",
           "class MockClient:\n    pass\n\n\ndef test_thing():\n    pass\n")
    assert scan_authenticity(str(tmp_path)).passed


def test_empty_project_passes_vacuously(tmp_path: Path):
    assert scan_authenticity(str(tmp_path)).passed
