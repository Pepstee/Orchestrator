# TIER-1 FINDINGS — orchestrator-side flaws (L9-forbidden to the overseer; cowork lands them)

*RECONSTRUCTED 18 Jul 2026 by the Fable cowork session. The overseer believed it was appending
this file at `memory/tier1-findings.md`; the file never existed on disk — every append it
narrated left no trace (no quarantine patch either: the writes never landed). Content below is
rebuilt from `state/overseer/journal.jsonl` + `state/overseer/BELIEFS.md`, which held the whole
ledger — the mind survived its own dangling pointer. Landing path: `memory/tier1-findings.md`
(where the beliefs point; continuity IS the files), committed by the operator so the fence
never touches it. Lesson for Sol, standing: AFTER any write that matters, `ls` it. A narrated
write is not a write.*

Protocol (operator-ratified): every orchestrator-side flaw is appended here with evidence seqs
and cowork-ready fix instructions; a cowork session lands fixes host-side; the overseer
verifies ON DISK and marks FIXED-VERIFIED.

---

## F-001 — Criterion burial / criteria carry-forward (P0, 4 instances) — OPEN, fix brief below

**Mechanism.** A validate/judge attempt fails with a specific finding; a DIFFERENT validate
later passes (or an intervene sees green gates and declares the finding "stale"); the judge
gate goes TRUE and the round certifies with the finding still true on disk. Two proven burial
modes: different-validate-passes (instance #3: judge-failed 3× at seqs 4972/4975/4978 on the
directives.py char-blacklist finding, then unrelated validate passed at 5006, gate TRUE at
5022, blacklist still on disk — caught pre-cert by ledger W) and green-gates-stale-call
(cert #9, seqs 5653-54: judge fail 5587 on README.md:118 "1,712 tests" vs 2617 collected;
intervene ran gates, saw green, said stale; certified; claim still on disk at line 118).
Cert ledger: #1 honest, **#2 BURIED** (4870-71), #3-4 honest, #5-6 clean-through, #7-8 honest,
**#9 BURIED**. Interim countermeasure (active): overseer ledger W on every cert — find the last
failing judge cause, verify its TEXT against disk before trusting the cert.

**Fix brief (v2 `control/daemon.py` — one session, small and reversible):**

1. *Thread the finding.* Wherever the daemon enqueues a follow-up validate after a failed one
   (the re-validate path), embed the failing cause durably:
   `payload["carry_forward"] = cause[:500]` on the new task. Match on this FIELD, never on
   title text (the echo-trap lesson: titles quote history; payloads carry intent).
2. *Gate the certification.* In `monitor_projects`, in the `assurance.fully_hardened` branch,
   BEFORE `repo.record_confirmation(project)`: compute the project's last validate-type
   task_result with ok=False (its cause = finding F). If F exists and there is NO later
   validate-type task_result with ok=True whose task carried
   `carry_forward` matching F (compare a normalised fingerprint, e.g.
   `hashlib.sha1(F[:200].encode()).hexdigest()[:12]`, stored alongside the text), then DO NOT
   certify: route through `_advance_stalled(reason="criterion carry-forward: unresolved
   finding: …")` so the overseer gets it — journaled, loud, never silent.
3. *Tests (the contract):* (a) burial repro — validate fails with cause C, unrelated validate
   passes, assert certification is blocked and the reason names C; (b) honest path — a later
   validate carrying C's fingerprint passes, certification proceeds; (c) no-finding path —
   project with no validate failures certifies untouched; (d) replay — the block survives a
   restart (derived from the ledger, no new event kinds needed).
4. Constraint: read-only over existing events; no schema change; the block routes to the
   overseer rather than failing anything terminally. Reversible by deleting the precondition.

**DONE means:** the overseer cites `tests/…carry_forward…` paths in its contract ledger and
marks F-001 FIXED-VERIFIED after watching one real certification pass through the new gate.

## F-002 — lint-imports missing from the gate environment (P1) — OPEN

The L2 layer contract's cross-check (`lint-imports`) is not present/verified in the gate
environment, so the import contract is enforced only where the suite's own layering test runs.
Fix: boot-time presence check with a loud journal line when absent (or pin the suite-side test
as the sanctioned single enforcement and record that decision). One hour.

## F-003 — merge-conflict livelock (P2, UNVERIFIED-CURRENT) — re-verify before spending

Historical shape: conflicting worktree merges re-enqueued in a loop. Marked unverified-current
by the overseer; re-reproduce before fixing.

## F-004 — cause-blind assurance_result events (P3) — OPEN

`assurance_result` events carry pass/fail but not the finding text, forcing forensics through
journal archaeology. Fix: include `cause`/finding summary in the event data at write time.

## F-005 — failure ladder cannot route mechanical lint causes (P2, 2 instances) — OPEN

B904 burned 4 rounds (~1.5h red, seqs ~5449/5494/5513), C408 repeated the shape: a
file:line-named lint cause loops through full replan machinery instead of mapping to a direct
mechanical fix task. Fix: a PA fast-path rule — cause matching `^[A-Z]\d{3} .*:\d+` (ruff-code
+ file:line) enqueues a scoped "fix exactly this lint finding" implement task immediately.
Opposite failure mode to F-001 (cause retained but never routed); the fix must not weaken the
scanner (TRAP: never satisfy a lint gate by disabling the rule).

---

*Verification loop: after landing any fix, tell the overseer/Sol which F-numbers landed and
the enforcing test paths; it verifies on disk and updates this file's status lines (via a
cowork session — this file is repo-committed, so agent edits stay fence-forbidden by design).*
