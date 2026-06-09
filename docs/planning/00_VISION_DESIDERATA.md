# Orchestrator v2 — 0.0 Vision & Desiderata (consolidated)

*The anchor for all of Phase 0. The literature review (0.1) is read through this lens;
the feature catalogue (0.3) is justified and prioritised against it.*

---

## 1. One-line vision

> A reliable, observable, **GUI-first desktop orchestrator** that takes **one goal** for a
> project and **autonomously** drives it to completion through a team of **specialised
> agents** — trustworthy enough to leave running for days, legible enough to audit every
> step, and **cheaper and more deterministic the longer it runs.**

## 2. The confirmed frame

- **Interface:** GUI-first desktop; **remotable control surface** (signals & queries) so a
  mobile companion can drive it later — designed-for from day one.
- **Autonomy:** fully autonomous; **decision-light one-tap steering**; it **never idles**.
- **Work domain:** code-first, architected to extend to other domains without a rewrite.
- **Research appetite:** balanced — proven core, strong recent results behind flags, the
  bleeding edge feeds predictions.
- **Substrate:** **hybrid** — hand-roll most, but adopt durable **event-sourced execution +
  crash-replay** and the **signals & queries** control pattern (the two things that broke v1).
- **Models:** Claude now, **provider-abstracted**, with a **planned migration to local LLM**
  (hybrid routing, per-agent, balance shifts via config).
- **Self-modification:** **deferred** behind a clean seam; not in v1.

## 3. Defining mechanisms

1. **Goal-intake funnel (signature flow).** A **"build-your-idea" guided intake** — the app
   *questions you Socratically* to draw out the full idea/requirements (the way Phase 0 elicited
   this vision) → assists prompt generation → the Architect proposes an architecture as a
   **confirmable flowchart** → on approval it becomes the **Global Task** → the agents (Task Manager
   → Architect → Builder → Judge → Tester) decompose and build it. *Rich intent capture up-front is
   how the orchestrator avoids efficiently building the wrong thing.* Also: scheduled, templates, auto-spawned
   sub-goals. *(This is the Phase-0 process itself, productised.)*
2. **Completion contract — TWO TIERS.** *Tasks/steps complete **autonomously*** via their own
   automated checks (tests/lint/judge) — you are **never asked to approve individual steps**, and a
   development phase can run **autonomously for weeks**. A whole **project (Global Task)** is
   **officially DONE only when all four gates pass**: tests green ∧ acceptance criteria met ∧
   LLM-judge approves ∧ **your confirmation**. *Each gate answers a different question (per F2):
   tests = **works** (usability, not safety); acceptance = **meets intent**; judge =
   **correct & quality**; you = **accepted**. Safety/hardening is NOT a test concern — it is proven
   by the adversarial/security checks inside the progressive-assurance loop.*
