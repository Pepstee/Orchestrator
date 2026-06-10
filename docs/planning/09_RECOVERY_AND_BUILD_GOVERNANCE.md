# Orchestrator v2 — 0.8 Recovery & Build Governance

*Written 9 June 2026, after the first production-scale v2 run ended in a stop order: 16 hours,
52 successful agent runs against 1,513 failures (~3%), one task retried 90 times, the weekly
usage window drained, zero projects certified. This document is the bridge between the Phase 0
corpus (00–08), which was right, and the build, which did not follow it. It applies the prime
directive — **a law without a machine-check is a wish** — to the build process itself.*

**Status:** v1.1 — amended 9 June 2026 after independent verification of the diagnosis against
both repos and a stress-test of the BG checks (amendment log: §9). DG-2 is an **open decision
for the operator**. Copy into the live v2 repo (this folder is a git-less snapshot), commit, and
wire the checks before any further feature work.

---

## 1. Evidence base

| # | Observation | Source |
|---|-------------|--------|
| E1 | 52 ok / 1,513 failed runs in ~16 h (~3% efficiency); weekly window drained | run session, 9 Jun |
| E2 | One merge-conflict task requeued 90 times; ~6 tasks with genuinely overlapping diffs | run session |
| E3 | Overseer dead ~11 h overnight: malformed session id (dash-less UUID) failed `--resume` hourly; stale `overseer_session.json` survived a log wipe; daemon cached the id in memory | run session |
| E4 | 16 × `TimeoutExpired` on long Claude calls, unaddressed | run session |
| E5 | 8 projects built concurrently; `confirmations/` empty — no project ever passed the completion contract | run session |
| E6 | Products underscoped: mock backends, CLI-only, ~1,000 orphan lines across duplicate packages (`tts_studio/`, `panalytics/` 629 lines, `local_llm/`); edge still packaged as `situation_monitor`, its tests do not collect; writing-assistant test collection hits `RecursionError` | run session |
| E7 | Usage-cap exhaustion surfaces as bare `claude exited 1`; was misclassified as permanent failure | run session |
| E8 | Escalation tray pulled the human in for merge conflicts (deal-sniper, digital-twin) — the wrong things escalate while a dead overseer did not | run session |
| E9 | v1 already solved several of these: `error_triage.py` (TRANSIENT/RECOVERABLE/PERMANENT, `MAX_TRANSIENT_REQUEUES=5`, 30 s × 2ⁿ backoff capped 300 s), `admission_control.py` (AIMD rate-limit control), task/session checkpoints, reasoning-session accumulation across retries, supervisor graceful restart. None of it reached v2 | v1 audit, 9 Jun |
| E10 | v1's watchdog fired `no_ready_tasks` **5,384 consecutive times** over 170+ h into the void; `journal_gap` unresolved 42 h; its one failed task is an overseer escalation that returned unparseable output 4× | v1 `state/` audit |
| E11 | v1's supervisor/orchestrator **confirmed still running idle** on the host: supervisor PID 45634, orchestrator PID 45637, cycle 4027 ticking ~1/min, zero tasks since 1 June, self-check reporting an infinite-loop signature. Whether the zombie co-paid for the window exhaustion is unproven — Phase A attributes it from v1's journal | v1 `state/` audit; live verification 9 Jun |
| E12 | v1 `orchestrator.py` is now 4,161 LOC (the charter recorded 4,067 when it wrote the file's obituary) | v1 audit |
| E13 | Stray artefacts: `projects/p/` with a stuck `.git/index.lock`; `pytest-cache-files-*` in writing-assistant | run session |
| E14 | Budget log reports $0.00 while the GUI imputes ~$160 — no usable cost/usage ledger | run session |
| E15 | v2's **static** enforcement spine exists and is green: 3 import-linter contracts (L2, registry-leaf, L9), ruff, architecture suite incl. `test_every_law_has_a_check`, L11 totality, L7 preservation, registry single-source. The 4-gate contract is *defined* (`validation/gates.py`: `REQUIRED_GATES = (tests, acceptance, judge, authenticity)`) but the gates are true-by-default proxies; greps find no `MAX_ACTIVE_PROJECTS`, no `attempt_budget`, no `burn_rate`, no boot self-test | live v2 repo verification, 9 Jun |
| E16 | The implemented gate tuple contains **no human gate**: `authenticity` (anti-mock) stands where ADR-04's `accepted(you)` should be. The goal-drift of F10 was already in the code, not merely in stated goals *(subsequently ratified deliberately — DG-2)*. Correction on direct inspection, 9 Jun: the human gate **did** exist as the daemon's `pending_user` step (v2 CLAUDE.md lifecycle), absent only from the automated tuple — DG-2 therefore lands as *removing that wait*, not adding a gate | E15 |

## 2. Root-cause findings

| # | Finding | Violated law / risk | Evidence |
|---|---------|---------------------|----------|
| F1 | *(narrowed after verification, E15)* The **static** architecture spine was built well. What was skipped is the enforcement that binds behaviour **under load** — gate predicates with teeth, budgets, caps, the boot self-test — and 07 §8.3's rule: no breadth before P0 meets its bar. The demo gradient applied even to enforcement itself: the checks that don't constrain the build got built; the ones that do, didn't. R10 occurred as predicted | prime directive, R10 | E1, E5, E15 |
| F2 | Retries did not change inputs: same prompt, same base state, 90 times — the failure ladder collapsed into "retry". **Proximate cause:** a fresh regression (conflict-as-transient, introduced 8 Jun, since reverted). **Structural cause:** nothing made that one-line error cheap — no loop-cap test, no burn-rate breaker. The spark gets a regression test (BG-7); the dry forest gets Phase C. Misclassification is inevitable; the system must be safe under it | L6, ladder (00 §3.4) | E2 |
| F3 | No economic layer: budget kill-switch and per-task token caps were designed (R6 mitigations, P0 features) but not built; nothing sensed burn-rate decoupling from progress | L6, R6 | E1, E14 |
| F4 | Only gate 1 of the 4-gate contract was live, and it was gameable: agents closed tasks on tests that mock the product. The corpus's headline finding — *a green test suite is not a done signal* — was unenforced | ADR-04, F2(lit) | E5, E6 |
| F5 | The overseer's memory lived in a provider chat session (opaque, un-replayable); one malformed id silently killed it for a night. Nothing guarded the guardian | A3, L8, R11 | E3 |
| F6 | Alert semantics are wrong in both generations: alerts repeat instead of escalate-dedupe-or-resolve (5,384 identical alerts is a log line, not an alert); meanwhile real anomalies (90 retries, dead overseer) raised nothing | L10 | E2, E3, E10 |
| F7 | The rewrite abandoned its inheritance: FOUNDATION §5's port-list (triage taxonomy, AIMD, backoff, checkpoints) was never executed, so v2 re-purchased solved bugs at full token price | FOUNDATION §5 | E7, E9 |
| F8 | Breadth before depth: 8 concurrent projects on an unproven pipeline multiplied burn ×8 while adding no information the first project would not have produced | R10, 07 §8.3 | E1, E5 |
| F9 | Failure classification keyed on strings/exit codes rather than cause classes (deterministic vs stochastic); deterministic failures (merge conflicts) were treated as retryable weather | L10 | E2, E7 |
| F10 | Goal drift: "human out of the loop entirely, no confirmations" contradicts the ratified ADR-04 contract, whose design already minimises the human to one asynchronous tap per project | ADR-04 | stated goals |

## 3. Build-governance laws (BG) — the prime directive applied to the build itself

Per the law-intake rule (05 §4): each law ships with its check, in the same change.

| # | Law | Machine check (predicate pinned — an undefined predicate is how gate 1 became gameable) |
|---|-----|---------------|
| **BG-1** | No feature work while enforcement is red or absent; the boot self-test refuses to dispatch build tasks otherwise | Self-test asserts the **named** architecture checks are *collected and pass* (anchored on `test_every_law_has_a_check`), never an aggregate exit code — partial collection or a deleted test file must read red. No bypass flag/env exists (tested) |
| **BG-2** | Depth before breadth. `MAX_ACTIVE_PROJECTS = 1` until `confirmations/` holds a first certification; doubling only after a clean soak (DG-4); the cap is human-only configuration | Boot assertion validates the certificate's **contents against a schema** (four gate verdicts + evidence-bundle refs), not file existence; write-path isolation test proves no agent/overseer code path can modify the breadth config |
| **BG-3** | Every failure changes inputs; the ladder rung must advance: repair → replan → escalate | `test_no_identical_reattempt` with the hash **pinned**: canonicalised prompt (timestamps/UUIDs/attempt-counters stripped; one canonicaliser, single source) + the git rev the worktree branched from + sorted declared target paths (or declared scope). Rebase-replan changes the base rev ⇒ new hash ⇒ permitted; retry-apply against the same base ⇒ refused. Rung monotonicity tested separately |
| **BG-4** | Alerts escalate, dedupe, or resolve — never repeat | Emitter test with a defined per-key **state fingerprint**: same key >3× with unchanged fingerprint ⇒ escalate one level; the terminal level is the human notify path; resolution followed by genuine recurrence re-arms at level 0 (the 5,384 pathology, both directions) |
| **BG-5** | Guard the guardian — gradually, so the guardian doesn't become the new single point of failure | Two missed pulses ⇒ **restart the overseer** (safe under BG-6) + notify; two failed restarts ⇒ pause paid work. The chain has an external top: supervisor under launchd KeepAlive. Drill: kill overseer (assert restart), then block restart (assert pause) |
| **BG-6** | Guardian state lives on disk; `--resume` is an optimisation whose failure is non-fatal by construction | Delete the session store ⇒ pulse must still succeed. **Companion:** the pulse reads a bounded, incrementally-compacted digest + event-log tail, never the raw log (unbounded context would make pulses slower and costlier across a weeks-long soak); digest size bound asserted; pulse context ≤ budget by construction |
| **BG-7** | Incidents become executable knowledge within 24 h | Ledger linkage admits `test_id \| drill_id \| waiver{owner, expiry}` — some incidents (a drained weekly window) are drills, not unit tests; an expired or ownerless waiver is red |

## 4. Decisions (rationale · alternatives rejected)

**DG-1 — Harden the live daemon incrementally; no second rewrite.** The plumbing demonstrably
works (52 successful runs; agents do build); every catastrophic failure was a missing feedback
loop, which Phases B–D retrofit. A second rewrite is R10 recurring. The corpus's substrate
kill-criterion ("P0 can't be made reliable within its budget → lean on bought infra") remains
the trigger for a Temporal/LangGraph pivot — it has not been earned yet. The event-sourced
spine (ADR-01) arrives by upgrading the existing journal into an append-only, replayable record,
not by rebuilding the daemon around a new store. *Rejected:* rebuild-on-corpus-architecture now.

**DG-2 — CLOSED (ratified by Artiom, 9 Jun 2026): zero human gates, from day one.** The
recommendation (keep gate 4) was presented with its risks and **deliberately declined**; this
supersedes ADR-04's fourth gate, and the `REQUIRED_GATES` tuple (E16) is correct by decision.
Consequences, engineered rather than hoped:

1. Gates 1–3 + authenticity carry everything; Phase D's compensators are **mandatory and
   blocking**: cross-provider judge (D4), authenticity teeth, positive + negative calibration
   controls, an archived evidence bundle per certification.
2. The human gate is replaced by a **machine circuit breaker, not by nothing**: certifications
   are continuously spot-audited (sampled re-judgement of evidence bundles by a different
   model); if measured false-accept exceeds 2% (CUSUM-tracked), the system **parks further
   certifications** and notifies. Parking, not asking, is the zero-touch failure response —
   it never ships through a known-bad judge.
3. Completion notifications still fire (observability without involvement); no veto window;
   nothing waits.
4. The corpus's hard stop-and-ask on machine-leaving actions (00 §4) becomes **stop-and-don't**:
   with nobody to ask, irreversible/external actions (push to remotes, publish, send, spend)
   are policy-forbidden unless whitelisted per project at intake. That boundary is separate
   from gate 4 and remains.

Reopen criterion: the spot-audit breaker tripping twice in a quarter returns this decision to
the operator with the evidence.

**DG-3 — Model changes only via registry + eval (L5, A2).** On Fable 5 specifically: capability
multiplies through feedback loops; bolted onto an open-loop system it multiplies waste at 2× the
price. Adopt after Phase C, strongest-roles-first per D4's logic (Architect, Overseer,
hard Builder steps via the difficulty cascade). Metric: **tokens-per-certified-criterion** and
retries-per-completion — the premium must pay for itself in fewer attempts on the slices it
serves. The Judge stays cross-provider (D4): a stronger Claude is more reason, not less, to keep
the judge outside the family. *Rejected:* ad-hoc model upgrades on release day.

