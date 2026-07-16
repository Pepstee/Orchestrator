# 18 — The GIGA Capability Wave (v3 slices 11–16, post-P0)

*Status: RATIFIED in direction by the operator, 14 July 2026 (source: the operator's GIGA-user
design session; deduced requirements confirmed in conversation). Slices encoded verbatim in
`control/slice_feeder.py` (11–16); the feeder dispatches them only after Slice 10 certifies —
ordering is structural (certs ≥ n−1), not aspirational. House rule holds: every mechanism names
the check that polices it.*

## The thesis being built

The operator's goal is maximum leverage: attention spent only on direction, taste, and
verification, while systems execute. The differentiator at that level is not prompting or fleet
size — it is **evaluation**, **compounding memory**, and **surface area beyond code**. This wave
turns those from essays into slices.

## The slices (acceptance detail lives in the feeder — single source)

| # | Slice | What it closes |
|---|---|---|
| 11 | **Eval harness** — EvalPort, rubric-graded behaviour evals in a durable store; behaviour changes gated on non-regression; ME-5 promotion consults it; execution-shaped validation enforced | v2's A2 law (deferred since birth); the 12 Jul "review-only validate" gaming class; the missing precondition for safe self-improvement |
| 12 | **Eval-driven routing** — v1 benchmark harness ported; registry model changes require eval-store receipts; env overrides stay the outage lever | "model X for task Y" folklore; makes judge/model choices measured decisions |
| 13 | **Feedback distiller** — operator corrections (vetoes, Telegram directives, quarantines, requeues) → KB entries + CANDIDATE eval cases, promoted via the curated gate | "learns from your edits" — the one unclosed line of the operator's challenge; taste becomes regression tests |
| 14 | **Personal knowledge corpus** — MemoryPort widened to operator-configured life corpora (notes, journal, research, transcripts) via read-only manifest-gated connectors; budget-capped recall in planner/overseer context | code-shaped memory; the retrieval-breadth gap |
| 15 | **Scheduler + morning briefing** — SchedulerPort (cron→inbox, never direct log writes); daily what-changed/why/suggested-actions via notify + GUI; one-tap actions through existing channels only | the empty `scheduling/` seam; the AI-OS daily surface |
| 16 | **Leverage metrics** — operator-touches-per-certification; window-cost per project from focus events; trends in GUI + briefing | measuring the actual thesis: shipped certified work per unit of operator attention |

## Guardrails adopted with the wave (anti-goals)

- **No fleet vanity.** Agent count is not a metric. Growth happens through manifest-gated
  modules, each requiring a certification (ME-8); the roster grows only with eval-backed
  justification. *(Check: registry single-source test + module load gate already enforce this.)*
- **Debate is earned.** Multi-agent debate/ensembles only where an eval shows the win; never a
  default topology. *(Check: any debate topology must cite an eval-store entry — folds into the
  Slice-12 receipt rule.)*
- **Context minimalism is doctrine.** Smallest high-signal token set; budget-capped recall
  everywhere. The 10 Jul 500k-token overseer session is the standing counter-example.
  *(Check: Slice 14's recall budget cap is tested.)*

## Placement rationale (why post-P0, why this order)

Nothing here may precede the P0 certification: the wave hardens and extends a machine that must
first exist. Within the wave, evals come first because every later slice consumes them (routing
receipts, feedback-derived cases, briefing trends) — the hub before the spokes. Slices 13–16
are deliberately independent of each other so a stall in one cannot block the rest (the
prerequisite-cascade lesson).

## Standing note for the charter merge

When v3 assumes its own development (post-cutover, ME-5), slices 11–16 transfer from v2's
feeder to v3's own intake — the eval harness is what makes that transfer safe.

---

## Addendum, 15 July 2026 — the full programme (slices 13–26, operator-ordered)

Gap analysis against the GIGA vision found two buckets missing from the fed programme; the
operator ordered both encoded, and separately ratified the **knowledge graph as crucial and
its use as ENFORCED** — promoted from deferral to load-bearing slice 13, ahead of the corpus
and briefing so everything downstream lands in an indexed world. Acceptance detail lives in
the feeder (single source).

**Slice 13 — the knowledge graph (load-bearing, enforced):** typed graph over code + KB +
ledger entities (corpus joins at 15); ENFORCED freshness (stale graph = red boot check) and
ENFORCED consultation (planner/overseer context requires a graph-receipt; planning without one
is refused at the seam — the DV-2 fail-closed pattern). "A graph nobody is forced to consult
is a wish."

**Bucket one — ratified in planning/17, now slices 18–21:**
18 container runner (ME-4; manifests generate sandbox profiles; orchestrator tree unmounted —
L9R made structural) · 19 credential broker (tokens never enter sandboxes; per-call metering;
AIMD backpressure; the opaque-exit escalation rule) · 20 **the Theseus machinery** (ME-5/DG-5:
candidate/promotion pipeline with in-candidate gates, eval non-regression via Slice 11,
blue-green auto-revert, constitution veto window — the piece that makes unattended
self-improvement survivable) · 21 resurrection drill (ME-6/DG-8: guardian raisable, proven).

**Bucket two — vision gaps, now slices 22–26:**
22 untrusted-input hardening (external tokens are data, never instructions; injection drills) ·
23 local-model tiering (cheap breadth, receipt-assigned) · 24 read-only world connectors
(calendar/email/GitHub → KB; actions stay operator-channelled; eyes before hands) ·
25 guardian evals (the full-control agent stops grading its own homework) ·
26 portfolio ratchet (DG-4: breadth doubles on clean soak, halves on breach).

Slice 15 (personal corpus) was amended in place: the injection drill applies from day one
(a poisoned note must never steer a plan) — safety lands with the surface, not after it.

**Cost-audit inputs, 16 Jul** (register: v1-archive `docs/RISK_REGISTER.md` C-001..C-005;
evaluator: v1-archive `scripts/cost_attribution.py`): measured $489/7.6 d — observation 44%,
failure-burn 24% (since locked out), quiet pulses and flat backoff fixed in v2 code the same
day. Fed into the programme as: Slice 9 pulse-economics criterion (quiet-gate from birth),
Slice 13 stale-goal criterion, Slice 15 notification-honesty criterion, Slice 16 waste-metric
doctrine + attribution-evaluator port. Standing lesson made law: raw fail-rate is not a waste
metric — repetition past the retry budget is.

Deliberately still unplanned (recorded, not forgotten): semantic/embedding retrieval on top of
the graph (deferred per N5 until graph+keyword recall measurably fails); write-capable world
connectors (hands stay human until the injection posture has soaked); voice/mobile surfaces
beyond Telegram + GUI.
