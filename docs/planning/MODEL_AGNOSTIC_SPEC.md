# MODEL-AGNOSTICISM SPEC — ladders for every agent, survival past 8 August

*Drafted 18 Jul 2026 (Fable cowork session, final deliverable). Operator situation: BOTH Claude
20x Max AND GPT 20x Max until **8 Aug 2026**, after which the Claude subscription ENDS. The
Fable wall (19 Jul) was the rehearsal; 8 Aug is the extinction event. This spec feeds v3 as
amendments to the open slices / the first improvement goal, and its criteria are written as
drills. Companion to V3_CONTRACT_DECISIONS.md point 5 (codex seam, already ratified).*

## Doctrine (one paragraph)

No agent depends on one model; no role depends on one provider; no assignment outlives its
evidence. Every agent resolves against an ordered LADDER of (provider, model) rungs; rung 0 is
the strength-assignment, later rungs are survival. Stepping down is automatic, loud, and
journaled; stepping back up is automatic when the better rung recovers. A model's death
(walled, delisted, sub expired) is a routine event the fleet absorbs without an operator in
the loop — proven by drills, not asserted.

## 1. Provider seam completeness

`infra/llm.py` supports a closed provider catalogue: `claude` (CLI), `codex` (CLI), `ollama`
(local HTTP). Each provider entry carries as DATA: auth remedy text (the exact re-auth command
— never another provider's), session-resume capability, cost-reporting capability, and its
failure signatures for triage. The provider-correct-remedy rule is a test: an auth error's
message must name its own provider's remedy (the 16-17 Jul phantom-alert lesson, now law-shaped).

## 2. Ladders for every agent (generalise v2's overseer pattern)

`AGENT_MODELS` becomes `AGENT_LADDERS: dict[agent, list[rung]]`. Semantics ported from v2
(proven 15-18 Jul through two live successions): step down on ANY provider fault
(RateLimited, RuntimeError, TimeoutExpired), restart at rung 0 each call so recovery is
automatic, `served_by`/`rung` journaled on every serve, engage/recover transitions notified
once. Env override `AGENTIC_<AGENT>` pins one model and disables the ladder (the outage lever,
receipt-exempt, unchanged).

Default ladders — **until 8 Aug** (exploit both subs by strength):

| agent | rung 0 (strength) | rung 1 | rung 2 |
|---|---|---|---|
| task_manager | claude sonnet | codex | ollama (best local) |
| builder | claude sonnet | codex | ollama |
| tester | codex (cross-provider from builder) | claude sonnet | ollama |
| judge | codex Sol (cross-provider, F5) | claude opus | — (see §4) |
| overseer | codex Sol (phase 2, live) | claude opus | — |
| researcher | claude sonnet | codex | — |
| mechanical/triage tier | ollama local | claude haiku | codex |

**After 8 Aug** (claude rungs die): every claude rung is removed by the availability ledger
(§5), not by an edit — the ladders above must already survive with rung 0 mostly codex and
ollama beneath. The drill in §6 proves it in advance.

## 3. Strength assignment is evidence, not opinion (A2)

Initial rung-0 choices above are judgement; they harden or change ONLY through benchmark
receipts. v3 already has the machinery (`benchmark_ref`, `assignment_has_receipt`, the
model-change-requires-receipt architecture test): extend it per-RUNG — every (agent, provider,
model) rung carries a receipt; serving from an unreceipted rung is permitted in outage but
journaled as `unbenchmarked_service` so the eval harness knows to backfill. Promotion/demotion
between rungs = a receipt delta, reviewed like any model change.

## 4. Anti-collusion (F5) under provider loss — decide the degradation NOW

Cross-provider judging survives until 8 Aug for free (two frontier subs). After 8 Aug,
same-provider judge/builder is a KNOWN DEGRADATION. Ratified mitigation, in order:
(a) **API-key Claude for the judge only** — subscription death ≠ API death; judge calls are
small and few, so metered opus-as-judge costs single-digit dollars a month and preserves F5
outright. This is the recommended path; wire `claude` provider to accept an API-key env as an
alternative to CLI auth for exactly this.
(b) If (a) is declined: judge = different MODEL same provider + the eval-gate's
consecutive-PASS variance rule, recorded as a deferred-law degradation in the constitution
(the F-9 lesson: the constitution says so, or it lies by silence).

## 5. The availability ledger (the Fable lesson, mechanised)

A durable `state/model_availability.json`: per (provider, model) — alive | walled | expired,
last_probe ts, evidence (the triage class that killed it). Rules: a PERMANENT-class
invalid-model/auth-dead signature marks the rung dead immediately (ladders skip dead rungs); a
daily cheap probe (one-token call) revives or confirms; a sub-expiry date can be entered in
advance by the operator (8 Aug goes in NOW) so the ladder steps down at the boundary without a
single failed call. All transitions journaled and notified once.

## 6. Drills (certification criteria — the spec is DONE when these pass)

1. **Rung-death drill**: kill rung 0 for every agent (fake PERMANENT signature) mid-run; the
   fleet completes its work on lower rungs; journal shows one engage notification per agent,
   zero operator involvement, zero lost tasks.
2. **Provider-extinction drill**: mark ALL claude rungs expired in the availability ledger;
   run the P0 sample project end-to-end; it certifies on the surviving providers. This is the
   8 Aug rehearsal and MUST pass before 8 Aug.
3. **Recovery drill**: revive the dead rungs; next calls serve from rung 0 again with a single
   recover notification.
4. **Remedy-text drill**: force an auth error per provider; every alert names its own
   provider's re-auth command.

## Sequencing

- Points 1, 2, 5 are amendments to the open slices (llm seam + registry are already under
  construction in 23-26); point 3 extends existing eval machinery; point 4(a) is an operator
  account action (get the API key before 8 Aug).
- Enqueue as the FIRST improvement goal if the slices are closed by the time this lands.
- The 8 Aug date goes into the availability ledger the day the ledger exists.