**DG-4 — Concurrency ratchet (portfolio-level AIMD).** 1 project until first certification;
double only after a clean soak (defined by DG-9, work-denominated — not days); any trailing
window below 80% run-success halves concurrency automatically. Within a project, the 1-agent
cap stays law, not patch.

**DG-5 — Rebuild strategy: Theseus, ratified (9 Jun).** Organs replaced in place, under tests,
inside the running system — no new repo, no parallel core. Each replacement lands as: new organ
+ its drill → cutover behind registry/config → old path deleted in the same change (manifest
row, `10_DELETE_MANIFEST.md`). The system must remain bootable at every commit.

**DG-6 — Depth default: D2.5, "real product at or above industry level", ratified (9 Jun).**
D2 (real backends, real UX, e2e + screenshot evidence, docs, packaged and runnable by a
stranger, zero mocks in the product path) **plus**: (a) intake names an **industry reference
set** per project; (b) the judge's rubric scores parity-or-better against those references on
core feature/UX axes; (c) deterministic security hygiene is clean (bandit/semgrep, dependency
CVEs) — a product is not industry-level with injection holes; (d) performance within
category-typical budgets. **D3 escalation (amended 10 Jun, H4): not opt-in — every project
climbs to D3 (full security audit + standing SLOs) during its forever-improve rounds after
soft-finish.** D2.5 is the certification bar; D3 is the standard post-certification trajectory.
Improvement cycles continue only while each proves a measurable delta worth its tokens.

