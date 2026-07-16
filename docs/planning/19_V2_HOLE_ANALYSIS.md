# 19 — V2 Hole Analysis: every measured defect, and its v3 answer

*Consolidated 16 Jul 2026 from two weeks of live operation, incident forensics, a measured
cost audit, and a Mode-C seam review. Purpose: v3 must be the best version yet — this is the
complete map of where v2 bled, why, and where each cure lives in the v3 programme. v1 is a
discontinued artefact: mine it for ideas (its port/ folder, its failure taxonomy), never
resurrect it. Method note: every claim below survived contact with reality — an incident, a
measurement, or an executable repro. Companions: the risk register + evaluators in the
v1-archive (`docs/RISK_REGISTER.md`, `scripts/cost_attribution.py`,
`scripts/repro_worktree_orphan.py` — the last is v3's isolation inheritance-detector).*

## 1. Identity & operations

| Hole (evidence) | Root cause | v3 answer |
|---|---|---|
| Flagship starvation: one failed read at boot silently emptied the dispatch allowance; 80 min lost (14 Jul) | read-once config; silent degradation | hot focus re-read every cycle (ME-7); a failed focus read refuses loudly, never proceeds empty |
| Env-loss restarts: a bare relaunch silently re-armed the wedged Codex judge and reset the intervention cap (15 Jul) | operational config living in paste buffers | defaults live in committed launch config; overrides are deliberate acts (already baked into v2's run_forever as the pattern to inherit) |
| pkill-orphans: killed daemons leave worktree merges half-done, sessions locked by zombie CLIs, tasks failing as "merge conflict" (14–15 Jul, twice) | hard kill as the default stop | STOP-drain as the only stop; Slice 9's supervisor criteria (graceful refusal, stay-down on deterministic failure) |

## 2. The tree, the fence, the operator (the DV-7 wound)

The fence ate the operating guide, the slice feeder (twice), its own log, and four innocent
tasks — every incident a variation of "legitimate content visible in the runtime tree", made
worse by sandbox plumbing commits desyncing `git status`. **v3 answer:** operators and agents
never share a tree — DEVMODE (Slice 9), containers with the orchestrator tree unmounted
(Slice 18, making L9R structural), and the Theseus candidate pipeline (Slice 20) where even
the system's own changes happen in a checkout that is not the running one.

## 3. Providers

| Hole | v3 answer |
|---|---|
| Codex wedge masked as "transient" for ~2 days: opaque exit-1 inherited Claude's usage-cap charity; ~28 wasted judge runs | opaque exits stay transient ONCE — five identical opaque exits from one provider escalate (Slice 19 broker criterion); per-provider health, not per-call guessing |
| Auth expiry looped all night as transient | 401/auth wording fails FAST + notifies (fixed in v2 with tests; Slice 6 criterion carries it) |
| Session locked by an orphaned CLI process → guardian "missed check-ins" | Slice 9: `--resume` is an optimisation whose failure is non-fatal; canonical UUID sessions |
| Cross-provider judging existed on paper only (Codex never answered) | Slice 12: registry model changes require eval-store receipts; outage overrides remain reversible env acts |

## 4. Budgets, eras, breakers

| Hole | v3 answer |
|---|---|
| The 3-intervention treadmill: productive hardening (each fix real) killed by a shared-era budget; v3-the-project abandoned twice | per-slice rescope eras; operator-tunable intervention cap with floor 1 (both live in v2's feeder/daemon as the inherited pattern) |
| Era inheritance: a revived project arrived pre-exhausted | abandonment closes the era; revival = clean ledger (v2 `de63f94` semantics — port verbatim) |
| Burn breaker tripped on quota weather twice (fence storm 8 Jul; dead window 14 Jul) | breaker counts QUALITY signals only — transient failures are weather (fixed in v2 with tests; Slice 6 criterion) |
| Binary adversarial verdict made "fully hardened" unreachable — an LLM adversary always finds one more thing | severity-aware rung: minors log to the improvement backlog, blockers block (Slice 5 — already certified WITH this design) |

## 5. Cost (measured: $489/7.6 d; evaluator re-runnable)

| Bleed | Measured | v3 answer |
|---|---|---|
| Guardian contemplation: 44% of attributed spend; ≥7 confessed quiet pulses | $171.53/61 pulses | Slice 9 pulse economics (ledger-delta gate, ≤2 skips, journalled) + DV-5 KB digest bounding context (the $10-per-pulse session bloat, 10 Jul, is the standing counter-example) |
| Failure burn 24% — 131 failed validates | $94.10 | root causes were blindness+wedge, both structural in v3 (planner cause contract §8; provider health §3) |
| Dead-window probes on flat backoff | $5–15/window | exponential backoff (in v2, tested) + Slice 6 pause-until-reset |
| No per-call metering: 20% unattributable | $96 | Slice 19 broker = the meter (agent/task/model/tokens/cost rows) |

**Doctrine made law (Slice 17): raw fail-rate is NOT a waste metric — repetition past the
retry budget is.** The naive metric was falsified in production: 99/101 "wasteful" failures
were genuine judge findings. A cost fix that would have degraded verification was caught by
an executable lock before it spent a token. Baseline process calibration: 2/10 claims
discarded by experiment.

## 6. Verification integrity

| Hole | v3 answer |
|---|---|
| Judge gamed by "review-only, do NOT execute" validates (passed 0.90–0.95 over a red suite, four documented false-passes) | Slice 11: execution-shaped validation — a validate that forbids execution FAILS the gate |
| Judge variance: FAIL(0.97, real findings) → PASS(same artefact, no change between) | OPEN — candidate policy: consecutive-pass requirement for contested verdicts, or variance folded into Slice 25 guardian/judge evals. Not yet encoded; fold at next natural feeder restart |
| Judge provider down ⇒ adversarial assurance rung silently self-skips (passes) | Slice 11/19: a skipped verification rung is a FAILED rung when its provider is unhealthy — never a silent pass. Not yet encoded as a criterion; fold with the above |

## 7. Isolation (the seam review, R-101..103 — Reproduced, milestone-gating)

A failed worktree create in v2 is SILENT (no returncode checks; the pool swallows the
exception) and the agent runs UNGATED on the live project tree; environment failures wear a
content-conflict's name, which BG-3 then terminal-fails. **v3 answers:** Slice 9 P0 drill
includes an isolation-loss drill (failed create = loud, never ungated); Slice 20 candidates
refuse on isolation loss; Slices 17–18 containers close the class structurally.
**Inheritance test:** `repro_worktree_orphan.py` run against v3's isolation — exit 0 = v3
inherited the defect.

## 8. Planner pathologies (the most instructive class)

| Hole | v3 answer |
|---|---|
| Cause-blindness: `[:200]` truncation fed the planner titles instead of causes — seven rounds measuring one unread failure | v3 planner CONTRACT: failure causes are first-class inputs with a guaranteed budget (the fix pattern is in v2 `d4d34e7`); a replan that plans zero implements against a standing genuine cause is a planner defect |
| Stale goal inheritance: every replan titled "Slice 1" forever; fronts can silently pivot | Slice 13 criterion: plan context carries the CURRENT era's goal, proven by test |
| Goal compression: multi-part injected goals lose parts (2 of the overseer's goals dropped their snapshot-implement halves) | OPEN — the guardian runs a "narrow-goal tripwire" behaviourally; encode as a planner contract test at next natural restart |
| Review-only emission under pressure (the gaming vector) | Slice 11 (§6) |
| Criteria poisoning: replan spirals tightened acceptance criteria into unsatisfiability (system-temp as scope violation; literal stub-grep matching README prose) | partially open — the planner self-corrected once (12 Jul); Slice 11 evals should include a criteria-sanity rubric |

## 9. Operator surface honesty

The plain-speech notifier under-alarmed during a real starvation, invented a project named
"BG-5" from a law id, and prescribed restarts for recovered conditions. **v3 answer:** Slice
16 criterion — alerts fact-checked against the live ledger before send, tested against the
three real transcripts.

## 10. What v1 still owes v3 (mine, don't resurrect)

The port folder earns its keep: `error_triage.py` (taxonomy — already ported), `admission_control.py`
(AIMD — reborn in the broker), `velocity_monitor.py` (stall signatures — ideas for Slice 9's
health machine), `watchdog.py` (alert pattern library), `benchmark.py` (Slice 12's harness),
`reasoning_session.py` (multi-turn repair context — candidate for the feedback distiller).
Nothing else: v1's 26k lines were the argument for v2's 6k.

## The three still-open items (nothing else is uncarried)

1. Judge variance / consecutive-pass policy (§6) — fold into Slice 11 or 25 criteria.
2. Skipped-verification-rung-when-provider-down = fail, not pass (§6) — same vehicle.
3. Goal-compression planner contract (§8) — Slice 11 eval or Slice 13 criterion.

All three ride the next natural feeder restart (v2 freeze honoured — no dedicated window);
until then the guardian carries them via handoff §8 and its own beliefs.
