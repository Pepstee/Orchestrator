# V3 Build Charter — instructions for the orchestrator to build its successor

*This is the contract you (the v2 orchestrator) build against. You are building a SEPARATE product —
a fresh orchestrator, v3 — in its own directory `projects/orchestrator-v3/`. This is NOT
self-modification (L9): you never touch your own running code; you build a new codebase as a product,
exactly like any other project. Build it spine-first, inherit the proven parts verbatim, and let each
slice pass its gates before the next begins.*

---

## 0. Mission

Build `orchestrator-v3`: a clean, autonomous software orchestrator that supersedes v2. It must reach,
by its own gates, the v2 P0 bar — drive ONE real project end-to-end through four gates unattended,
survive a forced crash with resume-from-step, and halt on its kill-switch and budget cap — while
baking in the v3 capabilities (load-bearing KB, deep research, dev-mode fence) from day one.

Why fresh, not a patch of v2: to escape recurring git-lock/conflict/entropy in the v2 tree, and to make
the KB load-bearing and the enforcement spine present *before* features (the ordering v2 skipped).

## 1. Laws the build MUST obey (each is gate-checked)

1. **Enforcement before features (BG-1).** No slice past Slice 2 begins until the enforcement
   toolchain (ruff + pytest + lint-imports layer contract + boot self-test) is green. If the suite is
   missing or red, the boot self-test refuses to dispatch.
2. **No mocks in shipped product paths (L4/authenticity).** Mocks live in tests only. The authenticity
   gate scans shipped code for `Mock*`/`fake`/`dummy`/stub and fails on a hit.
3. **Done means demonstrated, not asserted.** Every acceptance criterion is *executable* — it runs the
   real product and checks a real output. A green unit suite is necessary, never sufficient.
4. **One writer per project tree.** `claim_next` caps concurrency per project at 1 by default — no
   intra-project merge conflicts.
5. **Every failure changes inputs (BG-3).** The failure ladder is repair → replan → escalate; never
   retry the same (prompt, base-state) twice. Merge conflicts are bounded-retry then surfaced, never
   looped.
6. **Total state machine.** Every (status, event) pair defined; illegal pairs are no-ops. Replay never
   crashes.
7. **Guard the guardian (DV-5/BG-6).** The overseer's memory lives on disk (the KB digest); `--resume`
   is an optimisation whose failure is non-fatal. Session ids are canonical dashed UUIDs.
8. **Capabilities are load-bearing, gated at the seam (DV-2/DV-6).** The KB and research modules plug in
   with a MANDATORY fail-closed seam-gate, never an optional hook.
9. **Operators develop out of the daemon's path (DV-7).** A `state/DEVMODE` sentinel whitelists the tree
   for the self-mod fence AND disables agent auto-apply while set.

## 2. Inherit verbatim (port, do not reinvent)

Copy these from v2 / the seed, adapting only import paths. They are proven; reinventing them is waste
(FOUNDATION §5, the port v2 itself skipped):

- **Core + spine (Slice 1, already seeded):** `core/models.py` (with `AgentResult.knowledge` native),
  `core/state_machine.py` (total), `infra/atomic_io.py` (L7), `infra/event_store.py`,
  `dispatch/repository.py` (replay, cap, reclaim). Green: 9 tests.
- **KB module:** `memory/knowledge.py` + its tests (append-only markdown, recall/record/digest).
- **Research module:** `agents/researcher.py` + `validation/research_contract.py` + tests.
- **Failure taxonomy:** v1's `error_triage.py` (TRANSIENT/RECOVERABLE/PERMANENT, requeue cap 5, backoff).
- **The laws + gate designs:** the DV-laws (`docs/planning/13`), the module specs (`14`, `15`), the
  quality charter, the recovery-plan gates (`09`).

## 3. The slice sequence (task graph — each slice depends on the previous)

