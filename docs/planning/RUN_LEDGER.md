# RUN_LEDGER — incidents, forensics, and their executable lessons (BG-7)

*Started 9 June 2026. Every incident gets a regression test, a drill, or a waiver{owner, expiry}.
An unresolved incident older than 24 h is a red build (BG-7).*

## 1. The June burn — primary-source forensics (from `state/tasks.events.log`)

**Totals:** 115 ok / 1,573 failed agent runs — **6.8% run-success**.

**By triage class (today's taxonomy, applied retroactively):** transient 1,013 · recoverable 552
· permanent 8.

**Top offenders:**

| Count | Cause | Today's defence |
|-------|-------|-----------------|
| 994 | `RateLimited` (window exhausted, system kept thrashing) | transient budget cap (5) + burn breaker + batch backoff |
| 90 | merge conflict `7c2f873da4a7` → edge — **the 90-retry oscillator, by name** | BG-3 input-hash: refused at attempt 2 |
| 75 | merge conflict `aba8b06c98f4` → writing-assistant | same |
| 67 | merge conflict `f2fccd18455b` → dubbing-studio | same |
| 53 / 46 / 46 / 37 | conflicts → deal-sniper, learning-accelerator, digital-twin, deal-sniper | same |

**v1 burn attribution (the "zombie co-payer" hypothesis): REFUTED.** v1 attempted 78 agent runs
through 9 Jun 19:28 UTC (repair-looping on a warm-start task), every one exiting 1 in ~0.02 s —
the subprocess never reached the provider. Budget contribution ≈ nil. Both v1 processes killed
9 Jun ~21:50 UTC (supervisor first, after the resurrection event).

## 2. Negative control (9 Jun) — the strengthened gates vs three "finished" projects

All three FAIL honestly (the gates work; the certifications were theatre):

| Project | acceptance_exec | authenticity |
|---------|-----------------|--------------|
| dubbing-studio | FAIL — no declaration at all | FAIL — `MockTTSBackend` shipped in BOTH the live `dubbing/backends/mock.py` AND dead `tts_studio/` |
| writing-assistant | FAIL — its declaration is a Python file's CONTENTS: 73 lines run as shell, first is a docstring (exit 127) | FAIL — `MockLLM`/`MockBackend` shipped in 3 places |
| digital-twin | FAIL — no declaration | FAIL — `MockLLM` in both live `privana/` and dead `panalytics/` |

**Positive control:** the gate-fixture projects (real declaration, real output) pass the same
gates — both poles calibrated; we did not trade false-green for false-red.

## 3. Incident → executable lesson (the BG-7 ratchet)

| Incident | Test / drill |
|----------|--------------|
| 90-retry conflict oscillator | `test_identical_deterministic_reattempt_refused`, `test_rebase_changes_inputs_and_permits_reattempt` |
| Restart laundering retry budgets | `test_restart_cannot_launder_the_budget` |
| Unbounded transient requeue | `test_transient_requeues_are_finite`, `test_revival_respects_the_transient_budget` |
| Burn at 6.8% with no alarm | `test_burn_breaker_trips_on_collapsed_ratio` (+ restart-durable pause) |
| Stub certification via builds-done proxy | `test_no_declaration_fails`, `test_mock_path_is_refused`, `test_every_declared_criterion_must_pass` |
| Dead overseer, silent for 11 h | DG-8 mind tests (`test_observe_wakes_with_mind_and_writes_back`, `test_failed_pulse_leaves_a_trace`) + BG-5 (`test_pulse_health_alarms_*`) |
| Malformed session UUID | canonical-UUID guard (pre-existing, `memory/overseer.py::_is_canonical_uuid`) |
| Repeat-alert spam (5,384×, v1) | once-per-episode alarms (`test_pulse_health_alarms_on_wedge_once_and_clears`); LOC guardrail descoped from archives |
| Supervisor resurrection on partial kill | manifest §1 procedure (drill: observed live, 9 Jun — child 45637 → respawned 56404) |
| **11 Jun overnight integration wedge:** all 8 project repos unmergeable — legacy baselines tracked `__pycache__` artefacts which gate-runs dirty in the MAIN tree, plus crash residue (`AUTO_MERGE`); every worktree integration failed deterministically and finished work was discarded at merge (incl. the overseer's completed 227-tests consolidation). Overseer diagnosed it precisely (pulse 10) but cannot touch main-tree git state from its worktree. Night totals: 21 ok / 71 fail; burn breaker tripped 3× (worked); PA terminally killed the old conflict looper (`pa:escalate`) | `heal_repo()` now runs before EVERY integration (abort stale merge, untrack artefacts, snapshot strays — preserved, never discarded) + artefact `.gitignore` at baseline; `test_integration_heals_a_wedged_main_tree`; live repos healed by hand 07:30 UTC, 11 Jun. Incident → executable lesson in under 30 minutes (BG-7) |

## 4. Open / pending

| Item | Owner | Due |
|------|-------|-----|
| AIMD admission control | waived — Artiom | expires at first 7-day soak |
| edge rename repair (C7), writing-assistant recursion (C8) | flagship/re-scope pipeline | Phase E/F |
| C9.x project dispositions | intake re-scoping | per project |
| v1 estate archive + delete (A3/A4) | operator | when convenient |
| Directive race (overseer pulse 3, 11 Jun): same-pulse `abandon` + `enqueue` processed together — the abandon swept the overseer's own fresh recovery plan (seq 5712). Ordering/atomicity fix needed in `process_overseer_control` | next hardening slice | before breadth widens |
