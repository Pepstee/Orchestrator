"""validation.authenticity — the no-stub gate (Quality Charter bar 1).

A deterministic static scan of a project's *shipped* (non-test) Python source for the tells of
unfinished or faked work, which an autonomous builder reaches for as the cheapest path to a green
suite:

  - `raise NotImplementedError` in a concrete function,
  - TODO / FIXME / XXX / HACK / PLACEHOLDER / STUB markers,
  - `pass`-only or `...`-only function bodies,
  - `mock` / `fake` / `dummy` / `stub` identifiers defined in non-test code.

Making this a completion gate means the cheap path fails — the only way to pass is to implement the
work for real. It is stdlib-only (`ast` + a line regex), so it runs as a gate with no cost and no
network. It is deliberately conservative: abstract methods, `@overload` stubs, and `Protocol`/`ABC`
bodies are NOT flagged, so it does not punish legitimate interface declarations.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from validation.gates import GateResult

# Markers that betray unfinished work, matched as whole words anywhere in the source text.
_MARKER_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK|PLACEHOLDER|STUB)\b")
# Identifiers that betray a mock/fake shipped as if real, matched on def/class names.
_FAKE_NAME_RE = re.compile(r"(?i)\b(mock|fake|dummy|stub|placeholder)")
# Directories never scanned (deps, build artefacts, VCS, caches).
_SKIP_DIRS = {"__pycache__", ".venv", "venv", "env", "node_modules", ".git", "dist",
              "build", ".worktrees", ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages"}
_ABSTRACT_DECORATORS = ("abstract", "overload")
_ABSTRACT_BASES = {"Protocol", "ABC", "ABCMeta"}
_MAX_REPORTED = 12


def _is_test_file(rel: Path) -> bool:
    if any(part in ("tests", "test") for part in rel.parts):
        return True
    return rel.name.startswith("test_") or rel.name.endswith("_test.py")


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_abstract_fn(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(any(tok in _decorator_name(d) for tok in _ABSTRACT_DECORATORS)
               for d in node.decorator_list)


def _effective_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    """The function body with a leading docstring removed."""
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def _raises_notimplemented(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Raise) or stmt.exc is None:
        return False
    exc = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
    return _base_name(exc) == "NotImplementedError"


def _is_stub_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if the function has no real implementation (empty / pass / ... / bare NotImplementedError)."""
    body = _effective_body(node)
    if not body:
        return True
    if len(body) == 1:
        only = body[0]
        if isinstance(only, ast.Pass):
            return True
        if isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant) \
                and only.value.value is Ellipsis:
            return True
        if _raises_notimplemented(only):
            return True
    return False


def _scan_source(text: str, rel: Path) -> list[str]:
    """Return human-readable offence strings for one shipped source file."""
    offences: list[str] = []
    for m in _MARKER_RE.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        offences.append(f"{rel}:{line}: unfinished-work marker '{m.group(1)}'")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return offences + [f"{rel}: does not parse ({exc.msg})"]

    def visit(node: ast.AST, in_abstract_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                if _FAKE_NAME_RE.match(child.name):
                    offences.append(f"{rel}:{child.lineno}: mock/fake type '{child.name}' in shipped code")
                abstract = bool({_base_name(b) for b in child.bases} & _ABSTRACT_BASES)
                visit(child, abstract)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _FAKE_NAME_RE.match(child.name):
                    offences.append(f"{rel}:{child.lineno}: mock/fake function '{child.name}' in shipped code")
                if not in_abstract_class and not _is_abstract_fn(child) and _is_stub_body(child):
                    offences.append(f"{rel}:{child.lineno}: unimplemented function '{child.name}' (stub body)")
                visit(child, False)
            else:
                visit(child, in_abstract_class)

    visit(tree, False)
    return offences


def scan_authenticity(project_dir: str) -> GateResult:
    """Scan a project's shipped Python source for stubs/placeholders/mocks. Passed = none found."""
    root = Path(project_dir)
    offences: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root)
        if _is_test_file(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        offences.extend(_scan_source(text, rel))

    if not offences:
        return GateResult("authenticity", True, "no stubs, placeholders, or mocks in shipped code")
    shown = "; ".join(offences[:_MAX_REPORTED])
    more = "" if len(offences) <= _MAX_REPORTED else f" (+{len(offences) - _MAX_REPORTED} more)"
    return GateResult("authenticity", False, f"{len(offences)} authenticity issue(s): {shown}{more}")
