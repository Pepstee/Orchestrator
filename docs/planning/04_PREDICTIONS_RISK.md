# Orchestrator v2 — 0.5 Predictions & Risk Register

*The phase that earns the right to build. Confronts what could make the vision wrong, with
structural mitigations already in the design, early-warning signals, and explicit kill/pivot
criteria. Tight and honest.*

---

## 1. The foundational bet — and how we'd know we're wrong

The literature openly questions whether multi-agent orchestration beats a single strong model
(the "Multi-Turn Multi-Agent Orchestration vs. Single LLMs" line). Taken seriously, this could
invalidate the whole project. The honest position:

> **A single strong model wins on atomic, one-shot tasks. Orchestration earns its keep only on
> long-horizon, decomposable, *validated* work** — where (a) no single context window holds the
> whole project, (b) the multi-gate + progressive-assurance loop compounds quality beyond any
> single pass, and (c) memory + the overseer-evolved PA make it cheaper and more reliable over
> time. v2 is a bet on *that* regime, not on beating one model at a single prompt.

**Falsification test (build this into the eval harness — charter law A2):** if a single strong
model behind a *thin* harness matches v2 on multi-step project completion at **equal cost and
equal reliability**, then v2's heavy orchestration is over-engineered → pivot to the thin
harness. The **bugs-per-$** north-star metric and the eval harness exist precisely to keep this
bet measurable and falsifiable rather than a matter of faith.

---

## 2. Risk register

L = likelihood, I = impact (of the v2 design as specified). "Mitigation" = already in the design.

| # | Risk | L | I | Structural mitigation | Residual & early-warning signal |
|---|------|---|---|----------------------|---------------------------------|
| R1 | Orchestration ≤ single model (foundational) | M | High | scoped to long-horizon+validated; eval harness; thin-harness fallback | may hold for *small* projects → **warn:** eval parity at equal cost |
| R2 | Maturation curve regresses (naive hybrid fixes fewer/$) | M | Med | bugs-per-$ metric, CUSUM, tuned escalation fraction, classical floor | **warn:** bugs-per-$ drops after a local-model swap |
| R3 | LLM-judge fooled by fluent-but-wrong | M | High | builder≠judge, tool-using judge, calibration harness, 4 gates | **warn:** high-confidence approvals later fail downstream tests |
| R4 | Cross-project memory bleed | M | Med | episodic-local/procedural-global, curated promotion, category retrieval, slice calibration | **warn:** a promoted procedure lowers success in a new project |
| R5 | Silent corruption / over-confident agents | M | High | validate outputs (not error codes), PRM, overseer, faithfulness check | **warn:** rising confidence + flat/falling pass-rate (CUSUM) |
| R6 | Cost runaway (autonomous + assurance loop) | M | High | hard budget kill-switch, bounded loop, per-task token cap, tiered spend | **warn:** spend slope decoupling from bugs-per-$ |
| R7 | Concurrency isolation failure (multi-project + global mem) | M | Med | per-project sandbox, isolation discipline, namespaced memory | **warn:** any orchestrator artefact found in a project tree |
| R8 | Deceptive alignment / unsafe self-mod | L* | Catastrophic | self-mod **deferred** behind enforced seam; human-led; red-team corpus | *only if the seam is opened* → keep deferred until eval infra exists |
| R9 | Security breach in autonomous run (injection/supply-chain/adversarial) | M | High | structural posture: least-priv agents, JSON+schema input, dep+taint scan, stop-ask | **warn:** rising red-team ASR; new-import attempts; injection heuristics fire |
| R10 | Scope/complexity over-build (the rewrite itself) | **High** | High | P0-milestone-first, enforcement toolchain, tight phases, port-don't-reinvent | **warn:** P0 slips; LOC budget breached; god-file forms |
| R11 | v1 operational traps recur (false heartbeat, zombie procs) | M | Med | L8: one supervised entrypoint, startup grace, hard-stop lifecycle, smoke test | **warn:** any no_heartbeat-on-startup or duplicate process |
| R12 | Thresholds/evals don't port across deployments | M | Low-Med | learn per-slice, A/B, never hardcode | **warn:** imported thresholds underperform on a new slice |
| R13 | Cold-start monitoring blindness (needs weeks; canary has no baseline) | M | Med | robust no-history limits (MAD/EWMA/4σ), explicit canary period | **warn:** false-alarm storms in the first weeks |

**The biggest practical risk is R10 — over-building.** The whole vision is ambitious; the single
most important discipline is to make the **P0 milestone reliable first** and let the enforcement
toolchain hold the line, rather than building the full pipeline before anything runs.

---

## 3. Cutting-edge bets (balanced appetite — adopt behind flags, keep the classical floor)

Each is promising but unproven; each ships **behind a flag, measured against the classical
baseline, removable**: speculative / early-exit decoding (cost); learned *upfront* router
(after escalation data accrues); mutation testing *as a bar* (not just a metric); automated
adversarial red-teaming; PRM step-scoring; SPIN self-play **(deferred — needs a locked
benchmark first)**. Rule: a cutting-edge technique never becomes load-bearing until it beats the
classical floor on the eval harness.

---

## 4. Maturation-curve predictions (falsifiable)

The thesis (F8) is only true if these move the right way — measure them, don't assume them:

- **P1 — PA hit-rate rises over time.** As the overseer evolves rules, the % of failures handled
  deterministically (no LLM) climbs. *Falsified if* PA hit-rate is flat after N runs.
- **P2 — bugs-per-$ improves** as local tier-0 + PA mature. *Falsified if* it never beats a
  cheap single-model baseline.
- **P3 — human-escalation rate declines** as calibration improves. *Falsified if* escalations
  don't fall (or rise) over comparable workloads.

If a prediction is falsified, that *component* of the thesis is wrong — revisit it specifically,
don't abandon the whole.

---

## 5. Kill / pivot criteria (decide these now, honour them later)

- **Single-model parity** at equal cost on multi-step completion → thin the orchestration (R1).
- **bugs-per-$ never beats cheap single-model** → drop the hybrid-routing complexity (R2).
- **Judge can't be calibrated below an acceptable error bar** → make the human gate heavier,
  lower autonomy (R3).
- **P0 can't be made reliable within its budget** → the substrate choice is wrong; lean harder
  on bought infra (Temporal/LangGraph) per the hybrid decision (R10).
- **Any opened self-mod seam shows reward-hacking/deception in red-team** → re-close the seam
  immediately (R8).

---

## Note for 0.7 (synthesis)
These risks and predictions are the "Discussion / Threats to Validity" section of the Phase 0
paper. The kill-criteria double as the **go/no-go gates** for the eventual build — Phase 0 should
end with them written down so the build is accountable to evidence, not optimism (charter law:
verify with evidence).
