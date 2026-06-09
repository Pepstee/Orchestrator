# Orchestrator v2 — Phase 0 Synthesis

*The capstone. Reads on its own as the case for v2; points to the deep component documents for
detail. This is the front matter and narrative of the Phase 0 "paper."*

---

## Abstract

v1 of the orchestrator is a self-modifying multi-agent system whose substrate works but whose
*discipline* did not hold: two weeks of patching left it unreliable, because its safety/autonomy
machinery reacted to its own state (storms, self-repair, model drift) and its excellent written
rules were never machine-enforced. v2 is a **full, clean rebuild informed by that experience**,
scoped to a different and sharper goal: a **GUI-first, fully-autonomous, code-first orchestrator
that reliably builds the user's projects and is trustworthy enough to leave running for days.**
Self-modification — the source of most v1 instability — is **deferred behind an enforced seam.**
A 34-report literature corpus was synthesised and found to **independently validate** the
intended architecture. The core thesis is a **maturation curve**: local-LLM migration +
overseer-evolved deterministic rules + rigorous validation make the system *cheaper, more
deterministic, and more reliable the longer it runs.* The prime directive — **a law without a
machine-check is a wish** — is what makes this rebuild different from the last.

## 1. Introduction — why rebuild, and what we keep

The instinct to rewrite was right, but for a sharper reason than "it's too big": **most of v1
exists to let the orchestrator safely modify itself** (developer/validator/policy/tiers/
worktrees/overseer), and that machinery is exactly what destabilised every run — yet it is
orthogonal to the real goal of *building the user's projects*. So v2 drops/defers
self-modification and scopes to reliable external-project orchestration.

What we **keep** (proven, ported as concepts, not files): file-based queue + atomic IO +
tombstones; the one-shot-subprocess agent contract; dependency-gated tasks; crash recovery;
the event log; the three-tier safety idea (returns with self-mod). What we **never repeat**:
the false-`no_heartbeat` storm, the overseer parse-loop, self-dev monopolising runs, model-
assignment drift, implicit cross-agent contracts, the `queued→blocked` bug, soft-kill zombies,
deliverable pollution, god-files, opaque failures. *(Full catalogue: `FOUNDATION.md`.)*

## 2. The thesis & the bet

**Thesis (maturation curve):** three forces compound — local-LLM migration (cheaper),
overseer-evolved PA (more deterministic, fewer LLM calls), and the validation gates (catch
regressions). The system should be architected so *getting better over time is the default
trajectory.* **It is real but not automatic** — it must be instrumented (`bugs-per-$`, CUSUM
drift, circuit breakers) or it regresses.

**Foundational bet (stated honestly):** a single strong model wins on one-shot tasks;
orchestration earns its keep only on **long-horizon, decomposable, validated** work. v2 bets on
*that* regime — and builds a falsification test (single-model-parity eval) so the bet stays
accountable to evidence, not faith. *(Full register: `04_PREDICTIONS_RISK.md`.)*

## 3. What the literature established (condensed)

34 reports (≈hundreds of papers, 16 domains) converged on twelve load-bearing findings — the
spine of the design. The five that most shape v2:
- **A green test suite is not a safety signal** (91% of test-passing patches hid vulns) → the
  4-gate contract and escalating assurance are necessities, not gold-plating.
- **Validation is the central reliability lever**, layered and **builder≠judge** → it is what
  makes cheap/local models safe to rely on.
- **Learned beats fixed, but keep a classical floor** → the maturation curve, safely.
- **Self-generated signal needs an external anchor** → tests/gates/curated-promotion are it;
  confirms deferring self-mod.
- **Trace-anchored observability is the precondition for everything** → one event schema serves
  dispatch, validation, learning, monitoring, and remote control.

The literature **maps one-to-one onto the desiderata** — the vision is where the state of the
art points. *(Full review + bibliography: `01_LITERATURE_REVIEW.md`.)*

## 4. The architecture (in brief)

