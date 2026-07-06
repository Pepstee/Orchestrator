# Research Module Spec — deep tiered research (DV-3, DV-4, DV-6)

*Module spec for the second v3 capability. Implements DV-3 (research is deep or it fails), consumes
DV-4 (Fable 5 for synthesis, after the Overseer eval), obeys DV-6 (isolated module, fail-closed
seam-gate). Spec only — no code yet. Reads alongside 14 (KB): research writes its findings INTO the KB.*

---

## 1. Purpose & placement

A capability that **excavates** knowledge rather than skimming: fan-out search, iterative deepening
through the tier ladder, adversarial verification, and a synthesised, cited output — governed by an
**evidence contract** that fails shallow work.

**Placement (near-zero core footprint, per DV-6):**
- `agents/researcher.py` — the agent (an LLM agent with web tools + the strict output contract).
- `research/` — support module: the tool surface (search/fetch/archive/translate) and the evidence-bundle
  schema. Leaf-ish; imports `infra`/`core` only.
- `validation/research_contract.py` — the machine-check that gates a research task's completion (lives
  with the other gates, respects L2).
- `registry/agents.py` — **one entry**: `research` → `researcher`. This is the plug point; adding a
  task_type→agent here is the whole wiring change (the same seam the existing 5 agents use).

## 2. The tier ladder (from DV-3 §5, fixed)

- **Tier 1** — popular open web: mainstream sources, top results. Orientation & breadth.
- **Tier 2** — depth in the open: `archive.org`, open-access journals + APIs (OpenAlex, Semantic
  Scholar, CORE, Crossref), articles, and **non-Western / non-English sources** (with translation).
  Where the real, under-used depth lives; Fable 5's long-horizon synthesis is the tool for it.
- **Tier 3** — genuinely-public but obscure: low-traffic public pages, niche public datasets, primary
  documents nobody indexes. **Public only.**

**Hard boundary (non-negotiable):** no circumvention of paywalls, logins, robots/anti-bot, or any
access control. A source that requires it is **out of scope and rejected by the gate** (§5). Tier 1–2
plus *public* Tier 3 is the legitimate edge.

## 3. The evidence bundle (the contract's artefact)

Every research task emits one machine-checkable bundle:

```json
{
  "question": "…",
  "findings": [
    {
      "claim": "…",
      "confidence": 0.0-1.0,
      "corroborations": 2,
      "sources": [
        {"url": "…", "tier": 1|2|3, "excerpt": "extracted finding, not just a link", "accessed": "iso8601"}
      ]
    }
  ],
  "tier_coverage": {"tier1": n, "tier2": n, "tier3": n},
  "synthesis": "the cited report",
  "gaps": ["what could not be found / open questions"]
}
```

Every source carries an **extracted excerpt** (extraction, not link-dumping). Key claims carry
`corroborations` ≥ 2 from **independent** sources.

## 4. Depth mechanism (not skimming)

Mirrors the deep-research harness pattern:

1. **Fan-out** — multiple search angles per question, not one query.
2. **Iterative deepening** — follow citations and references Tier 1 → 2 → 3; stop when marginal
   sources stop adding.
3. **Adversarial verification** — a verification pass challenges each key claim; unresolved claims are
   demoted or moved to `gaps`. Verification uses a **cross-provider** check (D4/F5 — a stronger Claude
   is more reason to keep the checker outside the family), consistent with the Judge.
4. **Synthesis** — a cited report + the structured findings above.

## 5. The evidence contract — the gate (`validation/research_contract.py`)

A research task's completion is **gated** on its bundle passing:

- **Depth floor:** ≥ `MIN_TIER2` Tier-2 sources and ≥ `MIN_TIER3` Tier-3 sources (configurable; default
  e.g. 3 / 1) — a Tier-1-only bundle **fails**.
- **No link-dumping:** every source has a non-empty `excerpt`.
- **Corroboration:** every `claim` with confidence ≥ threshold has `corroborations` ≥ 2 independent.
- **Boundary:** any source flagged as paywalled/login/anti-bot ⇒ **reject** (boundary violation, §2).
- **Fail-closed:** a bundle that is missing, malformed, or below floor ⇒ the research task does **not**
  complete (fails with a self-explaining cause).

## 6. Integration with the KB (DV-2 — closes the loop)

Research findings are **written into the KB as `kind: research` entries** (the researcher's `AgentResult`
carries `knowledge` entries, recorded on the main thread exactly like §4 of the KB spec). Consequences:

- The **planner recalls** prior research before planning (no re-researching what's known).
- Findings enter the Overseer's `digest()` (DV-5).
- Research **satisfies the KB write-gate (H2)** like any other task — the two modules compose, they don't
  collide.
- Bundles are cached in the KB, so repeated questions don't re-fetch (cost control).

## 7. Seam-gates (DV-6 — minimal, mandatory, fail-closed)

| # | Hook | File | Fail-closed behaviour |
|---|------|------|-----------------------|
| H1 | **Register the agent.** `research` → `researcher` (+ command + model) | `registry/agents.py` | existing `test_registry_single_source` covers it |
| H2 | **Gate on completion.** A `research` task settles only if its bundle passes `research_contract.check()` | `validation/research_contract.py`, invoked at settle | shallow/boundary-violating research cannot be marked done |
| H3 | **Planner vocabulary.** The task_manager may emit `research` steps (one line in its allowed task_types + prompt) | `agents/task_manager.py` | if omitted, research simply never runs — so H3 is required for the capability to be *reachable* |
| H4 | **Boot self-test.** Assert the researcher is registered and the contract gate is wired | `control/self_test.py` | daemon refuses to dispatch if missing |

## 8. Model & cost (DV-4, and the economic layer)

- **Model:** Fable 5 for synthesis — but **after** the Overseer eval (locked order: Overseer first).
  Until then the researcher runs on the current default; the verifier stays **cross-provider**.
- **Cost:** deep research is token-heavy, so it runs **under the 09 economic layer** — a per-task attempt
  and token budget, and the burn-rate breaker. Research without a budget is how a weekly window vanishes;
  the module must never run un-metered.

## 9. Machine-checks (ship with the module)

- `test_contract_rejects_shallow` — Tier-1-only / below-floor bundle fails.
- `test_contract_rejects_linkdump` — a source without an excerpt fails.
- `test_contract_requires_corroboration` — a high-confidence claim with < 2 independent sources fails.
- `test_boundary_violation_rejected` — a paywalled/anti-bot source ⇒ reject.
- `test_research_writes_kb` — findings land as `kind: research` KB entries (DV-2 compose).
- boot self-test assertion (H4, fail-closed).
- layer-contract (import-linter) — `research`/`agents.researcher` respect L2.

## 10. Non-goals & open questions

- **Tier-3 reach is best-effort and public-only** — obscure public content is genuinely reachable, but
  coverage is not guaranteed; the bundle's `gaps` field records what couldn't be found (honesty over
  false completeness).
- **Translation fidelity** for non-English Tier-2/3 — flag low-confidence translations; don't launder
  uncertainty into a confident claim.
- **Tool surface reality** — Tier-2/3 access depends on which connectors the environment exposes
  (archive.org, OpenAlex/CORE, translation). List them as module dependencies; degrade gracefully to
  Tier 1–2 if a connector is absent (and say so in `gaps`).
- **Retrieval/quality-of-source scoring** beyond the tier tag is deferred (measure first).
- **Activation vs build:** buildable now; H2's gate and H1's Fable model both depend on the 09 spine and
  the DV-4 eval respectively — build the module early, wire the gate/model when they land.
