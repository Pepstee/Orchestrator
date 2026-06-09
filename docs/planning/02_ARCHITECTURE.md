# Orchestrator v2 — 0.4 High-Level Architecture

*Tight and decision-dense. Synthesises 0.0 (vision) + 0.1 (lit review) + v1 lessons + the
charter laws. Each decision is an ADR with its rationale and the finding (Fn) or law (Ln)
that backs it. Requirements (0.2) and the feature catalogue (0.3) are largely derivable from
this and will be backfilled.*

---

## 1. The core control loop (one ordered pipeline)

```
GOAL  →  Intake funnel: scope-assist → prompt-gen → ARCHITECT proposes a
         confirmable FLOWCHART → you edit/confirm/decline
      →  confirmed flowchart becomes the GLOBAL TASK
      →  TASK MANAGER decomposes into a dependency-gated graph of small steps
      →  DISPATCH: pick ready step → estimate DIFFICULTY → route to the
         specialised agent + cheapest-sufficient model (cost cascade local→Claude)
      →  AGENT executes (payload in → AgentResult out)
            ├─ on failure → PA consult (deterministic fast-path: known fix / requeue)
            │                 └─ no rule → REASONER (depth matched to difficulty) →
            │                    failure ladder: repair → replan → escalate
            └─ on success → VALIDATION pipeline (layered, severity-ordered):
                 lint → type → security(bandit/semgrep, taint) → LLM-adjudication
                 → tests(augmented) → fragility → LLM-JUDGE (≠builder, tool-using)
      →  if automated gates pass → PROGRESSIVE-ASSURANCE loop (never idle):
         escalating cycles — edge-tests → mutation → adversarial → design-audit,
         budget-bounded, never regresses (any change re-passes all gates)
      →  COMPLETION CONTRACT (all four): works(tests) ∧ meets-intent(acceptance)
         ∧ correct&quality(judge) ∧ accepted(you)
      →  COMPLETION-AS-PROPOSAL: Judge + Architect emit one-tap next-move choices
         (from portfolio + aspirations memory)
      →  CURATED PROMOTION: episode→procedure into global memory (gated)

Cross-cutting, always on:
  • Everything is EVENT-SOURCED + TRACED (trace-id per goal through every span/verdict)
  • SIGNALS & QUERIES control bus → remotable (desktop now, mobile later)
  • BUDGET kill-switch + CUSUM drift guards + circuit breakers
  • OVERSEER (bounded) periodically: global sanity check + evolves the PA rules
```

**One difficulty signal, three consumers (the practical use of F4).** Estimate step
difficulty *once* (from fault taxonomy + slice calibration) and feed it to **(a)** model
routing (easy→local/Haiku+CoT; ambiguous→Sonnet+self-consistency; hard→Opus+ToT), **(b)**
validation intensity (mutation/adversarial tiers), and **(c)** the failure ladder / escalation
threshold. Don't build three difficulty estimators — compute it once, use it three ways.

---

## 2. Module layers (dependency points inward — L2, enforced by import-linter)

```
edge/        GUI (desktop) + remote control API; intake funnel; flowchart view;
             intervention view; one-tap proposal cards          ← depends on control/
control/     completion contract; autonomy + escalation; bounded overseer;
             signals&queries bus; budget governor               ← dispatch, validation, memory
dispatch/    decompose; dependency-gated queue (MLFQ aging);
  scheduling/  cost-cascade routing (classical floor + learned); difficulty estimator
validation/  layered gate pipeline; PRM step scoring; progressive-assurance loop
pa/          deterministic rule engine (consult/fast-path); overseer-evolved
agents/      specialised roster; payload→AgentResult; model from registry
memory/      episodic(local) + procedural(global, curated) + portfolio/aspirations;
             code-graph (graphify); slice calibration
infra/       durable event-sourced store + replay; atomic IO; sandbox; clock; tracing
core/        Goal · Task · AgentResult · Verdict · Event · the total state machine (L11)
             (pure; stdlib only)
registry/    single source of truth: agent→command, agent→model, task-type→agent (L1/L5)
selfdev/     DEFERRED behind a seam; import-linter forbids the core importing it (L9)
```