**DG-7 — Deletion law, ratified (9 Jun): token-economical demolition.** Delete what is
redundant, outdated, legacy-logic, architecturally misfit, or cheaper to rewrite than fix.
Keep what would burn tokens regenerating ~99%-similar output — repair beats re-seed when the
diff-to-target is small. Mechanics: every deletion is a manifest row (path, reason-class,
replacement-or-archive ref); v1 is archived before any deletion (it has **no VCS**); control
paths are deleted only after their replacement's drill is green; provably-dead code needs only
the archive. Projects are dispositioned case-by-case (delete / keep-and-repair / re-seed) by
expected-cost comparison at intake re-scoping.

**DG-9 — The soak bar is work-denominated, not time-denominated (ratified 10 Jun, H1).** The
operator asked the right question: days were a lazy proxy. What a soak must actually prove is
confidence across enough WORK and enough CYCLE DIVERSITY, so the bar is: **≥200 settled agent
runs at ≥95% run-success, AND ≥1 overseer session succession survived cleanly, AND ≥1
usage-window exhaustion handled without escalation, AND zero unresolved BG-5/breaker alarms.**
Wall-clock (~2 days) is the expected envelope those cycles naturally occupy, never the
criterion. A soak that hits the numbers without the cycles has not soaked.

**DG-10 — Second slot + external notification channel (ratified 10 Jun, H2/H3/H5).**
(a) When dubbing-studio certifies, the second project is **situation-monitor, reborn at large
scope** (contract draft: `12_SITUATION_MONITOR_CONTRACT.md`) — multi-domain awareness (world
news, trading, oil, currencies, geopolitics, significant decisions) through a **propaganda/bias
estimator presenting both left- and right-lens framings**; the operator's stated intent: "I am
not simply absorbing info, I am familiarising myself with other people's lenses." The current
`edge` project's disposition leans cull-and-re-seed under this scope (C9.x decision at its
intake). (b) **Telegram is a whitelisted outbound channel** (the stop-and-don't policy's first
explicit exception): `notify()` fans out to the operator's own chat when `state/telegram.json`
exists; desktop notify remains the fallback. (c) **v1 retirement trigger (H5):** archive zip any
time (pure backup); folder deletion (A4) only after BOTH the first certification exists AND
every `port/v1` organ is consumed-in-code or its waiver resolved — "never rely on it again"
made checkable.

