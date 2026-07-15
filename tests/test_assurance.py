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


# ── LLM hardening tiers (fakes; no tokens spent) ────────────────────────────────────────────
from infra.llm import LLMResult  # noqa: E402
from validation.assurance import hardening_tiers, llm_tier  # noqa: E402


def _llm(text: str, cost: float = 0.0):
    def call(provider, model, prompt, system=None, cwd=None, **_):
        return LLMResult(text=text, cost_usd=cost, model=model)
    return call


def test_llm_tier_passes_when_no_issue():
    t = llm_tier("mutation", "find gaps", provider="openai", model="codex",
                 call=_llm('{"issue_found": false, "detail": "solid"}'))
    r = t("/tmp")
    assert r.passed and r.name == "mutation"


def test_llm_tier_fails_on_found_issue():
    t = llm_tier("adversarial", "find flaws", provider="openai", model="codex",
                 call=_llm('{"issue_found": true, "detail": "off-by-one on empty input"}'))
    r = t("/tmp")
    assert not r.passed and "off-by-one" in r.detail


def test_llm_tier_charges_the_governor():
    class _Gov:
        def __init__(self):
            self.total = 0.0

        def charge(self, c):
            self.total += c

    gov = _Gov()
    llm_tier("m", "x", provider="claude", model="sonnet", governor=gov,
             call=_llm('{"issue_found": false}', cost=0.05))("/tmp")
    assert abs(gov.total - 0.05) < 1e-9


def test_llm_tier_error_is_non_blocking():
    def boom(*_a, **_k):
        raise RuntimeError("cli down")

    r = llm_tier("m", "x", provider="openai", model="codex", call=boom)("/tmp")
    assert r.passed and "skipped" in r.detail


def test_hardening_tiers_is_escalating_ladder():
    tiers = hardening_tiers()
    assert len(tiers) >= 3 and all(callable(t) for t in tiers)


# ---- severity-aware convergence (14 Jul: the binary adversarial verdict made 'fully hardened'
# unreachable — seven rounds each fixed a real finding, the adversary always had one more, and
# the era budget turned the treadmill into an abandonment) ----

def test_minor_finding_logs_but_does_not_block():
    t = llm_tier("adversarial", "find flaws", provider="openai", model="codex",
                 call=_llm('{"issue_found": true, "severity": "minor", '
                           '"detail": "docstring could mention the timeout"}'))
    r = t("/tmp")
    assert r.passed, "a minor finding must not block certification"
    assert "minor" in r.detail and "docstring" in r.detail


def test_blocker_and_major_still_block():
    for sev in ("blocker", "major"):
        t = llm_tier("adversarial", "find flaws", provider="openai", model="codex",
                     call=_llm('{"issue_found": true, "severity": "%s", '
                               '"detail": "replay bricks on UTF-8 BOM"}' % sev))
        r = t("/tmp")
        assert not r.passed, sev
        assert sev in r.detail


def test_missing_severity_defaults_to_blocking():
    # Old-format verdicts (no severity field) keep the conservative behaviour: they block.
    t = llm_tier("adversarial", "find flaws", provider="openai", model="codex",
                 call=_llm('{"issue_found": true, "detail": "path escape via ../"}'))
    r = t("/tmp")
    assert not r.passed and "major" in r.detail


def test_unknown_severity_treated_as_major():
    t = llm_tier("adversarial", "find flaws", provider="openai", model="codex",
                 call=_llm('{"issue_found": true, "severity": "catastrophic-ish", '
                           '"detail": "x"}'))
    r = t("/tmp")
    assert not r.passed
