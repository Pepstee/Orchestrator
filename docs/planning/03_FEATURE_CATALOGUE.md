# Orchestrator v2 — 0.3 Feature Catalogue

*Every feature mapped to a module (0.4 §2), tagged by origin, and prioritised. Tight by
design — one line each.*

**Origin:** `v1`=ported concept · `R`=research-backed (Fn) · `LS`=landscape · `you`=your steer.
**Priority:** **P0** = first buildable milestone (the reliable minimal loop) · **P1** = next ·
**P2** = later · **D** = deferred behind a seam / roadmap.

---

## The P0 milestone — "the smallest thing that is already better than v1"

A single goal runs end-to-end, **reliably and legibly**, with nothing arbitrary:
durable event-sourced core + replay · one supervised entrypoint (no false-alarm storms) ·
decompose → dependency-gated dispatch → agent execute → **layered validation (lint+type+tests+
judge)** → **4-gate completion** (judge + you) · budget kill-switch · episodic (local) memory ·
desktop GUI (dashboard + intervention + one-tap confirm) · signals/queries control bus ·
the registries + enforcement toolchain. *Everything else builds on this spine.*

---

## A. Edge / GUI

| Feature | One-line | Origin | Pri | Module |
|---|---|---|---|---|
| Intake funnel | scope-assist → prompt-gen → confirm | you | P1 | edge |
| Architecture flowchart (view) | Architect proposes a confirmable flowchart | you,LS | P1 | edge |
| Flowchart editor | edit/confirm/decline before it becomes Global Task | you | P2 | edge |
| Dashboard (at-a-glance) | waiting/working/done/needs-attention | v1 | **P0** | edge |
| Intervention view | live state + why + what's-next + pending tray | you,R(K2) | **P0** | edge |
| One-tap proposal cards | decision-light steering; no typing required | you | P1 | edge |
| Live activity / event stream | filterable (all/errors/success) | v1 | **P0** | edge |
| Task list + detail | inspect payload/result/handoff/trace | v1 | **P0** | edge |
| Task/dependency graph view | topology visualisation | v1 | P2 | edge |
| Cost & performance panels | spend over time, per-agent | v1 | P1 | edge |
| **Copy text anywhere** | quality-of-life | you | **P0** | edge |
| **Start/stop process from app** | lifecycle control in-app | you | **P0** | edge |
| Pause/resume dispatch | without killing the process | new | P1 | edge |
| **Kill-switch button** | halt all spend immediately | you,R(F8) | **P0** | edge |
| Jump task→events/handoff/trace | click-through | new | P1 | edge |
| Retry / cancel task | from the UI | v1 | P1 | edge |
| Open built-project folder | from the app | new | P1 | edge |
| Search / filter tasks & logs | findability | new | P2 | edge |
| Notifications (desktop + external) | reach you away from machine | you | P1 | edge/control |
| Keyboard shortcuts · theme · export run report | QoL | new | P2 | edge |

## B. Control

| Feature | One-line | Origin | Pri | Module |
|---|---|---|---|---|
| 4-gate completion contract | works ∧ intent ∧ judge ∧ you | you,R(F2) | **P0** | control |
| Signals & queries control bus | remotable command/state surface | you,LS,R(F7) | **P0** | control |
| Budget governor + kill-switch | hard auto-cap halts spend | you,R(F8) | **P0** | control |
| Autonomy / escalation layer | act-vs-escalate calibration (per-tier, learned) | R(K1) | P1 | control |
| Hard stop-and-ask | irreversible / machine-leaving actions | you,R(F10) | **P0** | control |
| Bounded overseer | periodic global sanity + evolves PA | you,R | P1 | control |
| Completion-as-proposal | Judge+Architect emit next-move choices | you | P1 | control |
| Fatigue-throttled escalation | cap escalation volume over long runs | R(K1) | P2 | control |
| Remote control API | desktop now; mobile-ready | you | P1 | control |

## C. Dispatch / scheduling

| Feature | One-line | Origin | Pri | Module |
|---|---|---|---|---|
| Goal decomposition (Task Manager) | one goal → many small steps | you,R | **P0** | dispatch |
| Dependency-gated queue | correct state machine (no queued→blocked bug) | v1,R(L11) | **P0** | dispatch |
| MLFQ aging (anti-starvation) | low-priority work never starves | R(F3) | P1 | scheduling |
| Difficulty estimator (one signal) | feeds routing + assurance + escalation | R(F4),you | P1 | scheduling |
| Cost-cascade routing | cheap→strong, classical floor + learned | R(F3,F8) | P1 | scheduling |
| bugs-per-$ north-star metric | the maturation-curve gauge | R(F8) | P1 | scheduling |
| Local-LLM as cascade tier-0 | the migration | you,R | P2 | scheduling |

## D. Validation

| Feature | One-line | Origin | Pri | Module |
|---|---|---|---|---|
| Layered gate pipeline | lint→type→security→tests→judge | R(F5) | **P0** | validation |
| LLM-judge (≠builder, tool-using) | bias-mitigated, calibrated | R(F5) | **P0** | validation |
| Test augmentation | counter test-insufficiency (HumanEval+) | R(F2) | P1 | validation |
| PRM step scoring | which-rung signal for the ladder | R(F4) | P2 | validation |
| Progressive-assurance loop | edge→mutation→adversarial→audit, bounded | you,R | P1 | validation |
| Judge calibration harness | self-generated correct/wrong pair set | R(F5) | P1 | validation |