**DG-8 — The overseer is a persistent mind whose memory lives on disk; the session is a cache
(ratified direction, 9 Jun, after operator step-back).** The requirement is persistent context
*and* reasoning. What failed in v2 was not persistence but its substrate: continuity rented from
a provider's opaque session store — one malformed UUID cost 11 silent hours. Resolution: extend
`memory/overseer.py` (the CORE+EXTRA handoff already exists — N1, extend don't replace) into a
structured mind: `CHARTER` (immutable) · `BELIEFS.md` (baselines, what-normal-looks-like,
updated every pulse) · `JOURNAL.jsonl` (append-only: every observation/intervention with its
rationale) · per-project `DOSSIER.md`. Every pulse: load beliefs + recent journal (+ resume the
live session when available — the cache hit) → reason → act → **write back**. The 24 h session
reset becomes compaction, not amnesia. This is *more* persistent than a chat session: it
survives resets, is auditable (C2/C3), and the reasoning thread carries because each pulse reads
its own last rationale. BG-5/BG-6 stand unchanged — they guard this mind, they do not
lobotomise it.

## 5. Recovery programme

### Phase A — Freeze & forensics (≤1 day)
Both daemons stay/come down. **Kill v1's supervisor before its orchestrator** (PID 45634 first, then the current child —
56404 as of 21:38 UTC; verify with `ps`) — killing only the daemon invites the supervisor to
resurrect it (up to its 20-restart guard): the same trap diagnosed in v2 this week. **This
fired in reality on 9 Jun:** a kill of child 45637 alone was attempted; the supervisor
respawned the daemon as 56404 (`restart_count` 0→1). Record the weekly-window
reset time. Snapshot both `state/` dirs + journals to archive. Write `RUN_LEDGER.md`: failure
histogram by cause, the 90-retry case study, the burn timeline, incident IDs (feeds BG-7), and
the **v1 burn attribution** — whether the zombie made LLM calls 1–9 June (E11) is settled by its
journal, not assumed. Quarantine the 6 conflict tasks (blocked, with cause). Tombstone-delete
stray artefacts (E13).
**Exit:** ledger committed; no orchestrator process running; every incident has an ID.

