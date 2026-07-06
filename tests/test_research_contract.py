"""Behavioural: the DV-3 evidence gate — deep research passes, shallow/boundary-violating fails."""
from __future__ import annotations

from validation.research_contract import ContractPolicy, check

# A bundle that clears the default floor: 3 Tier-2 + 1 Tier-3 sources, excerpts, corroboration.
_GOOD = {
    "question": "q",
    "findings": [
        {"claim": "A", "confidence": 0.9, "corroborations": 2, "sources": [
            {"url": "https://archive.org/x", "tier": 2, "excerpt": "found A"},
            {"url": "https://openalex.org/y", "tier": 2, "excerpt": "also A"},
        ]},
        {"claim": "B", "confidence": 0.8, "corroborations": 2, "sources": [
            {"url": "https://core.ac.uk/z", "tier": 2, "excerpt": "found B"},
            {"url": "https://obscure.example/q", "tier": 3, "excerpt": "primary doc B"},
        ]},
    ],
    "synthesis": "…",
    "gaps": [],
}


def test_good_bundle_passes():
    assert check(_GOOD).passed


def test_tier1_only_skim_fails():
    shallow = {"findings": [{"claim": "A", "confidence": 0.5, "sources": [
        {"url": "https://news.example/a", "tier": 1, "excerpt": "popular"},
        {"url": "https://blog.example/b", "tier": 1, "excerpt": "popular"},
    ]}]}
    r = check(shallow)
    assert not r.passed and any("depth floor" in x for x in r.reasons)


def test_link_dump_fails():
    dump = {k: v for k, v in _GOOD.items()}
    dump["findings"] = [dict(_GOOD["findings"][0])]
    dump["findings"][0] = {**dump["findings"][0],
                           "sources": [{"url": "https://archive.org/x", "tier": 2, "excerpt": ""}]}
    r = check(dump)
    assert not r.passed and any("link-dump" in x for x in r.reasons)


def test_uncorroborated_high_confidence_claim_fails():
    single = {"findings": [
        {"claim": "big claim", "confidence": 0.95, "sources": [
            {"url": "https://archive.org/x", "tier": 2, "excerpt": "one source only"},
        ]},
        # pad the depth floor so ONLY the corroboration rule can trip
        {"claim": "pad", "confidence": 0.1, "sources": [
            {"url": "https://openalex.org/y", "tier": 2, "excerpt": "e"},
            {"url": "https://core.ac.uk/z", "tier": 2, "excerpt": "e"},
            {"url": "https://obscure.example/q", "tier": 3, "excerpt": "e"},
        ]},
    ]}
    r = check(single)
    assert not r.passed and any("uncorroborated" in x for x in r.reasons)


def test_boundary_violation_rejects_bundle():
    blocked = {"findings": [{"claim": "A", "confidence": 0.5, "sources": [
        {"url": "https://paywalled.example/a", "tier": 2, "excerpt": "behind paywall", "access": "paywall"},
        {"url": "https://openalex.org/y", "tier": 2, "excerpt": "ok"},
        {"url": "https://core.ac.uk/z", "tier": 2, "excerpt": "ok"},
        {"url": "https://obscure.example/q", "tier": 3, "excerpt": "ok"},
    ]}]}
    r = check(blocked)
    assert not r.passed and any("boundary violation" in x for x in r.reasons)


def test_policy_is_tunable():
    # a stricter floor rejects what the default accepts
    strict = ContractPolicy(min_tier2=5, min_tier3=3)
    assert not check(_GOOD, strict).passed