Nothing in `core/infra/registry` imports outward. `selfdev/` is quarantined and off by default.

---

## 3. Architecture Decision Records (concise)

| ADR | Decision | Why / backed by | Alternative rejected |
|-----|----------|------------------|----------------------|
| 01 | **Durable, event-sourced core with replay** (hybrid substrate) | resume-from-step, failure attribution, the data spine for learning/monitoring — F7, F12; v1's ad-hoc state caused the storms | v1-style scattered JSON + in-memory globals |
| 02 | **Signals & queries control bus** (commands injected as signals, live state read via queries) | makes control *remotable* (desktop+mobile) and decoupled from the GUI — A5, F7 | control logic embedded in the desktop app (can't remote) |
| 03 | **Layered validation, Builder≠Judge, tool-using judge** | judge bias/collusion is reproducible; validation is THE reliability lever — F5 | a single LLM judge gate |
| 04 | **4-gate completion: works ∧ intent ∧ quality ∧ accepted** | tests prove *works* not *safe*; the ~30% humans must judge is real — F2 | "tests pass → done" |
| 05 | **Progressive-assurance loop: never idle, escalating, budget-bounded, non-regressing** | converts idle time into assurance; green tests ≠ hardened (91% ASR) — F2, your idea | stop-and-wait for confirmation; or unbounded loop |
| 06 | **Memory: episodic-local / procedural-global via curated promotion, keyed by fault taxonomy** | quadruple anti-bleed defence — F6 | one global shared memory (v1 bleed) |
| 07 | **PA = deterministic rule engine, OVERSEER-evolved, human-led across the seam** | determinism + governed evolution, not an opaque autonomous loop — F1, F11, your correction | autonomous self-learning PA |
| 08 | **Cost-cascade routing (local→Claude) + classical floor + bugs-per-$ north-star + CUSUM drift guard** | the maturation curve is real but not automatic — F3, F8 | static confidence-threshold escalation; assume hybrid wins |
| 09 | **Structural security: least-privilege agents, JSON+schema input, dependency + taint scanning** | prompt defences are bypassable; model never trusted to refuse — F10 | prompt-based guardrails |
| 10 | **Self-modification deferred behind an import-linter-enforced seam; human-led when enabled** | mesa-optimisation / deceptive alignment unprovable to rule out — F1, F11 | build self-mod into v1 (v1's core instability) |
| 11 | **Single-source registries + enforcement toolchain (import-linter, LOC budget, registry-vs-runtime tests)** | v1's god-level rules drifted because unenforced — L1, L5, the prime directive | prose rules in a CLAUDE.md |
| 12 | **Difficulty estimated once → routing + assurance intensity + escalation** | one signal, three consumers; practical use of F4 | three separate difficulty heuristics |

---

## 4. Agent roster → layer/model (from the registry — L5)

Task Manager (decompose) · Architect (flowchart + proposals) · Builder (implement) ·
Reasoner (hard steps) · Validator/Judge (≠builder family) · Tester · Auditor (security/quality)
· Diagnoser · Explorer/Researcher · Reporter · Clarify · Fan-out · **Overseer (bounded:
global sanity + PA evolution)** · Monitor. Each resolves its model from the registry
(planner/architect→strong; builder→mid, cascading from local; tester/explorer→cheap;
judge→strong, different family from builder). Models: Claude now, provider-abstracted,
local-LLM as cascade tier-0 later.

---

## 5. What this leaves for later phases
- **0.2 Requirements / usability** — mostly derivable; backfill the non-functional targets
  (latency, the no-history monitoring cold-start, fatigue-throttled escalation volume).
- **0.3 Feature catalogue** — the §2 modules × §4 agents give the spine; prioritise v1-of-v2
  vs deferred against it.
- **0.5 Predictions / risk** — seed from lit-review §4 open problems (esp. "does orchestration
  beat one strong model?", maturation-curve regression, deceptive alignment).
- **0.6 Enforcement toolchain** — make ADR-11 concrete (the linters/tests/CI).
- The **confirmable flowchart** of this loop lives alongside this doc (editable).