### Phase B — Enforcement spine + port ledger (2–4 days)
Extend the spine that already runs (E15) rather than standing one up from zero: add L6
loop-caps, L8 lifecycle smoke + single-PID, L10 failure-cause schema, the boot self-test, and
the BG checks (§3) alongside the existing import-linter contracts, ruff, and architecture suite.
**The first commit of this phase is the boot self-test anchored on `test_every_law_has_a_check`**
— that closes the only window (A→B) still governed by discipline rather than a gate. Register
the supervisor under launchd (KeepAlive) as the external top of the dead-man chain (BG-5), with
L8's startup grace. Execute FOUNDATION §5's
port ledger from v1: triage taxonomy + transient-requeue cap, AIMD admission control, backoff
curve, task/session checkpoints, reasoning-session accumulation, supervisor graceful restart
(fixes "every fix needs a manual bounce", E3), watchdog with BG-4 semantics. Disposition each
item: ported / reimplemented / waived-with-reason.
**Exit:** CI green including architecture suite; port ledger 100% dispositioned; restart drill
passes with no zombies.

### Phase C — Economic layer (2–3 days)
Usage ledger (runs, wall-time, tokens where the CLI reports them — closes E14). Per-task attempt
budget (3, ladder-enforced) and per-task token cap at dispatch. Burn-rate breaker: trailing-2 h
success ratio < 40%, or ≥ 20 runs with zero completions ⇒ pause intake, pulse overseer, notify.
Kill-switch reachable three ways (file, GUI, remote signal) and tested mid-batch. Usage-cap
signal ⇒ pause until recorded reset time; never a task failure. Timeout ⇒ checkpoint-resume
once, then the ladder. Ladder enforced per BG-3; merge conflicts get the **rebase-replan rung**
(new task carrying the conflict hunks against current main), never retry-apply. Re-dispatch the
six quarantined tasks through this machinery.
**Exit:** poison-task drill consumes exactly its budget then terminal-fails with cause;
conflict-pair drill resolves via rebase; kill-switch drill passes; the six tasks dispositioned
(landed or descoped with a written decision).

