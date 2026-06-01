"""pa.rules — the deterministic Programmatic Architecture rule engine (the fast-path).

A rule maps a failure-cause pattern to a deterministic action (no LLM). Rules are durable and
EVOLVED BY THE OVERSEER (pa.overseer) — not autonomously — and promoted candidate -> active only via
a curated gate. consult() returns the action of the first ACTIVE rule matching a failure cause,
else None (the failure falls through to the LLM). As active rules accumulate, more known failures
are handled deterministically — the maturation curve, cheaper and more predictable over time.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from infra.atomic_io import read_json, write_json_atomic

# Non-code-modifying actions — safe for the overseer to auto-promote. Anything riskier
# (e.g. apply_fix) stays a candidate for human promotion (the self-mod seam, law L9/F1).
SAFE_ACTIONS = {"escalate", "requeue", "classify"}


@dataclass
class Rule:
    id: str
    pattern: str            # substring matched (case-insensitive) against a failure cause
    action: str             # deterministic handling: escalate / requeue / classify / ...
    status: str = "candidate"   # candidate | active
    evidence: int = 0


def matches(rule: Rule, cause: str) -> bool:
    return rule.pattern.lower() in (cause or "").lower()


def consult(cause: str, rules: list[Rule]) -> str | None:
    """Return the action of the first ACTIVE rule matching the cause, else None (fall through to LLM)."""
    for rule in rules:
        if rule.status == "active" and matches(rule, cause):
            return rule.action
    return None


def load_rules(path: Path | str) -> list[Rule]:
    data = read_json(path) or []
    return [Rule(**d) for d in data if isinstance(d, dict)]


def save_rules(path: Path | str, rules: list[Rule]) -> None:
    write_json_atomic(path, [asdict(r) for r in rules])
