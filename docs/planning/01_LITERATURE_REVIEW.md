# Orchestrator v2 — 0.1 Literature Review (Related Work)

*Synthesis of the 34-report research corpus (≈300–500 cited papers across 16 design
domains), read through the consolidated 0.0 vision. The headline result: the literature
independently arrives at the mechanisms 0.0 specified — the 4-gate completion contract,
builder≠judge separation, curated promotion, risk-tiered autonomy, and the maturation
curve. The vision is research-validated, not speculative.*

---

## 0. Corpus & method

34 deep-research reports, each posing a design question and summarising 10–15 named papers
(core insight, technical pattern, extractable technique, foundational/tactical tag). Read in
five domain batches: (1) orchestration/dispatch/scheduling/cost; (2) validation/LLM-judge/
repair; (3) reasoning/memory/learning/failure-taxonomy; (4) self-improvement/code-graph/
tools/monitoring/efficiency; (5) testing/security/delegation/explainability. Techniques are
tagged **[F]** foundational (shapes the design) or **[T]** tactical (directly implementable).

---

## 1. Cross-cutting synthesis — the twelve load-bearing findings

These recurred across multiple independent batches. They are the spine of the v2 architecture.

**F1 — Self-generated signal is only safe when anchored to an external verifier.**
Constitutional AI, SPIN, SELF-REFINE, RouteLLM *all* depend on an external anchor (a
constitution, a locked benchmark, tests, preference labels). The single most important rule
in the corpus: **never let a self-improvement loop close on itself.** v2's deterministic
gates + tests + curated promotion *are* that anchor — and this is the deep reason
self-modification stays deferred.

**F2 — A green test suite is NOT a safety signal.** SWExploit produces patches that pass
all tests yet hide vulnerabilities at a **91% success rate**; INSEC injects insecure-but-
functional code; HumanEval+ shows pass@k drops **15–29%** when tests are augmented ~80×.
This *kills* any "tests pass → auto-apply" design and is the empirical justification for the
4-gate contract and for escalating past tests into mutation + adversarial probing.

**F3 — Learned/adaptive beats fixed — but always keep a classical/deterministic floor.**
Adaptive dispatch (Puppeteer), learned scheduling, and learned routing (RouteLLM, PILOT) all
beat static rules on cost/quality — yet every result pairs the learned policy with a
classical safety floor (SPT/EDD, FrugalGPT cascade, classical planner). This *is* the
maturation curve: start deterministic/safe, layer learned behaviour as data accrues, never
remove the floor.

**F4 — Match reasoning and validation depth to difficulty — on a ladder.** Plain CoT for
easy/local faults; self-consistency when one bad path dominates; Tree/Graph-of-Thoughts for
ambiguous/repeatedly-failing steps; process-reward models to localise the *first wrong step*
and decide repair-vs-replan-vs-escalate. The reasoning engine should *escalate its own
structure* exactly where the failure ladder escalates.

**F5 — Validation is the central reliability lever; it is layered, severity-ordered, and
builder≠judge.** Pipeline: lint → semantic/type → security (bandit/semgrep) → LLM
adjudication → augmented tests → fragility tests → LLM-judge → user. The judge must be a
*different model family* than the builder (self-enhancement bias is reproducible), should
*run tools* as part of its verdict (Agent-as-a-Judge), and must be continuously
calibrated against a self-generated known-correct/known-wrong pair set. Strong validation is
precisely what makes relying on cheaper/local builders safe.

**F6 — Memory: episodic-local / procedural-global, via curated promotion keyed by fault
taxonomy.** Episodes carry repo/framework/test context and must never cross projects; only
abstracted, test-verified *procedures* are globally retrievable, and retrieval is
category-aware so an unrelated project's quirk is structurally unreachable. Promotion
requires generalisation evidence (recurs across ≥N episodes, calibrated on its slice, passes
a held-out check, still passes current tests). Cross-project bleed is defended four
independent ways: partition + verified-promotion + category-scoped retrieval + slice-local
calibration.

