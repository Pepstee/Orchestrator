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
