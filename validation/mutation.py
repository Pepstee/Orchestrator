"""validation.mutation — real mutation testing as a completion gate (Quality Charter bar 3).

Proves the project's tests can actually *fail*. It introduces small, behaviour-changing edits
(mutants) into the shipped source one at a time, runs the suite against each, and requires that a
threshold fraction are *killed* (the suite goes red). A stub-plus-weak-test combination scores near
zero and fails the gate — so "make the tests pass" cannot be satisfied by tests that assert nothing.

Deterministic and dependency-free (stdlib `ast` + `subprocess`). Mutants are applied inside a throwaway
copy of the project, so the real tree is never left mutated; all writes route through infra.atomic_io
(law L7). Bounded by `max_mutants` and a per-run timeout (it runs the suite once per mutant).
"""
from __future__ import annotations

import ast
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

from infra.atomic_io import write_text_atomic
from validation.authenticity import _SKIP_DIRS, _is_test_file
from validation.gates import DEFAULT_TEST_COMMAND, GateResult, run_test_gate

# Comparison operators and their semantic opposite.
_CMP_FLIP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt,
             ast.Gt: ast.LtE, ast.LtE: ast.Gt}
# Arithmetic operators swapped within a pair.
_BIN_FLIP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult}


class _Mutator(ast.NodeTransformer):
    """Counts mutable sites in a fixed visit order; mutates exactly the one at `target` (or none)."""

    def __init__(self, target: int) -> None:
        self.target = target
        self.count = 0

    def _hit(self) -> bool:
        fire = self.count == self.target
        self.count += 1
        return fire

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        if len(node.ops) == 1 and type(node.ops[0]) in _CMP_FLIP and self._hit():
            node.ops = [_CMP_FLIP[type(node.ops[0])]()]
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if type(node.op) in _BIN_FLIP and self._hit():
            node.op = _BIN_FLIP[type(node.op)]()
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        if self._hit():
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, bool) and self._hit():
            node.value = not node.value
        return node

    def visit_Return(self, node: ast.Return) -> ast.AST:
        self.generic_visit(node)
        is_none = node.value is None or (
            isinstance(node.value, ast.Constant) and node.value.value is None
        )
        if node.value is not None and not is_none and self._hit():
            node.value = ast.Constant(value=None)
        return node


def _site_count(tree: ast.AST) -> int:
    m = _Mutator(target=-1)
    m.visit(deepcopy(tree))
    return m.count


def _mutate(tree: ast.AST, target: int) -> str:
    mutated = _Mutator(target).visit(deepcopy(tree))
    ast.fix_missing_locations(mutated)
    return ast.unparse(mutated)


def _shipped_sources(root: Path) -> list[Path]:
    out = []
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if _is_test_file(path.relative_to(root)):
            continue
        out.append(path)
    return out


def run_mutation_gate(
    project_dir: str,
    *,
    test_command: tuple[str, ...] = DEFAULT_TEST_COMMAND,
    max_mutants: int = 12,
    threshold: float = 0.8,
    timeout: int = 300,
) -> GateResult:
    """Mutate shipped source, run the suite per mutant, require killed/total >= threshold."""
    src_root = Path(project_dir)
    sources = _shipped_sources(src_root)
    # Build the list of (file, mutant_source) up to the budget, in a stable order.
    plan: list[tuple[Path, str]] = []
    for path in sources:
        if len(plan) >= max_mutants:
            break
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for target in range(_site_count(tree)):
            if len(plan) >= max_mutants:
                break
            plan.append((path.relative_to(src_root), _mutate(tree, target)))

    if not plan:
        return GateResult("mutation", True, "no mutable sites in shipped code (nothing to prove)")

    with tempfile.TemporaryDirectory(prefix="mutation-") as work:
        sandbox = Path(work) / "proj"
        shutil.copytree(src_root, sandbox,
                        ignore=shutil.ignore_patterns(*_SKIP_DIRS), dirs_exist_ok=True)
        killed = 0
        for rel, mutant_src in plan:
            target_file = sandbox / rel
            original = target_file.read_text(encoding="utf-8")
            write_text_atomic(target_file, mutant_src)
            try:
                result = run_test_gate(str(sandbox), command=test_command, timeout=timeout)
                if not result.passed:        # the suite noticed the mutant -> killed
                    killed += 1
            finally:
                write_text_atomic(target_file, original)   # restore before the next mutant

    score = killed / len(plan)
    passed = score >= threshold
    detail = f"mutation score {killed}/{len(plan)} = {score:.0%} (threshold {threshold:.0%})"
    return GateResult("mutation", passed, detail)
