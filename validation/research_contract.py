"""validation.research_contract — the DV-3 evidence gate: research is deep or it fails.

A research task settles only if its evidence bundle passes this contract. The teeth:
  - depth floor  : a minimum of Tier-2 and Tier-3 sources (a Tier-1-only skim fails);
  - no link-dump : every source carries an extracted excerpt, not just a URL;
  - corroboration: every high-confidence claim has >= N INDEPENDENT sources (distinct domains);
  - boundary     : any non-public (paywalled / login / anti-bot) source rejects the whole bundle.

Pure/self-contained (imports stdlib only) so the gate is trivially testable and cheap. The agent that
PRODUCES bundles (agents.researcher) lives below this layer and never imports it (inward-only, L2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Source:
    url: str
    tier: int
    excerpt: str = ""
    accessed: str = ""
    access: str = "public"          # anything other than "public" is a boundary violation


@dataclass
class Finding:
    claim: str
    confidence: float = 0.0
    corroborations: int = 0
    sources: list[Source] = field(default_factory=list)


@dataclass
class EvidenceBundle:
    question: str = ""
    findings: list[Finding] = field(default_factory=list)
    synthesis: str = ""
    gaps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContractPolicy:
    min_tier2: int = 3
    min_tier3: int = 1
    confidence_threshold: float = 0.6
    min_corroborations: int = 2


DEFAULT_POLICY = ContractPolicy()


@dataclass
class ContractResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def _domain(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url or "")
    return m.group(1).lower() if m else (url or "").lower()


def parse(data: dict) -> EvidenceBundle:
    """Tolerant construction of a bundle from the agent's raw JSON dict."""
    findings = []
    for f in data.get("findings", []) or []:
        sources = [
            Source(
                url=str(s.get("url", "")),
                tier=int(s.get("tier", 1) or 1),
                excerpt=str(s.get("excerpt", "")),
                accessed=str(s.get("accessed", "")),
                access=str(s.get("access", "public")),
            )
            for s in (f.get("sources", []) or [])
        ]
        findings.append(Finding(
            claim=str(f.get("claim", "")),
            confidence=float(f.get("confidence", 0.0) or 0.0),
            corroborations=int(f.get("corroborations", 0) or 0),
            sources=sources,
        ))
    return EvidenceBundle(
        question=str(data.get("question", "")),
        findings=findings,
        synthesis=str(data.get("synthesis", "")),
        gaps=[str(g) for g in (data.get("gaps", []) or [])],
    )


def evaluate(bundle: EvidenceBundle, policy: ContractPolicy = DEFAULT_POLICY) -> ContractResult:
    reasons: list[str] = []
    all_sources = [s for f in bundle.findings for s in f.sources]

    if not bundle.findings:
        reasons.append("no findings")
    if not all_sources:
        reasons.append("no sources")
    if any(not s.excerpt.strip() for s in all_sources):
        reasons.append("link-dump: a source has no extracted excerpt")
    if any(s.access != "public" for s in all_sources):
        reasons.append("boundary violation: a non-public (paywall/login/anti-bot) source is present")

    t2 = sum(1 for s in all_sources if s.tier == 2)
    t3 = sum(1 for s in all_sources if s.tier == 3)
    if t2 < policy.min_tier2:
        reasons.append(f"depth floor: {t2} Tier-2 sources < required {policy.min_tier2}")
    if t3 < policy.min_tier3:
        reasons.append(f"depth floor: {t3} Tier-3 sources < required {policy.min_tier3}")

    for f in bundle.findings:
        if f.confidence >= policy.confidence_threshold:
            independent = {_domain(s.url) for s in f.sources if s.url}
            if len(independent) < policy.min_corroborations:
                reasons.append(
                    f"uncorroborated: claim {f.claim[:48]!r} has {len(independent)} independent "
                    f"source(s) < required {policy.min_corroborations}"
                )
    return ContractResult(passed=not reasons, reasons=reasons)


def check(data: dict, policy: ContractPolicy = DEFAULT_POLICY) -> ContractResult:
    """Convenience: parse a raw bundle dict and evaluate it in one call (what settle() will invoke)."""
    return evaluate(parse(data), policy)