**F7 — Trace-anchored observability is the precondition for everything else.** One structured,
intent-tagged, evidence-bearing event/trace schema (trace-ID propagated through every
subprocess and every gate verdict, with judge/PRM scores + margins logged) simultaneously
serves: debugging, failure attribution across the ladder, judge/PRM recalibration,
episode→procedure distillation, drift monitoring, *and* the signals/queries control plane.
Always tail-sample every failure and escalation. Without this you cannot tell a bad-builder
move from a mis-scoring judge from a doomed plan — and therefore cannot trust the gates.

**F8 — The maturation curve is real but NOT automatic — instrument it or it regresses.**
A naive Claude+local hybrid can fix *fewer* bugs per dollar than cheap-only; the win depends
on the local model's success rate and the escalation fraction. v2 must make
**bugs-fixed-per-dollar (≈ fixes-per-token)** its north-star metric, tune the escalation
fraction from data, and guard slow drift with **CUSUM** charts + locked-benchmark-vs-canary
divergence + automated rollback circuit breakers.

**F9 — Risk-tier everything, through one policy tier.** Mutation-score targets (security
90–95% / logic 80–90% / style optional), adversarial-probing intensity, and auto-apply
confidence thresholds (≈0.95 / 0.75 / 0.50) all independently land on risk tiers. Unify them:
a file's policy tier should simultaneously set its assurance intensity *and* its delegation
threshold. (The literature validates the existing tier-3≥0.9 / tier-2≥0.7 bands.)

**F10 — The autonomous security posture must be structural, not prompt-based.** Prompt/safety-
training defences are brittle and bypassable; untrusted task descriptions get executed as
instructions (indirect injection). Defence must rest on deterministic, non-LLM layers:
structured-JSON input + schema, data/instruction context partitioning, per-agent
least-privilege (read-only reasoning/validator, write-diffs-only builder, no arbitrary
subprocesses), dependency scanning (OSV/CVE, bandit/semgrep), and an enforced charter that
survives injection. **The model is never trusted to refuse.** Three vectors (inference-time
injection, runtime supply-chain, training-time poisoning) need three distinct gates.

**F11 — Self-modification stays deferred; the self-learning PA is its safe shadow.** Builder
self-fine-tuning (SPIN) and core-logic self-edits are where mesa-optimisation, deceptive
alignment, and data-poisoning bite (100 poisoned examples implant a backdoor). The *safe*
version is the self-learning PA: deterministic handlers for *known* errors, promoted by an
external curated gate — circuit breakers, tool-failure handlers, SPC alert rules,
cost-benefit escalation rules are all deterministic and adoptable now. The hard rule "never
let the system rewrite its own policy" is the correct, literature-justified seam.

**F12 — v2's own artifacts already are the training & monitoring corpus.** Validator critiques
→ Reflexion-style memory + PA handlers + SPIN negatives; applied/rejected changes → labelled
trajectories; tool-call logs → SPC charts + escalation features. The reject→critique→retry
loop produces, for free, the data every other mechanism needs. The work is *plumbing existing
signals*, not collecting new data.

---

## 2. Domain findings

### 2.1 Orchestration, dispatch, scheduling, scale, cost
- **Dispatch:** the load-bearing decomposition is **dispatch / validation / retry** as separate
  concerns (ReAct, AutoGen). Learned adaptive supervision (Puppeteer, NeurIPS 2025) beats fixed
  workflows **[F]**; AgentBench shows you must score *trajectory* quality, not just endpoints.
- **Hierarchy:** dominant failure is **over-delegation from a wrong capability model**, and
  **silent failure** (continuing on a false premise) is more dangerous than noisy failure —
  always verify outcomes, never trust a role label **[F]** (AgentOrchestra, Director, ToM,
  "Which Agent Causes Task Failures and When?").