| # | Slice | Ships when (executable acceptance) |
|---|-------|-----------------------------------|
| 1 | Core + spine | *(seeded, green)* models + total SM + event log + repository; ruff+pytest green; `replay()` reconstructs state; per-project cap enforced |
| 2 | Enforcement toolchain | `lint-imports` layer contract passes; `charter/laws.py` (laws-as-data) + `test_every_law_has_a_check` green; a boot self-test that **refuses to dispatch** when the suite is missing/red (prove it: hide a test, boot refuses) |
| 3 | Agent contract + runner + registry | `agents/common.py` (payload stdin → one AgentResult stdout); `dispatch/runner.py` routes task_type→agent via `registry/agents.py`; `test_registry_single_source`; a dummy agent runs end-to-end through the runner |
| 4 | Dispatcher + pool + failure ladder | `run_concurrent` drives ready tasks with the per-project cap; failure ladder (transient requeue → bounded retry → escalate); a poison task consumes exactly its retry budget then terminal-fails (drill); merge-conflict is bounded, not looped |
| 5 | The gates | completion contract = tests ∧ acceptance ∧ judge ∧ authenticity; authenticity/no-mock purity gate; acceptance-by-execution; cross-provider judge. **Negative control: the gate set fails a deliberately-stubbed sample project AND passes a known-good one** |
| 6 | Economic layer | budget cap + kill-switch reachable 3 ways and tested mid-batch; per-task attempt + token budgets at dispatch; burn-rate breaker (trailing success ratio < 40% ⇒ pause + notify); usage-cap (`exited 1`) ⇒ transient pause-until-reset, never a task failure (drill each) |
| 7 | Load-bearing KB (port) | `memory/knowledge.py` in; the three fail-closed seam-gates wired: a task cannot be marked done without a KB entry, the planner's context includes `recall()`, the boot self-test asserts both (prove each fails closed) |
| 8 | Deep research (port) | `agents/researcher.py` + `validation/research_contract.py`; a Tier-1-only / link-dump / uncorroborated / paywalled bundle FAILS the gate; research findings land as KB entries; runs under the Slice-6 budget |
| 9 | Overseer + daemon + supervisor | persistent overseer (disk memory via KB digest, canonical UUID, `--resume` non-fatal); supervised `run_forever` loop with STOP at repo root; DV-7 dev-mode sentinel. **P0 CERTIFICATION: build ONE real sample project end-to-end through all 4 gates unattended; forced `kill -9` mid-task resumes from step; kill-switch + budget cap halt spend** |
| 10 | Remote control + GUI | token-authed GUI (health, projects, NEEDS-YOU tray); notifications + a signals/queries surface reachable over SSH/Tailscale; stop/confirm from the phone |

## 4. How to feed it to the orchestrator (one slice at a time)

Feed slices in order. Do NOT enqueue all ten at once — depth before breadth (BG-2). Confirm/certify each
slice green before dropping the next.

```
python3 -m control.intake \
  "Build orchestrator-v3 Slice 2 — the enforcement toolchain — in projects/orchestrator-v3/, on top of
   the seeded core+spine. Inherit v2's enforcement patterns; do not reinvent." \
  --project orchestrator-v3 --plan \
  --accept "lint-imports passes a 3-tier inward-only layer contract (core<-infra<-dispatch<-...)" \
           "charter/laws.py declares every law as data; test_every_law_has_a_check is green" \
           "a boot self-test refuses to dispatch when the test suite is missing or red — proven by a test that hides a required test and asserts the refusal" \
           "ruff + pytest + lint-imports all green; no mocks in any shipped module"
```

Repeat per slice, swapping the goal and `--accept` block from §3. Seed Slice 1 first (copy the
`orchestrator-v3/` foundation into `projects/orchestrator-v3/`) so the orchestrator starts from green.

## 5. The v3 done bar (the whole project)

v3 is done when, by its OWN gates: it drives one real sample project end-to-end through all four gates
unattended; survives a forced crash with resume-from-step; halts on kill-switch and budget cap; the full
enforcement suite is green; the KB and research gates are load-bearing (proven fail-closed); and the tree
is pristine (no dead packages, no stubs). Then — and only then — is v3 a candidate to take over from v2.

## 6. Why slicing makes this tractable (and honest about the risk)

Building an entire orchestrator is far beyond any single project v2 has completed, so it is attempted the
only safe way: as ten small, independently-certifiable projects, enforcement-first, each gated before the
next. If v2's output is weak on a slice, the gates catch it there — cheaply — instead of compounding. If a
slice cannot be certified within its budget, that is the signal to intervene on THAT slice, not to abandon
the whole. This is the discipline the corpus prescribes (R10, 07 §8.3), applied to the biggest build of all.
