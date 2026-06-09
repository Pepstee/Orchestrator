# Orchestrator v2 — 0.2 Requirements & Usability

*Concise backfill. Functional requirements = the P0/P1 feature catalogue (0.3) — not repeated
here. This document pins the **non-functional** targets and **usability flows** that the
features must satisfy, made measurable where possible, each traced to its source.*

---

## 1. Non-functional requirements (the "feel" as targets)

| # | Quality | Measurable target | Source |
|---|---------|-------------------|--------|
| N-Reliability | survives unattended | P0 loop runs an **N-hour soak** with **zero unrecoverable states**; any crash resumes from the last step, never from zero | v1 goal, F7 |
| N-Trust | no surprises | hard budget cap is **never exceeded**; every irreversible/machine-leaving action is gated; spend is always visible | you, F8/F10 |
| N-Legibility | every failure explains itself | 100% of failure events carry a `cause`; the intervention view answers **what / why / next** without log-diving | F10, K2 |
| N-Responsiveness | live, not laggy | UI reflects state changes in **≲1s**; a newly-enqueued task is picked up in **seconds** (event-driven wake, not poll-only) | LS, v1 |
| N-Calm | escalates only when needed | escalation volume is **throttled** over long runs; notifications are meaningful, never spammy | K1 |
| N-Approachability | a non-dev can drive it | a first goal can be launched through the funnel **without reading docs** | you, v1 |
| N-Cost-efficiency | the maturation gauge | **bugs-per-$** tracked continuously and trends the right way (0.5 P2) | F8 |
| N-Cold-start | safe with no history | monitoring uses **robust no-history limits** (MAD/EWMA/4σ) for the first weeks; thresholds learned **per-slice** | F8, R12/R13 |
| N-Auditability | full history | every goal is **fully reconstructable** from the event-sourced trace alone | F7 |

## 2. Usability flows (the experiences that must work)

- **F-Intake (the funnel):** type/scope a goal → assisted prompt-gen → Architect proposes a
  **confirmable flowchart** → edit/confirm/decline → it becomes the Global Task. *Success: a
  non-technical user understands and confirms the plan without a manual.*
- **F-Steer (the "Da Nang test"):** notification → open app/phone → **one-tap** redirect or
  next-move from a curated choice list → back to life in **~30 seconds**, zero typing required.
- **F-Intervene:** open the app at any time → see live state, the *why* behind decisions,
  what's next, and the pending-confirmation tray → redirect with one tap.
- **F-Approve:** completed-but-unconfirmed work parks; meanwhile the progressive-assurance loop
  hardens it; you approve via one tap (diffs inspectable, never required).
- **F-Lifecycle:** start/stop/pause the orchestrator **from within the app**; kill-switch halts
  all spend instantly.

## 3. Operating constraints (carried from v1 lessons)

- **macOS-first** (current dev machine); native filesystem (the FUSE/mount class of v1 bugs is
  gone, but keep atomic-IO discipline — L7).
- **One supervised entrypoint**; no false-alarm-on-startup; soft-stop cannot resurrect (L8).
- **Claude now**, provider-abstracted; **local-LLM** as a planned cascade tier (hybrid).
- **Single machine**, file-based + event-sourced; no DB/broker required (v1 proved sufficient).

## 4. Acceptance criteria for the P0 build (the go-live bar)

P0 is "done" when, on the eval harness (0.6 §2(d)):
1. A real multi-step goal completes end-to-end through all four gates, **unattended**.
2. A forced crash mid-run **resumes from the last step** with no lost/duplicated work.
3. The **kill-switch** and **budget cap** demonstrably halt spend.
4. Every enforcement check (0.6 §1) is **green in CI**.
5. The **project tree is pristine** — no orchestrator scratch leaked (L4).
6. A non-developer can launch a goal via the funnel **without instruction**.

*If P0 cannot meet these within its budget, that is the R10 kill-criterion firing — reassess
the substrate (lean harder on bought durable-execution infra) before adding any P1 feature.*

---

## Note for 0.7
This is the "Requirements" section of the Phase 0 paper. The §4 acceptance criteria are the
concrete, testable definition of the first milestone — the bridge from Phase 0 (planning) to
the eventual build.