- **Communication:** treat messages as **speech acts with explicit intent** + typed content +
  evidence + confidence (FIPA, ChatDev's artifact-gated "communicative dehallucination",
  AgentScope) — this *is* the event-log + signals/queries schema **[F]**.
- **Planning under uncertainty:** use the LLM to *compile* problems for a sound planner
  (LLM+P), decompose + replan from feedback (SayPlan, DEPS), and **replan from current verified
  world-state, never the stale original** (cancel stale branches — a bug may already be fixed).
- **Queueing:** MLFQ **aging** prevents starvation; hybrid **learned-predictor + classical SPT/
  EDD floor**; demote/preempt on overrun → feeds the budget kill-switch and failure ladder.
- **Monitoring at scale:** no detector dominates; use **trend-aware** methods (STL+EWMA, 2–4 wks
  history) with adaptive thresholds; monitor metrics *jointly* (correlated spikes = real).
- **Cost routing:** the **FrugalGPT cascade + quality-checker** unifies cost-routing, the
  completion gate, and local-migration (local = tier-0) into one mechanism **[F]**; cap retry
  tokens; budget is structurally bounded because token cost is exponential (Token Economics).

### 2.2 Validation, LLM-judge, code repair
- LLM judging is viable (>80% human agreement) **only with active bias mitigation** (position/
  verbosity/self-enhancement) and is fooled by **fluent-but-wrong** code (JudgeBench, MT-Bench,
  G-Eval). **Builder≠Judge** and an **Agent-as-a-Judge** that runs tools are hard rules **[F]**.
- Automated review: ~70% of PR issues are automatable, ~30% (architecture/business-logic/
  scalability) need humans — the **empirical justification for the "user confirms" gate**; track
  **Key-Bug-Inclusion AND false-alarm-rate** as a pair; feed repo context, not bare diffs.
- **Process-reward models** score intermediate steps, localise the first wrong step, and tell
  the failure ladder *which rung* to use; spend verifier compute **adaptively** (Snell) — which
  is what makes weak/local builders affordable to validate.
- **Static analysis** catches a bug class tests miss (scope/type/taint) but misses 47–80% of
  real vulns — use it as a high-recall filter with the **LLM as alert-adjudicator**, not detector.
- **Test insufficiency is the core trap** (HumanEval+/EvalPlus, EvoEval overfitting, CodeCrash
  fragility) — augment tests, perturb, and score correctness *and* maintainability separately.
- **Tracing** (Dapper/OpenTelemetry/MLflow): trace-ID per goal through every span; tail-sample
  all failures/escalations; log judge/PRM scores — the substrate for attribution + recalibration.

### 2.3 Reasoning, memory, learning, failure taxonomy
- **Reasoning tiers by difficulty** (CoT → Self-Consistency → ToT → GoT), with an explicit
  per-step drift gate; add steps only when each has a distinct verification target.
- **Calibration** is slice-local and degrades under domain shift; per-agent targets (builder
  exploratory, validator conservative); calibrated confidence drives act/retry/escalate — and
  **calibration-on-slice is itself an anti-bleed gate for promotion** **[F]**.
- **Retrieval (RAG)** helps only when targeted: **category-aware retrieval** (ReCode, DSrepair)
  cuts cost 3–4×; freshness (decay, re-test on reuse, version on API change) is the promotion
  lifeblood; retrieval can *hurt* — gate on relevance.
- **Episodic vs procedural memory** (Generative Agents reflection loop, REMEMBERER RLEM):
  share *procedural* across projects, keep *episodic* project-local — the exact anti-bleed
  design **[F]**; learn from failures too, not just successes.
- **Context saturation:** "lost in the middle" → place curated learnings + live failure-context
  at prompt *edges*; MemGPT hot/cold paging; **selective forgetting is a first-class competency**.
- **Failure resilience:** chaos-engineering + a four-class fault model (transient/permanent/
  resource/race); **silent corruption is hardest** — caught only by output validation, not error
  codes. Lineage-guided injection on output-affecting paths.
