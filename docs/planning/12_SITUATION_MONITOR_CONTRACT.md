# 12 — Situation Monitor: contract draft (second slot, ratified DG-10a)

*Status: DRAFT, 10 June 2026. Enters the intake funnel only after dubbing-studio certifies
(BG-2). The Socratic intake refines this into locked acceptance criteria; nothing here
dispatches yet. The current `edge` project (old situation_monitor, crypto-leaning) leans
cull-and-re-seed under this scope — final disposition at intake (manifest C9.x).*

## The operator's intent, verbatim anchor

> "It needs to be really big scope — not only crypto, but world news, trading, oil, currency,
> geopolitics, latest significant decisions, all passing through a propaganda % estimator.
> I want to know both the right-wing and left-wing world. I am not simply absorbing info, I am
> familiarising myself with other people's lenses through which their worldview may become more
> understandable. If I was fed purely leftist propaganda then the riots in Belfast would
> probably terrify me. The Situation Monitor is meant to inform me on both practical and
> useful info."

The product is therefore **not a news aggregator** — it is a *lens instrument*: the same event,
seen through opposing framings, with the spin made measurable.

## Scope (domains)

World news · geopolitics · markets/trading · oil & energy · currencies · significant
governmental/regulatory decisions · (crypto demoted to one domain among many).

## Core mechanisms (to be refined at intake)

1. **Ingestion** — real public sources across the political spectrum (RSS/APIs, free tiers;
   read-only fetches whitelisted for this project at intake — DG-2.4 applies to anything beyond
   reads). Source spectrum must be *declared and balanced by design*, not emergent.
2. **Propaganda estimator** — per-article: a propaganda/spin percentage with a visible rationale
   (loaded language, omission, sourcing asymmetry, emotional framing), plus a lens
   classification (left / right / centre / state-aligned / other). The estimate must be
   *explainable* — a number with receipts, never an oracle.
3. **Dual-lens view** — the signature surface: one event, two columns — how the left-lens
   outlets frame it and how the right-lens outlets frame it, with the estimator's annotations
   inline. The Belfast test: a story that one lens renders terrifying must be readable in both
   renderings side by side.
4. **Practical layer** — market/FX/oil movements and significant decisions presented as
   actionable awareness (what changed, who it affects, what to watch), not commentary.
5. **Digest** — a daily Telegram digest (channel already whitelisted, DG-10b): top events in
   dual-lens summary + practical movers.

## D2.5 bar (per DG-6, with D3 escalation after soft-finish)

Real backends only (live feeds, no fixture corpora as product); web UX a stranger can use
(event stream, dual-lens view, estimator rationale on demand); `acceptance` criteria that
execute the real pipeline end-to-end on live sources and produce the dual-lens render;
industry reference set: **Ground News** (the lens-comparison reference), AllSides
(bias-rating methodology), plus one terminal-style market dashboard for the practical layer —
judge scores parity-or-better on the core flow *one event → both lenses → spin estimate →
practical takeaway*.

## Open questions for its intake (not now)

Estimator calibration (against what ground truth — AllSides/MBFC ratings as priors vs
self-anchored rubric?) · source list and balance policy · refresh cadence vs token budget ·
how much history to retain · whether the digest is fixed-time or event-driven.