### Phase D — Verification gates (3–5 days)
Acceptance compiler at intake: criteria → machine-checkable checks (e2e against real backends,
Playwright UX smoke with screenshot evidence, performance budgets) stored in the project's
contract file *before* build tasks are enqueued — including a **definition of abandon** per
criterion (attempt/timebox cap ⇒ descope decision, logged). Gates evaluated by a non-author:
Judge cross-provider per D4 (`codex exec --json`; different Claude family as interim). Per
DG-2 (zero-touch), the **certification spot-audit breaker** is mandatory here: sampled
re-judgement of evidence bundles by a different model, CUSUM-tracked; measured false-accept
≥ 2% parks all further certifications (park, don't ask). The daemon's `pending_user` wait is
removed in the same change. Purity
gate extends L4: no mock/fake-backend imports reachable from the product path (mocks live in
tests only). Every gate verdict ships an evidence bundle (logs, junit, screenshots, judge JSON).
**Calibration with both poles** (05 §2d's judge-calibration pattern, extended to the whole
pipeline): a **negative control** — the gates must honestly fail one currently-"finished"
project — and a **positive control** — a small known-good reference must pass, else a gate that
fails everything would also pass the negative test (false-green traded for false-red).
**Exit:** contract schema versioned; evidence bundles produced; negative control red; positive
control green.

### Phase E — P0 certification on ONE project (1–2 weeks)
`MAX_ACTIVE_PROJECTS=1`. Choose the nearest-to-done project; re-scope it through the intake
funnel (Socratic interrogation → acceptance criteria locked → contract compiled). The cleanup
items (E6: de-duplicate packages, finish the edge rename, fix writing-assistant's
`RecursionError`) become pipeline tasks for that project. Drive to all gates green,
zero-touch (DG-2): certification fires itself and emits a completion notification; nothing
waits on a human.
**Exit = the corpus's P0 bar as amended by DG-2:** completes unattended through all gates
(human gate removed by ratified decision; spot-audit breaker armed);
survives a forced crash with resume-from-step; kill-switch + budget cap halt spend; all
enforcement green; project tree pristine; plus a post-mortem enumerating every human touch,
each becoming an automation item or waiver.

### Phase F — Soak & controlled breadth (2+ weeks)
Chaos drills: `kill -9` mid-task, disk-full, injected rate-limit, killed overseer — all must
degrade safely. 7-day single-project unattended soak: ≥ 95% run-success, zero human touches,
full stop (DG-2). Then 2 projects → re-soak → 4 → 8, per DG-4. Remaining projects re-enter
one at a time through intake re-scoping (the fix for E6's underscoping: real backends, real UX
in the contract, or explicit descope).
**Exit:** each doubling preceded by a clean soak; auto-halve rule armed.

### Phase G — Remote control & maturation (parallel with F)
Signals/queries surface over Tailscale: status, pause, kill, steering signals from phone/Windows
(ADR-02 done properly — sentinel files retire). Then the maturation curve: local-LLM as cascade
tier-0 behind evals; Fable-5 trial per DG-3; PA fast-path rules begin accumulating from the
RUN_LEDGER (P1 of the corpus).
**Exit:** the Da Nang drill — steer from another device in under 30 s; one registry-gated model
change shipped with eval evidence.

## 6. Issues register

| ID | Item | Phase | Exit evidence |
|----|------|-------|---------------|
| I1 | 6 overlapping-diff conflict tasks | C | dispositioned via rebase-replan |
| I2 | 16 × TimeoutExpired | C | timeout drill: checkpoint-resume then ladder |
| I3 | Duplicate dead packages (~1,000 lines) | E | purity + single-package test green |
| I4 | edge rename incomplete; tests don't collect | E | test collection green |
| I5 | writing-assistant RecursionError | E | test collection green |
| I6 | Underscoped products (mocks, CLI-only) | D, E, F | contracts with real-backend criteria; negative control |
| I7 | confirmations/ empty | E | first certification artefact |
| I8 | Stray artefacts (projects/p, pytest caches) | A | tombstoned |
| I9 | Cost ledger $0.00 vs ~$160 imputed | C | usage ledger populated per run |
| I10 | 3% run-success burn | C | burn-rate breaker drill |
| I11 | Conflicts escalated to tray; dead overseer didn't | C, B | ladder ordering; BG-4/BG-5 tests |
| I12 | Overseer chat-resume fragility | B | BG-6 test |
| I13 | Fixes require manual daemon bounce | B | graceful-restart drill |
| I14 | STOP-sentinel/cwd operational trap | B, G | single entrypoint; in-app + remote stop |
| I15 | Runtime/economic enforcement absent (static spine present — E15) | B, C | boot self-test + drills green |
| I16 | v1 port-list unexecuted | B | port ledger dispositioned |
| I17 | Gates defined but toothless (tuple now ratified human-free, DG-2) | D | evidence bundles; spot-audit breaker live |
| I18 | No attempt/token budgets at dispatch | C | poison drill |
| I19 | No reset-aware pause on usage caps | C | cap drill |
| I20 | v1 daemon still running idle on host (supervisor 45634; child respawned as 56404 after a partial kill) | A | both processes stopped, supervisor first |
| I21 | No positive-control reference for the gates | D | positive control green |
| I22 | Overseer pulse context unbounded under BG-6 | B | digest size-bound test |
| I23 | No external watchdog above the supervisor | B | launchd KeepAlive drill |
| I24 | v1's share of the June burn unattributed | A | RUN_LEDGER attribution section |

## 7. Metrics (definitions fixed now, instrumented in C)

run-success ratio (ok runs / all runs) · retries-per-completion · tokens-per-certified-criterion
(falls back to runs-per-criterion until token capture works) · burn-rate (runs/h vs
completions/h) · escalations-per-week reaching the tray · later: PA hit-rate (P1 prediction) and
bugs-per-$ (the north star).

## 8. Non-goals of this phase
No new agents. No substrate swap (see DG-1's trigger). No self-modification (the seam stays
shut). No mobile app (the remote surface in G is API + existing tools). No Fable-5 adoption
before Phase C completes.

## 9. Amendment log (v1.1) & the minimum gate set for Phase E

**v1.1, 9 June:** Diagnosis independently verified against both repos (E9, E11 confirmed;
E15–E16 added). F1 narrowed — v2's static spine exists; the missing enforcement is the kind that
binds behaviour under load. F2 split into proximate (the 8 Jun regression, reverted) and
structural (no caps/budgets) causes — the fixes differ. All seven BG checks pinned to explicit
predicates. BG-5 made graduated (restart before pause; launchd as chain top). BG-6 gained the
bounded-digest companion. BG-7 admits drill IDs; waivers carry owner + expiry. DG-2 reopened as
an operator decision. Phase A kill order corrected (supervisor first). Phase B's first commit is
the boot self-test (closes the A→B discipline window). Phase D gained the positive control.

**v1.2, 9 June (later):** the four rebuild parameters ratified by the operator. DG-2 closed —
**zero human gates from day one**, with the spot-audit circuit breaker replacing the human gate
(park, don't ask) and stop-and-ask becoming stop-and-don't. DG-5 Theseus rebuild-in-place.
DG-6 depth default D2.5. DG-7 token-economical deletion law; `10_DELETE_MANIFEST.md` created.
Phases D–G reworded to zero-touch. Kill procedure updated after the resurrection event
(supervisor respawned the killed daemon as PID 56404, `restart_count` 0→1) — supervisor first.

**v1.3, 9 June (step-back review, operator-prompted):** course correction — the B–D sequence was
over-building governance; the governance gradient is as seductive as the demo gradient and this
document briefly fell for it. "Minimum gate set" replaced by **the hard floor** + failure-driven
hardening; the next milestone is a certified flagship product with the **daemon** doing the
work, not hand-executed phases. DG-8 added: overseer as a persistent mind on disk (session =
cache), extending `memory/overseer.py`. Flagship default: dubbing-studio, by the
60-second-stranger-demo criterion.

**v1.4, 10 June (operator answers H1–H5, first-flight day):** DG-9 — soak bar redefined
work-denominated (≥200 runs at ≥95% + cycle diversity; days demoted to envelope) after the
operator correctly challenged the time proxy. DG-6 amended — D3 is every project's
post-soft-finish trajectory, not opt-in. DG-10 — second slot = situation-monitor at large scope
(dual-lens propaganda estimator; contract draft in 12); Telegram whitelisted as the first
stop-and-don't exception (notify fan-out, config-gated, operator's own chat only); v1 deletion
trigger made checkable (first certification + port ledger consumed). Overseer promoted to
Fable 5 (registry, DG-3). First flight: boot self-test passed on the host; the overseer's first
pulse read the world and reprioritised the re-scope contract on its own authority.

**Conscious cost, accepted deliberately:** this regime front-loads roughly two weeks of
infrastructure before a single certified product, and the demo gradient will fight it daily.
The alternative was tried: it burned a week's window at 3% efficiency.

**The hard floor (v1.3 — supersedes the "minimum gate set").** Re-cut after a step-back review:
the B–D sequence as written **exceeded the corpus's own P0 bar** — governance was over-building
exactly the way features did in the first burn. Mandatory before the flagship runs (days, not
weeks): attempt budget = 3 + the BG-3 input-hash; kill-switch + a simple burn-rate pause
(thresholds, not CUSUM); the BG-1 boot self-test; BG-2 as a bare project cap (= 1, count check);
ported `error_triage` + AIMD (organs already staged); BG-5 basic (missed-pulse notify); the
acceptance compiler + authenticity teeth + cross-provider judge (without these, "impressive"
regresses to stubs under zero-touch); one manual negative control. **Everything else is pulled
in failure-driven:** a deferred check lands when an incident on the flagship path demands it
(BG-7 unchanged — incidents become tests within 24 h). Full BG-4 semantics, launchd, digest
compaction, CUSUM formality, the positive-control harness: deferred to the first soak unless
reality summons them earlier.

## 10. Adoption checklist
1. Copy this file + `RUN_LEDGER.md` skeleton into the live v2 repo; commit.
2. Stop both daemons (A); record the usage-window reset time.
3. Wire BG checks into CI alongside 05's toolchain (B).
4. Work the phases in order; each exit criterion is a drill or a test, not a judgement call.
5. Review this document against the ledger after Phase E — amend laws only with their checks.
