"""BG-1 — the boot self-test gates dispatch; predicates explicit; no bypass path exists."""
from __future__ import annotations

from pathlib import Path

from charter.laws import Law
from control.self_test import ANCHOR, law_linked_test_paths, run_boot_self_test

ROOT = Path(__file__).resolve().parents[2]

GOOD_LAWS = [
    Law("PRIME", "anchor", "active", ANCHOR),
    Law("X1", "self", "active", "tests/architecture/test_boot_self_test.py"),
    Law("D1", "deferred laws need no check", "deferred", None),
]


def _ok_runner(_root, args):
    if "--collect-only" in args:
        return 0, "\n".join(p for p in args if p.endswith(".py"))
    return 0, "99 passed in 1.00s"


def test_green_with_real_charter_and_stub_runner():
    ok, detail = run_boot_self_test(ROOT, runner=_ok_runner)
    assert ok, detail


def test_red_when_anchor_absent_from_charter():
    laws = [Law("X1", "self", "active", "tests/architecture/test_boot_self_test.py")]
    ok, detail = run_boot_self_test(ROOT, laws=laws, runner=_ok_runner)
    assert not ok and "anchor" in detail


def test_red_when_a_law_linked_file_is_missing():
    laws = GOOD_LAWS + [Law("X2", "ghost", "active", "tests/architecture/test_does_not_exist.py")]
    ok, detail = run_boot_self_test(ROOT, laws=laws, runner=_ok_runner)
    assert not ok and "missing" in detail


def test_red_when_a_file_collects_nothing():
    def runner(_root, args):
        if "--collect-only" in args:
            return 0, ANCHOR  # the other law-linked path never appears in collection output
        return 0, "99 passed"
    ok, detail = run_boot_self_test(ROOT, laws=GOOD_LAWS, runner=runner)
    assert not ok and "collected no tests" in detail


def test_red_when_checks_fail():
    def runner(_root, args):
        if "--collect-only" in args:
            return 0, "\n".join(p for p in args if p.endswith(".py"))
        return 1, "1 failed, 98 passed"
    ok, detail = run_boot_self_test(ROOT, laws=GOOD_LAWS, runner=runner)
    assert not ok and "failed" in detail


def test_red_when_passed_count_below_law_linked_file_count():
    def runner(_root, args):
        if "--collect-only" in args:
            return 0, "\n".join(p for p in args if p.endswith(".py"))
        return 0, "1 passed"
    ok, detail = run_boot_self_test(ROOT, laws=GOOD_LAWS, runner=runner)
    assert not ok and "fewer checks" in detail


def test_charter_derived_paths_exist_on_disk():
    missing = [p for p in law_linked_test_paths() if not (ROOT / p).is_file()]
    assert not missing, f"the charter names checks that do not exist: {missing}"


def test_no_bypass_path_exists():
    self_test_src = (ROOT / "control" / "self_test.py").read_text(encoding="utf-8")
    assert "environ" not in self_test_src and "getenv" not in self_test_src, (
        "the self-test must not consult the environment — no skip switch may exist"
    )
    daemon_src = (ROOT / "control" / "daemon.py").read_text(encoding="utf-8")
    assert "run_boot_self_test(root)" in daemon_src, "daemon must call the boot self-test"
    acquire = daemon_src.index("pidlock.acquire")
    boot = daemon_src.index("run_boot_self_test(root)")
    serve_call = daemon_src.index("serve(repo")
    assert acquire < boot < serve_call, "self-test must gate dispatch: lock -> self-test -> serve"