- **Defect taxonomy** (Beizer severity + CWE IDs + Defects4J control/data-flow classes): tag
  every episode/procedure with fault-class + severity → the retrieval key, the promotion
  partition, and a difficulty prior for reasoning depth.

### 2.4 Self-improvement, code-graph, tools, monitoring, efficiency
- **Self-improvement** (Constitutional AI, SELF-REFINE, Reflexion): a versioned constitution as
  the critique reference; persist critiques as memory; **anti-gaming requires external verifiers**
  — your charter + gates already are this.
- **Self-modification risks** (mesa-optimisation, deceptive alignment, SWExploit): cannot be
  fully detected pre-production → keep core self-edit deferred; adopt **automated circuit
  breakers** (confidence-drop / pass-rate-drop / validator-disagreement → rollback) now.
- **Code-graph** (Code Property Graphs, Joern fuzzy-parse + incremental passes, Graph4Code):
  give agents a pre-computed, indexed graph; **query for structural facts, reason for semantics**;
  taint analysis becomes a deterministic security-regression gate; AST-only incremental updates
  keep it cost-free (graphify) — reinforcing the maturation economics **[F]**.
- **Tool-calling** (Toolformer, ToolLLM, AnyTool, TIR-Judge): pre-call capability gate + closed
  tool registry; **separate transport failure (retry/backoff) from semantic failure (re-parse/
  switch)**; tool hallucination *worsens with weak local models* → harden before migration.
- **Proactive monitoring** (SPC/Wheeler, CUSUM-for-LLM, Klaise): **CUSUM catches the slow drift**
  the maturation curve risks; tiered alerts (ignore/warn/alert/escalate) with **explanations,
  not red lights**; robust no-history limits (MAD/percentile/EWMA) for the local-migration canary.
- **Efficiency** (SPIN self-play; RouteLLM/FrugalGPT): SPIN needs a locked external benchmark —
  defer builder fine-tuning until that exists; **RouteLLM learned routing >2× cheaper** but a
  naive hybrid can underperform — post-attempt cascade now, learned upfront router later.

### 2.5 Testing, security, delegation, explainability
- **Test generation (H2):** generation→validation→repair loop with adaptive focal context;
  **coverage is a weak proxy — mutation-guided augmentation lifts fault detection +28%** (MuTAP);
  cap at 5–10 tests/function; prefer showing a failing test back to the builder over rejection.
- **Mutation testing (H3):** the best no-real-bug completeness metric; **selective** (changed
  lines + neighbourhood), risk-tiered thresholds, run **async in the background** over the
  unattended days; a *ranking* feature, never the sole gate.
- **Injection (I1):** root cause = LLMs treat content as instructions; **structural defence only**
  (JSON+schema, context partition, least-privilege); prompt defences are insufficient.
- **Supply chain (I2):** 100 poison examples implant a backdoor; builder must not freely add
  imports — OSV/CVE + bandit/semgrep + provenance + **stop-and-ask on new imports**.
- **Adversarial robustness (I3):** correct-but-vulnerable is the headline danger (91% ASR);
  add security scanning + **ASR metric** + background red-teaming; defences are *manual*.
- **Delegation calibration (K1):** an **intermediate threshold (~0.75) beats pure-AI and
  pure-human**; thresholds are per-type and **learned from data**; lower autonomy on any
  regression; **throttle escalation volume** to avoid multi-day fatigue/automation-bias; treat
  every human override as a retraining signal.
- **Explainability (K2):** LLM self-explanations are **plausible-but-unfaithful** → prefer
  factual reasons emitted free by deterministic gates; ground every LLM explanation against
  evidence; **an explanation that contradicts its decision is a suspicious-validator signal →
  escalate** (a bounded-overseer integrity check).

---

## 3. Literature → v2 desiderata mapping

