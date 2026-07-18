# FIRST EXTERNAL PRODUCT — Travel Designer (flight-cost core)

*Goal specification for orchestrator-v3's first non-self build. Staged here per the read-only
law; load into v3's intake the day the Part IV completion contract (FABLE_V3_DESIGN_REVIEW.md)
holds. Drafted 18 Jul 2026 with the operator; criteria written to be executable by the DG-6
acceptance gate and un-goodhartable by construction.*

## Product, one sentence

A local tool that watches flight prices for the operator's defined legs, keeps a durable
replayable price history, and tells him — with evidence — when to buy and which
date/airport/route permutation in his flex window is cheapest.

## Why this scope

The operator flies constantly (currently mid multi-leg trip; Jakarta→Korea is unbooked TODAY,
more legs follow, long-haul travel is a standing pattern). Flight savings are recurring,
measurable money — the product pays for itself on its first correct "wait, then buy at X" call.
Itinerary/planning features are explicitly OUT of v1; price intelligence is the whole product.

## The immediate real case (maiden acceptance run)

Leg: **CGK (Jakarta) → Seoul (ICN/GMP)**, one-way, date window supplied by the operator at run
time. The first certified run must fetch live fares for this real leg and produce the decision
report. If the tool's report leads to the actual ticket purchase, the product has demonstrated
value before the factory's paint is dry.

## Non-goals (v1) — refuse scope creep at the planner level

- NO booking or payment execution (advice only; the operator buys).
- NO scraping of sources that prohibit it — no Google Flights scraping, no anti-bot arms race.
- NO accounts, no server deployment, no multi-user anything. One operator, one machine.
- NO itinerary/hotel/activity features.

## Architecture constraints (match the factory's proven idioms)

1. **Price-source port**: a closed, manifest-like interface with at least ONE real
   implementation against a genuinely free API tier (Amadeus Self-Service is the default
   candidate; Kiwi Tequila acceptable; the builder verifies the chosen API's current terms and
   free-tier reality as its first task — assumptions about external systems must be verified
   against reality, not documentation memory).
2. **Event-sourced price log**: every observed fare is an appended JSONL event
   (ts, source, leg, date, fare, currency, metadata); all views (history, min-in-window,
   alert state) derive from replay. Corrupt/foreign lines skipped, never fatal.
3. **Flex-window optimiser**: given a leg + ±N-day window + optional nearby-airport set,
   report the minimum observed fare and its permutation, with the evidence rows.
4. **Threshold + trend alerts**: "fare crossed below X", "fare rose two consecutive polls after
   a minimum" — written to a durable report file (stdout + file in v1; Telegram is a LATER
   module, not v1).
5. **One-command run** on the operator's machine: `python3 -m traveldesigner poll` and
   `python3 -m traveldesigner report` (or equivalent) — stdlib-only bias, no framework.
6. API credentials via env var / local config file, never committed, never logged.

## Acceptance criteria (the DG-6 file — executable, with negative controls)

1. `poll` against the configured real source fetches live fares for an operator-supplied leg
   and appends ≥1 price event; run twice, the log holds both observations and `report` derives
   from replay alone (delete any cache first — the log is the only state).
2. A seeded price-history fixture drives the UNIT tests for optimiser and alerts — but the
   ACCEPTANCE path must hit the real source: any acceptance command containing mock/fixture/
   stub tells FAILS the gate (the acceptance_exec mock-tell rule is the negative control).
3. Flex-window correctness proven adversarially: a history where the cheapest fare sits at the
   window edge, in a nearby airport, and on a different day than the naive minimum — the
   optimiser finds it; a deliberately poisoned non-optimal answer FAILS the check.
4. Alert correctness on replay: a history crossing the threshold fires exactly one alert;
   re-running `report` does not duplicate it (idempotent on replay).
5. Kill mid-poll (SIGKILL) leaves a log the next run reads without error and without losing
   prior events (torn final line tolerated — the factory's own event-store standard).
6. The maiden run on the operator's machine, CGK→Seoul, real window, produces the decision
   report he actually uses. This criterion is checked by the OPERATOR, recorded as a
   confirmation — the one human gate, because "a real user used it" is the product claim.

## Verification-integrity notes for the tester/judge

- The price source WILL be flaky/rate-limited: transient source failures must be loud,
  classified, and never fabricate a price event. An empty poll is an empty poll, not a zero fare.
- Currency handling is a correctness trap (IDR fares are seven digits): store currency with
  every event; never compare across currencies without explicit conversion; the optimiser
  refuses mixed-currency comparison rather than guessing.
- Timezone/date traps: departure dates are local to origin; the poll timestamp is UTC; tests
  must include a leg where those differ.

## Sequencing

1. Load this goal the day v3 self-certifies against Part IV (or, if quota pressure demands,
   as v3's P0-drill *second* project — after the sample-project drill, never instead of it).
2. Expected build size: small (one module tree, ~10-15 files) — bounded by design so the
   completion contract closes in days.
3. Product #2, already queued behind it: Northern Ray client components (spec pending the
   owner questionnaire) — the revenue build, on a factory with one certification behind it.