3. **Progressive-assurance loop = the bounded pre-confirmation hardening window.** When a project
   *finalises* (automated gates pass) it does not idle waiting for you — it runs ever-stricter
   verification cycles (edge-case tests → mutation → adversarial → design-audit) to maximise
   confidence in the window before you arrive (you're available within **~14h** of finalisation),
   so your one-tap confirmation is maximally informed. **Bounded by both your availability window
   and the budget cap; never regresses.** With multiple concurrent projects, **idle capacity goes
   to other projects first** — hardening a finalised one is the lowest-priority filler, not a pit.
4. **Failure ladder.** repair in place → replan a different approach → escalate to you.
5. **Completion = a proposal moment.** LLM-judge + Architect propose next moves (future work,
   optimisations, new projects) as **one-tap choices**, grounded in the portfolio + aspirations
   memory. The Da Nang test: redirect it in 30 seconds from your phone, then get back to life.
6. **Maturation-curve thesis.** local-LLM migration (cheaper) + **overseer-evolved PA** (more
   deterministic, fewer LLM calls) + the validation gates (catch regressions) → the system
   gets **cheaper, more deterministic, and more reliable over time.** Architect for this curve.
   *The PA does NOT learn autonomously: the **bounded overseer agent** observes outcomes and
   proposes/modifies the PA's deterministic rules, under curated promotion — human-led for
   anything crossing the self-modification seam (per F1).*

## 4. Safety & governance (defence in depth)

- **Hard stop-and-ask** (even when autonomous): irreversible file ops; any action that
  **leaves the machine** (push/publish/send). Principle: *reversibility + blast-radius* —
  irreversible/external actions gated, reversible local actions proceed.
- **Budget = hard auto-cap / kill-switch** (halts spend), governs the progressive-assurance loop.
- **Memory:** global accumulation via **curated promotion** (project-local → global only after
  a check) — structural defence against v1's cross-project bleed.
- **Concurrency:** multiple projects in parallel → strict isolation discipline.
- **Defence in depth:** deterministic gates → curated promotion → **overseer** (periodic global
  sanity) → you. *The overseer is bound by the same laws it enforces — no unbounded guardian
  (it was a top reliability liability in v1).*

## 5. Agent roster — **5 agents + the meta-agent (Overseer)**

**Task Manager** (decompose + reasoning mode) · **Architect** (build-your-idea intake + flowchart +
proposals) · **Builder** (implement) · **Validator/Judge** (gate + security/quality; on OpenAI/Codex)
· **Tester** (generate/run tests) · **Overseer** (meta: global sanity + evolves the PA). *Everything
else is a function/tool/mode, not a standalone agent — resisting v1's agent proliferation. Canonical
map + folded functions: see `08_DECISIONS_AND_REGISTRY.md`.*

## 6. GUI surfaces

**Major:** dashboard (at-a-glance) · intake funnel + **flowchart view/editor** · live
activity stream · task list + detail · task/dependency graph · meta-agent chat · cost &
performance panels · **pending-confirmation tray** · **proposal/choice cards**.

**Minor / quality-of-life:** copy text anywhere · **start/stop the process from the app** ·
pause/resume dispatch · click task → jump to its events/handoff/artefacts · retry/cancel ·
open the built project folder · search/filter tasks & logs · keyboard shortcuts ·
notifications (**desktop + external messaging**) · live cost ticker + health indicator ·
export a run report · dark/light theme · **kill-switch button**.

## 7. Capabilities adopted from the landscape

- **Signals & queries** as the control model (Temporal) — the remote-control blueprint.
- **Repo-map / code-graph** fed to agents (Aider + graphify) — understand before editing.
- **Durable event-sourced execution + crash-replay** for reliability (resume from step).
- *(Time-travel debugging, per-task sandbox VM, CodeAct, PR-diff review — considered, not v1.)*

## 8. Experience qualities

Trustable unattended · legible failures · fully auditable · responsive · approachable
(plain-language goals) · calm (escalates only when it genuinely needs you).

## 9. Open areas (resolve during 0.1–0.4)

Security posture (injection/supply-chain/adversarial) · self-evaluation strategy (how we know
v2 is reliable — evals are a charter law) · cost-model specifics (per-project budgets) · GUI
surface prioritisation for the first build · explainability mechanics (how the "why" is
captured & shown).

---

## Appendix — decisions log (round-by-round rationale)

- **R1:** GUI-first · fully autonomous · code-first-extensible · balanced research appetite.
- **R2:** 4-gate completion contract · stop-and-ask on irreversible/external actions · global
  memory · concurrent projects.
- **R3:** progressive-assurance loop (don't idle; escalate rigour) · curated-promotion memory ·
  desktop + external notifications · Claude-now/provider-abstracted.
- **R4:** assurance loop = edge-tests + mutation + adversarial + design-audit · failure ladder
  repair→replan→escalate · intervention view shows everything · intake funnel (scope → flowchart
  → Global Task → decompose).
- **R5:** remotable control surface · decision-light one-tap steering · completion-as-proposal ·
  portfolio + aspirations memory.
- **R5b/c:** planned Claude→local migration (hybrid) · self-learning PA (deterministic handlers,
  curated promotion, sandboxed — not core self-mod) · overseer as bounded periodic guardian.
- **R6:** hybrid substrate (adopt durable execution + signals/queries) · repo-map/code-graph ·
  one-tap approval (no diff-review gate).
