"""Behavioural: the overseer-evolved PA — consult, mining, curated promotion."""
from __future__ import annotations

from pathlib import Path

from pa.overseer import evolve
from pa.rules import Rule, consult, load_rules, save_rules


def test_consult_returns_only_active_rule_actions():
    rules = [
        Rule(id="1", pattern="git lock", action="requeue", status="active"),
        Rule(id="2", pattern="rate limit", action="escalate", status="candidate"),
    ]
    assert consult("error: git lock held", rules) == "requeue"   # active, matches
    assert consult("hit a rate limit", rules) is None            # matches but only a candidate
    assert consult("something else", rules) is None


def test_evolve_mines_recurring_cause_into_candidate():
    rules = evolve([], ["boom"] * 3, min_occurrences=3, evidence_threshold=5)
    assert len(rules) == 1
    assert rules[0].pattern == "boom" and rules[0].status == "candidate" and rules[0].action == "escalate"


def test_evolve_ignores_transient_causes():
    """Transient infra (restart-kills, rate limits) must NEVER become escalate rules — that mis-learning
    is what flooded the tray with phantom KeyboardInterrupt escalations."""
    causes = (["Traceback ... KeyboardInterrupt"] * 8
              + ["claude: 5-hour limit reached ∙ resets 5am"] * 8
              + ["real defect: missing module foo"] * 8)
    rules = evolve([], causes, min_occurrences=3, evidence_threshold=5)
    patterns = [r.pattern.lower() for r in rules]
    assert any("real defect" in p for p in patterns)                 # genuine recurring defect still mined
    assert not any("keyboardinterrupt" in p for p in patterns)       # transient excluded
    assert not any("5-hour limit" in p for p in patterns)


def test_evolve_ignores_one_offs():
    rules = evolve([], ["a", "b", "c"], min_occurrences=3)
    assert rules == []


def test_evolve_promotes_safe_candidate_at_threshold():
    rules = evolve([], ["stuck"] * 5, min_occurrences=3, evidence_threshold=5)
    assert rules[0].status == "active"          # safe action (escalate) + enough evidence -> promoted
    assert consult("got stuck again", rules) == "escalate"


def test_evolve_skips_causes_already_handled():
    existing = [Rule(id="x", pattern="known", action="escalate", status="active")]
    rules = evolve(existing, ["known failure"] * 9)
    assert len(rules) == 1   # already covered by the active rule -> no duplicate


def test_rules_round_trip(tmp_path: Path):
    path = tmp_path / "pa_rules.json"
    save_rules(path, [Rule(id="1", pattern="p", action="escalate", status="active", evidence=7)])
    loaded = load_rules(path)
    assert len(loaded) == 1 and loaded[0].pattern == "p" and loaded[0].evidence == 7
