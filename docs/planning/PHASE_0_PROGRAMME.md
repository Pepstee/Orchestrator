# Orchestrator v2 — Phase 0: Research & Architecture Programme

**What this is.** Phase 0 is treated as an academic paper, not a checklist. It is a
research-and-scoping effort that produces a high-level architecture, a complete
feature/usability scope, and a set of predictions — all grounded in (a) a 34-report
research corpus and (b) the battle-hardened experience of v1. **No product code is
written until Phase 0 ships and is signed off.**

**Why this rigour.** v1 failed not at the substrate but at discipline and scope: it
accreted overlapping paradigms and unenforced rules over two weeks of patching. v2
earns the right to exist only by being designed once, deliberately, from evidence.

---

## 1. Phase 0 sub-phases (the programme)

Each sub-phase has explicit inputs, a method, a deliverable, and an exit criterion.
They are sequenced; later phases consume earlier outputs.

| # | Sub-phase | Inputs | Method | Deliverable | Exit criterion |
|---|-----------|--------|--------|-------------|----------------|
| **0.1** | **Bibliography Analysis** | 34 research reports + their cited papers; v1 lessons | Per-domain synthesis; extract findings, techniques (foundational vs tactical), design implications, citations | **Literature Review** + **Annotated Bibliography** | Every design domain has a synthesised findings set with citations |
| **0.2** | **Problem Framing & Requirements** | 0.1 + v1 retrospective | Define problem precisely; functional + non-functional requirements; **usability goals** | **Requirements & Usability Spec** | Each requirement traceable to research or v1 evidence |
| **0.3** | **Feature Discovery & Discussion** | 0.1, 0.2 | Exhaustive feature inventory; each feature justified, prioritised, v1-vs-deferred, mapped to a module | **Feature Catalogue** | No feature without a justification and a home module |
| **0.4** | **Architecture Decision** | 0.1–0.3 | Synthesise into a high-level architecture; one **ADR per major decision**, each citing the research that justifies it | **Architecture Spec + ADRs** | Every major decision has an ADR with alternatives-rejected and citations |
| **0.5** | **Risk, Predictions & Open Problems** | 0.1–0.4 | Predict failure modes, scaling limits, research gaps; mark cutting-edge-but-unproven bets and their hedges | **Foresight & Risk Register** | Each high bet has a hedge; each known v1 failure has a structural defence |
| **0.6** | **Laws & Enforcement** | 0.4 | The inviolable laws + the machine-checks that enforce them | **Charter (drafted)** + **Enforcement Toolchain Spec** | Every law has an enforcement mechanism |
| **0.7** | **Synthesis** | all | Assemble into the Phase 0 paper | **The Phase 0 document** (abstract → references) | Reads as a coherent, citable whole |

**Output shape (the "paper"):** Abstract · Introduction (problem + v1 retrospective) ·
Related Work (the literature review) · Requirements & Usability · Proposed Architecture
(+ ADRs) · Discussion & Predictions · Threats to Validity / Risk Register · References.

---

## 2. The corpus → design-domain map (bibliography spine)

The 34 reports cluster into the system's design domains. 0.1 synthesises each cluster.

| Domain | Reports (n) | Design questions it answers |
|--------|:-----------:|------------------------------|
| **Multi-agent orchestration & dispatch** | 4 | dispatch patterns, agent coordination, failure points, evolving/centralised scheduling (ReAct, AutoGen, AgentBench, evolving orchestration) |
| **Validation & LLM-as-judge** | 4 | how to validate generated work/repairs; judge reliability, bias, calibration |
| **Reasoning engine** | 2 | producing/selecting multiple reasoning paths; reasoning-for-repair |
| **Knowledge accumulation & learning from experience** | 3 | long-horizon memory, statistics, learning across runs |
| **Code repair & repair-spawning** | 2 | repair generation, recursive repair-task topologies |
| **Scheduling, queueing & scale** | 3 | scheduling under load, queue management, thousands of tasks |
| **Cost / LLM-call efficiency** | 1 | per-call economics, when each call must justify itself |
| **Self-improvement / self-modification** | 2 | self-improving orchestrators, fine-tuning/self-editing systems (the *deferred* domain) |
| **Failure classification & taxonomy** | 2 | classifying failures, many-failure-mode systems |
| **Code-structure understanding** | 1 | code comprehension / graph representations (graphify-relevant) |
| **Tool-calling agents** | 1 | external tool use (git, etc.), tool-failure handling |
| **Proactive monitoring** | 1 | anticipatory monitoring/alerting |
| **Test generation & mutation testing (H2, H3)** | 2 | automated test generation, mutation-based validation |
| **Security (I1 injection, I2 supply chain, I3 adversarial)** | 3 | prompt injection/jailbreak, supply-chain, adversarial robustness for code |
| **Delegation & autonomy calibration; explainability (K1, K2)** | 2 | when to act vs escalate; explainable agent decisions |
| **Efficiency frontier (self-play, speculative/early-exit)** | 2 | self-play training signal; speculative decoding / early exit |

*(≈34 reports; exact assignments finalised when 0.1 opens each file.)*

---

## 3. Method for 0.1 (bibliography analysis)

Per domain, a focused synthesis extracting four things, kept citation-anchored:
1. **Core findings** — what the literature establishes.
2. **Techniques** — tagged *foundational* (shapes the design) vs *tactical* (directly
   implementable), each with the source paper.
3. **Design implications for v2** — the concrete decision each finding informs.
4. **Open problems / disagreements** — where the research is unsettled (feeds 0.5).

Executed as parallel domain reads (the corpus is large), then merged into one Related
Work section + an annotated bibliography. Volume warning: this is the heaviest sub-phase
— a real literature review across ~16 domains and hundreds of cited papers.

---

## 4. Decisions needed before I run 0.1

1. **Sign off the sub-phase structure** above (or adjust the breakdown).
2. **Depth/length target.** Academic-paper scale — confirm rough ambition (e.g. a
   ~40–60pp Phase 0 document, lit review ~15–20pp), so I calibrate the synthesis.
3. **Green-light the heavy synthesis.** 0.1 is a large parallel read of all 34 reports.
4. **Still-open charter decisions** (carry over): stack (assumed Python), v2 repo
   location/name, LOC budget, ratifying the agent→model registry.
```