## E. PA (deterministic rule engine)

| Feature | One-line | Origin | Pri | Module |
|---|---|---|---|---|
| Consult / fast-path | match failure → known fix, no LLM | v1,R | P1 | pa |
| Startup self-heal | fix env/git/queue before reads | v1 | P1 | pa |
| Overseer-evolved rules | governed, curated promotion (not autonomous) | you,R(F11) | P2 | pa |

## F. Agents (from registry — L5)

| Feature | One-line | Origin | Pri | Module |
|---|---|---|---|---|
| Task Manager · Builder · Validator/Judge · Tester | the P0 minimal roster | v1,R | **P0** | agents |
| Architect (flowchart + proposals) | intake + completion proposals | you | P1 | agents |
| Reasoner (depth=difficulty) | hard/repeated-failure steps | R(F4) | P1 | agents |
| Auditor (security/quality) · Diagnoser · Reporter · Clarify · Explorer · Fan-out · Monitor | specialised roster | v1 | P1–P2 | agents |
| Overseer (bounded) | global sanity + PA evolution | you | P1 | agents |

## G. Memory

| Feature | One-line | Origin | Pri | Module |
|---|---|---|---|---|
| Episodic memory (project-local) | per-run context, handoffs | v1,R(F6) | **P0** | memory |
| Procedural memory (global, curated) | promote project-local→global via gate | you,R(F6) | P1 | memory |
| Curated-promotion gate | generalisation + calibration + freshness check | R(F6) | P1 | memory |
| Code-graph context (graphify) | structural facts to agents; incremental | you,R | P1 | memory |
| Portfolio + aspirations store | built vs wanted → proposals | you | P2 | memory |
| Slice-local calibration | confidence trustworthy per-slice (anti-bleed) | R(F6) | P2 | memory |

## H. Infra

| Feature | One-line | Origin | Pri | Module |
|---|---|---|---|---|
| Durable event-sourced store + replay | resume-from-step; the data spine | LS,R(F7) | **P0** | infra |
| Trace-id propagation | per-goal across every span + verdict | R(F7) | **P0** | infra |
| Atomic IO + tombstones | crash-safe writes (port v1) | v1,R(L7) | **P0** | infra |
| One supervised entrypoint | no false-alarm-on-startup storms | v1-lesson(L8) | **P0** | infra |
| Per-task sandbox | isolation; external-project safety | LS,R(F10) | P2 | infra |

## I. Security

| Feature | One-line | Origin | Pri | Module |
|---|---|---|---|---|
| Least-privilege agents | read-only reasoning/judge; write-diffs builder | R(F10) | **P0** | security |
| Structured JSON+schema input | data≠instructions (anti-injection) | R(F10) | P1 | security |
| Dependency scanning (OSV/CVE, bandit/semgrep) | supply-chain + stop-ask on new imports | R(F10) | P1 | security |
| Taint gate (code-graph) | no new user-input→sink path | R | P2 | security |
| Background adversarial red-team | ASR drift per builder version | R(I3) | P2 | security |

## J. Observability / monitoring

| Feature | One-line | Origin | Pri | Module |
|---|---|---|---|---|
| Structured event log + rotation | the audit trail | v1 | **P0** | infra |
| SPC / CUSUM drift detection | catch slow regression (migration safety) | R(F8) | P1 | control |
| Tiered alerts w/ explanations | ignore/warn/alert/escalate, not red lights | R | P1 | control |
| Circuit breakers (auto-rollback) | confidence/pass-rate/disagreement triggers | R(F11) | P1 | control |

## K. Enforcement (meta — the prime directive, L1/L5)

| Feature | One-line | Origin | Pri | Module |
|---|---|---|---|---|
| Registries (agent→command, agent→model, type→agent) | single source of truth | R(L1,L5) | **P0** | registry |
| import-linter contract | dependency direction enforced | L2 | **P0** | (CI) |
| LOC-budget architecture test | god-files can't re-form | L3 | **P0** | (CI) |
| registry-vs-runtime test | reported model == chosen model | L5 | P1 | (CI) |
| Eval harness | behaviour change validated by evals (charter A2) | R | P1 | (CI) |

## L. Deferred (behind a seam / roadmap)

| Feature | Why deferred | Origin |
|---|---|---|
| Self-modification (core self-edit, builder fine-tuning/SPIN) | mesa-optimisation/deceptive-alignment unprovable; human-led only | D, R(F1,F11) |
| Mobile companion app | remotable API designed for it now; app later | D, you |
| Multi-provider beyond Claude+local | provider abstraction now, breadth later | D |
| Full time-travel debugging UX | durability/replay for reliability now, debugger later | D |

---

## Sequencing note
The **P0 column is the buildable v1-of-v2**: a reliable, legible, single-goal loop with the
enforcement spine in place from commit one. P1 adds the funnel, the assurance loop, cost
routing, global memory, the overseer, and monitoring. P2 adds the richer GUI, code-graph,
local-LLM migration, and the heavier security/assurance tiers. Deferred items stay behind the
enforced seam until explicitly promoted.