One ordered pipeline: **goal → intake funnel (Architect proposes a confirmable flowchart) →
Global Task → decompose → dependency-gated dispatch (difficulty-routed, cost-cascaded) → agent
executes → PA fast-path or reasoner+failure-ladder → layered validation → progressive-assurance
loop → 4-gate completion → completion-as-proposal → curated promotion.** Cross-cutting:
event-sourced + traced; signals/queries control bus (remotable); budget kill-switch + CUSUM +
circuit breakers; a **bounded overseer** that does periodic global sanity checks *and* evolves
the PA rules. Twelve ADRs, each backed by a finding or law. A practical economy: **difficulty is
estimated once** and drives routing, assurance intensity, and escalation together.
*(Full architecture + ADRs + flowchart: `02_ARCHITECTURE.md`, `02_ARCHITECTURE_FLOW.mermaid`.)*

## 5. Scope

The **P0 milestone** is "the smallest thing already better than v1": a single goal running
end-to-end *reliably and legibly* with the enforcement spine in place from commit one. P1 adds
the funnel, assurance loop, cost routing, global memory, overseer, monitoring; P2 the richer GUI,
code-graph, local migration; **deferred:** self-modification, mobile app, multi-provider breadth.
*(Full prioritised catalogue: `03_FEATURE_CATALOGUE.md`.)*

## 6. How the rules stay true

The prime directive is executable: every charter law maps to a named CI/pre-commit/boot check
(import-linter layering, LOC budget, registry single-source + reported==chosen model, deliverable
purity, total state machine, bounded-loop, file-preservation, lifecycle smoke, self-mod-seam,
failure-cause schema), plus an **eval harness** (charter A2) and a **law-intake rule** — a new law
must ship with its check or the build fails. This is the structural fix for v1's drift.
*(Full toolchain: `05_ENFORCEMENT.md`.)*

## 7. Requirements & the go-live bar

Non-functional targets (reliability soak, no-surprise trust, legible failures, ~1s
responsiveness, calm escalation, non-dev approachability, bugs-per-$, cold-start safety) and the
signature flows (intake funnel, the 30-second "Da Nang" steering, intervene, approve, lifecycle).
**P0 go-live bar:** completes unattended through all four gates; survives a forced crash with
resume-from-step; kill-switch + budget cap halt spend; all enforcement green; project tree
pristine; a non-dev can launch a goal without instruction. *(Full spec: `06_REQUIREMENTS_USABILITY.md`.)*

## 8. The path from Phase 0 to build

1. **Sign off Phase 0** (this set of documents) and ratify the open decisions still pending from
   the charter: stack (assumed Python), v2 repo location/name, the LOC budget value, and the
   canonical `agent→model` registry.
2. **Stand up the foundation tooling** (the one remaining foundation task): the enforcement
   toolchain skeleton (import-linter + architecture tests + ruff gate) *first*, then graphify on
   the new repo, then the skill set the build will use — so the rules exist before the code they
   police.
3. **Build P0** against its go-live bar. Do not start any P1 feature until P0 meets the bar.
4. **Honour the kill-criteria** (0.5 §5) as go/no-go gates — accountable to evidence.

## 9. Document map (reading order)

| Doc | Sub-phase | What it is |
|-----|-----------|-----------|
| `FOUNDATION.md` | charter | the laws + v1 lessons + substrate port-list |
| `PHASE_0_PROGRAMME.md` | programme | the research-programme structure |
| `00_VISION_DESIDERATA.md` | 0.0 | the consolidated vision (what we're building & why) |
| `01_LITERATURE_REVIEW.md` | 0.1 | the research synthesis + annotated bibliography |
| `02_ARCHITECTURE.md` (+ `.mermaid`) | 0.4 | the architecture, 12 ADRs, the flowchart |
| `03_FEATURE_CATALOGUE.md` | 0.3 | prioritised features + the P0 milestone |
| `04_PREDICTIONS_RISK.md` | 0.5 | the bet, risk register, kill-criteria |
| `05_ENFORCEMENT.md` | 0.6 | the executable laws (toolchain) |
| `06_REQUIREMENTS_USABILITY.md` | 0.2 | non-functional targets + go-live bar |
| `07_PHASE0_SYNTHESIS.md` | 0.7 | **this document** |

---

*Phase 0 complete. The vision is research-validated, the architecture is decided and enforced by
construction, the bet is falsifiable, and the first milestone has a testable definition. The next
action is sign-off + the four open ratifications in §8, then the enforcement-tooling skeleton,
then P0.*
