"""pa.overseer — the overseer's PA evolution (curated, not autonomous).

The overseer mines the failure history for RECURRING causes and proposes deterministic candidate
rules (default action: escalate a known-recurring failure rather than burn the LLM on it again).
Candidates are promoted to active only when they accumulate enough evidence AND the action is safe
(non-code-modifying) — the curated-promotion gate. The overseer modifies the PA; the PA never
modifies itself, and anything riskier than a SAFE_ACTION stays a candidate for a human (law L9/F1).
"""
from __future__ import annotations

import hashlib
from collections import Counter

from infra.llm import is_transient_cause
from pa.rules import SAFE_ACTIONS, Rule, consult

# Transient infra conditions (restart-kills, rate-limit windows) are NOT defects and must never become
# escalate rules — that mis-learning is what floods the tray. Classified once in infra.llm.


def _rule_id(pattern: str) -> str:
    return "pa_" + hashlib.sha1(pattern.encode("utf-8")).hexdigest()[:10]


def evolve(
    rules: list[Rule],
    causes: list[str],
    *,
    min_occurrences: int = 3,
    evidence_threshold: int = 5,
) -> list[Rule]:
    """Mine recurring causes into candidate rules, bump evidence, and promote safe candidates at
    threshold. Mutates and returns `rules` (the caller persists). One-off failures are ignored."""
    counts = Counter(c.strip() for c in causes if c and c.strip() and not is_transient_cause(c))
    by_pattern = {r.pattern: r for r in rules}
    for cause, n in counts.items():
        if n < min_occurrences:
            continue                       # not recurring enough to be worth a rule
        if consult(cause, rules) is not None:
            continue                       # already handled by an active rule
        rule = by_pattern.get(cause)
        if rule is None:
            rule = Rule(id=_rule_id(cause), pattern=cause, action="escalate", status="candidate")
            rules.append(rule)
            by_pattern[cause] = rule
        rule.evidence = max(rule.evidence, n)
        if (rule.status == "candidate"
                and rule.action in SAFE_ACTIONS
                and rule.evidence >= evidence_threshold):
            rule.status = "active"         # curated promotion: safe action + enough evidence
    return rules
