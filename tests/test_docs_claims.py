"""Docs-drift checks — the constitution's own idiom applied to prose (spec 17 §10 backport).

"A law without a machine-check is a wish" — and the July drift proved documentation is no
exception: four documents (CLAUDE.md, the Quality Charter, the handoff, planning/09 commentary)
described a human confirmation gate that DG-2 had removed from the code. These tests pin the
handful of greppable ground truths whose drift misleads a cold-start agent, so the next
divergence between code and prose turns the build red instead of surviving two document layers.

Deliberately small and robust: code-truth assertions plus a few phrase checks. No brittle
numbers (test counts, LOC) — claims like that were removed from the docs rather than policed.
"""
from __future__ import annotations

from pathlib import Path

from validation.gates import REQUIRED_GATES

ROOT = Path(__file__).resolve().parents[1]


def test_required_gates_are_the_four_automated_gates():
    # DG-2 zero-touch: completion is decided entirely by automated gates.
    assert set(REQUIRED_GATES) == {"tests", "acceptance", "judge", "authenticity"}
    assert "user" not in REQUIRED_GATES


def test_claude_md_does_not_claim_a_user_gate():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "∧ user" not in text, "CLAUDE.md reintroduced the retired user gate (DG-2)"
    assert "you confirm (the 4th gate)" not in text
    assert "SELF-CERTIFIED" in text, "CLAUDE.md should state the DG-2 self-certification model"


def test_quality_charter_matches_zero_touch():
    text = (ROOT / "docs" / "QUALITY_CHARTER.md").read_text(encoding="utf-8")
    assert "You are the final gate" not in text, "Charter bar 7 reverted to the pre-DG-2 wording"
    assert "self-issued" in text or "self-certif" in text.lower()


def test_claude_md_carries_no_brittle_test_count():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "~207 tests" not in text, "stale test count reintroduced — keep counts out of prose"


def test_handoff_read_order_paths_exist():
    # The handoff's read order once pointed at a file the fence had eaten (OPERATING_GUIDE.md).
    # Every docs/ path named in HANDOFF.md must exist on disk.
    handoff = (ROOT / "docs" / "HANDOFF.md").read_text(encoding="utf-8")
    for token in handoff.replace("`", " ").split():
        if token.startswith("docs/") and token.endswith(".md"):
            assert (ROOT / token).exists(), f"HANDOFF.md references missing file: {token}"