| v2 mechanism (0.0) | Strongest supporting research |
|--------------------|-------------------------------|
| 4-gate completion contract | F2 (green tests ≠ safe), JudgeBench, HumanEval+, 70/30 review split, SWExploit |
| Progressive-assurance loop | PRMs + Snell adaptive compute, EvalPlus/EvoEval, MuTAP (H2), mutation (H3), ASR (I3) |
| Failure ladder (repair→replan→escalate) | Process-reward first-wrong-step localisation, four-class fault model, ReAct repair loop |
| Builder≠Judge / LLM-judge | MT-Bench bias suite, Agent-as-a-Judge, G-Eval, TrustJudge calibration |
| Curated-promotion global memory | Episodic-local/procedural-global, category-aware retrieval, slice-local calibration |
| Self-learning PA (deterministic handlers) | Reflexion memory, circuit breakers, tool-failure handlers, SPC rules — all external-anchored |
| Maturation curve (Claude→local) | RouteLLM/FrugalGPT cascade, SPIN (deferred), CUSUM drift guard, bugs-per-dollar metric |
| Remotable control (signals & queries) | FIPA speech-acts, durable-execution signals/queries, structured event schema |
| Code-graph context | Code Property Graphs, Joern incremental, taint-as-security-gate |
| Bounded overseer / defence-in-depth | Silent-failure verification, faithfulness-as-integrity-check, structural security posture |
| Risk-tiered autonomy | K1 confidence thresholds, H3 mutation tiers, I3 security tiers — all converge on policy tiers |

Every major v2 mechanism has independent research backing. The vision is coherent with the
state of the art.

---

## 4. Open problems & disagreements (feeds 0.5 — Predictions & Risk)

- **Does multi-agent orchestration beat a single strong model at all?** Actively contested —
  a foundational challenge to the whole premise; must be in the risk register.
- **Optimality vs flexibility** (formal planners/SPT-EDD vs feedback-driven/learned): unresolved;
  v2's answer is hybrid-with-floor, but the blend must be tuned, not assumed.
- **The maturation curve can regress** (naive hybrid fixes fewer bugs/dollar) — not automatic.
- **Deceptive alignment is provably hard to rule out** — the literature offers detection
  *pressure*, not guarantees → keep self-mod deferred, lean on deterministic gates.
- **LLM-judge & self-explanation faithfulness have no universal guarantee** — task-dependent;
  must be continuously ground-truthed.
- **Silent corruption & equivalent mutants & mid-context degradation** lack reliable runtime
  detectors — design for defence, not detection.
- **Optimal thresholds (escalation fraction, ~0.75 delegation, mutation targets) are
  task-specific** and must be learned per slice — none port across deployments.
- **Cold-start**: monitoring needs 2–4 weeks history; the Claude→local canary has no baseline.

## 5. Caveats on the corpus (traceability)

Several reports flagged that a few originally-requested paper titles could not be verified and
**closely-adjacent papers were substituted** (e.g. AgentOrchestra/Director/ToM for unverifiable
"HMAS/Director 2024"; INSEC for CodefusionX; Confidence-Based/Adaptive/Mutual Trust Calibration
for the requested delegation papers; SHAP/TreeSHAP for "Trees to Networks"). Any v2 decision
resting on a *specific* citation should be re-verified before it is treated as load-bearing.
The corpus is also reports-about-papers, not the papers themselves — primary sources should be
read before final architecture commitments in 0.4.

---

## 6. Annotated bibliography (key papers by domain)

