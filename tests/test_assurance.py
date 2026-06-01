"""Behavioural: the progressive-assurance loop is bounded, escalating, and non-regressing (L6)."""
from __future__ import annotations

from validation.assurance import default_tiers, run_assurance
from validation.gates import GateResult


def _tier(name: str, passed: bool = True):
    def t(_project_dir: str) -> GateResult:
        return GateResult(name=name, passed=passed)
    return t


def test_all_tiers_pass_is_fully_hardened():
    out = run_assurance("/tmp", [_tier("edge"), _tier("mutation"), _tier("adversarial")])
    assert out.passed and out.fully_hardened
    assert out.cycles_run == 3 and "fully hardened" in out.stopped_reason


def test_failing_tier_halts_without_running_the_rest():
    out = run_assurance("/tmp", [_tier("edge"), _tier("mutation", passed=False), _tier("adversarial")])
    assert not out.passed and not out.fully_hardened
    assert out.cycles_run == 2 and "issue found at 'mutation'" in out.stopped_reason


def test_user_intervention_halts_immediately():
    out = run_assurance("/tmp", [_tier("edge"), _tier("mutation")], should_stop=lambda: True)
    assert out.cycles_run == 0 and out.stopped_reason == "user intervened"


def test_max_cycles_caps_the_loop():
    out = run_assurance("/tmp", [_tier(str(i)) for i in range(10)], max_cycles=3)
    assert out.cycles_run == 3 and out.stopped_reason == "max cycles reached"


def test_budget_halts_the_loop():
    class _Gov:
        def should_stop(self):
            return (True, "cap reached")

    out = run_assurance("/tmp", [_tier("edge")], governor=_Gov())
    assert out.cycles_run == 0 and "budget" in out.stopped_reason


def test_default_tiers_is_a_nonempty_ladder():
    tiers = default_tiers()
    assert len(tiers) >= 1 and callable(tiers[0])