**Orchestration/dispatch:** ReAct (Yao 2023); AutoGen (Wu 2023); Multi-Agent Collaboration via
Evolving Orchestration / "Puppeteer" (Dang, NeurIPS 2025); AgentBench (Liu 2024); AgentOrchestra
(2025); Director (DeepMind 2022); ChatDev (Qian, ACL 2024); AgentScope (Gao 2024); FIPA ACL.
**Planning/scheduling:** LLM+P (Liu 2023); SayPlan (Rana 2023); DEPS (Wang 2023); Pinedo
(textbook); MLFQ (OSTEP); Online Job Scheduling with ML (2022).
**Monitoring:** TimeEval (Schmidl, VLDB 2022); FITS (2023); TimesNet (ICLR 2023); SPC (Wheeler);
CUSUM-for-LLM (2024); Monitoring ML in Production (Klaise 2020).
**Cost/routing:** FrugalGPT (Chen 2023); RouteLLM (Ong 2024); Cost-Aware Orchestration/GUIDE
(2026); Token Economics (2026); PILOT.
**Validation/judge:** MT-Bench/LLM-as-Judge (Zheng, NeurIPS 2023); JudgeBench (ICLR 2025);
Agent-as-a-Judge (2025); G-Eval (Liu, EMNLP 2023); CodeReviewer (Li 2022); Defect-Focused Review
(2025); Let's Verify Step by Step (Lightman 2023); Math-Shepherd (2024); OmegaPRM (2024);
Scaling Test-Time Compute (Snell 2024); DeepBugs (Pradel & Sen 2018); LLift (2024).
**Code-gen quality:** HumanEval (Chen 2021); EvalPlus/HumanEval+ (Liu, NeurIPS 2023); EvoEval
(2024); CodeBLEU (Ren 2020); CodeCrash.
**Tracing:** Dapper (Google 2010); OpenTelemetry; MLflow (Zaharia 2018).
**Reasoning:** CoT (Wei, NeurIPS 2022); Self-Consistency (Wang, ICLR 2023); Tree of Thoughts
(Yao, NeurIPS 2023); Graph of Thoughts (Besta 2024).
**Calibration:** Language Models (Mostly) Know What They Know (Kadavath 2022); Calibration Using
Generations (Xiong 2023).
**Memory/retrieval:** RAG (Lewis 2020); REALM (Guu 2020); In-Context RALM (Ram 2023); ReCode
(2025); DSrepair; Generative Agents (Park, CHI 2023); REMEMBERER (2023); Lost in the Middle
(Liu 2023); MemGPT (Packer 2023); StreamingLLM (2023); MemoryAgentBench (2026).
**Resilience/taxonomy:** Chaos Engineering (Basiri 2016); Faults in Linux (Palix, ASPLOS 2011);
Lineage-Driven Fault Injection (Alvaro, SIGMOD 2015); Beizer Taxonomy (1990); CWE (MITRE);
Defects4J (Just, ISSTA 2014).
**Self-improvement/mod:** Constitutional AI (Bai 2022); RLHF (Stiennon 2020); SELF-REFINE
(Madaan 2023); Reflexion (Shinn 2023); Risks from Learned Optimization (Hubinger 2019); Concrete
Problems in AI Safety (Amodei 2016); Avoiding Side Effects/AUP (Turner 2020); SWExploit (2025);
SPIN (Chen 2024).
**Code-graph:** Code Property Graphs (Yamaguchi, IEEE S&P 2014); Joern (2022); Graph4Code (2020).
**Tools:** Toolformer (Schick 2023); ToolLLM (Qin 2023); AnyTool (2024); TIR-Judge (2026).
**Testing:** ChatUniTest (2023); CoverAgent (2024); TestPilot (Schäfer 2023); MuTAP (2024);
Mutation Testing Survey (2021); Stryker.
**Security:** Greshake/HouYi (2023); "Not What You've Signed Up For" (2023); Jailbroken (Wei,
NeurIPS 2023); Poisoning Instruction-Tuned Models (Wan 2023); Virtual Prompt Injection (2021);
DataComp (2023); INSEC (2024); Adversarial Robustness of Program Synthesis (2022).
**Delegation/explainability:** Confidence-Based Trust Calibration (2025); Adaptive Trust
Calibration (Okamura & Yamada 2020); LIME (Ribeiro, KDD 2016); SHAP/TreeSHAP (2020); Are
Self-Explanations Faithful? (ACL 2024).
