# Orchestrator v2 — Ratified Decisions & Canonical Registry

*Closes the four open decisions from the charter / synthesis §8. The agent→model table here is
the **single source of truth** (law L5) — agents resolve their model from it, nothing arbitrary.*

---

## D1 — Stack: Python-first, polyglot for optimisation

**Decision.** Python is the orchestration language. **Performance-critical components may be
written in C/C++ (or another suitable language) where profiling justifies it**, behind a clean
interop boundary (native extension or local service with a typed contract).

**Guidance (so this stays disciplined, per the maturation thesis):**
- **Measure first.** A component earns a native rewrite only when an eval/profile shows Python
  is the actual bottleneck — never speculatively (premature optimisation is its own entropy).
- **Likely candidates** when the time comes: the event-sourced store + replay at high volume,
  code-graph traversal/taint queries, the mutation-testing runner, the difficulty estimator's
  hot path. All are leaf components behind clean interfaces — safe to swap to native.
- The **provider/runtime abstraction** keeps language choice a per-component detail, not an
  architecture-wide commitment.

## D2 — Built projects live in a gitignored `projects/` folder

**Decision.** Everything the orchestrator builds lives at `<orchestrator>/projects/<Project Name>/`
(e.g. `projects/Situation Monitor/`), and `projects/` is **gitignored**.

**Why this is clean (resolves the earlier "deliverable pollution"):** gitignore keeps built work
out of the orchestrator's own version control, and **law L4 (deliverable purity)** is enforced by
test — a project tree contains only its own artifacts, never orchestrator scratch (handoffs,
reports, state, logs live under the orchestrator's own state dirs, not in the project). So "inside
the directory" is safe *because* of gitignore + L4, where building at the bare repo root was not.

**Still open (minor):** the v2 *orchestrator code* repo location/name itself (a fresh repo vs.
replacing v1 in place). Proposed: a fresh directory, its own git repo, with this gitignored
`projects/` inside. Confirm at build start.

## D3 — Module size: no hard cap, but a non-blocking god-file guardrail  ⚠️ *clarification*

**You said:** LOC unlimited; ready to spend whatever it takes.

**Important distinction — the LOC budget was never a spending or ambition limit.** It costs
nothing and limits nothing you care about. It existed for *one* reason: to stop **god-files**
re-forming — the exact pathology that made v1's `orchestrator.py` a 4,067-line tangle that no one
(human or agent) could safely change. Removing it doesn't let you invest more in the tool; it just
lets the tangle come back silently.

**Resolution (ratified):** drop the *hard cap* (no build-blocking on size), but keep a **soft
guardrail** — a warning + an automatic **architecture-review trigger** when a file crosses
**700–800 LOC**. Nothing is ever blocked; you're simply *told* when a module is growing into a
god-file, and the Architect/overseer reviews whether it should be split. Honours "spend whatever
it takes" while preventing the single worst v1 entropy. *(Charter L3 is now this soft form.)*

## D4 — Canonical agent→model registry (decided by role)

Assigned by **role stakes + reasoning depth + call volume**, with two hard rules from the
research: **(a)** the Judge must differ from the Builder (anti-collusion, F5); **(b)** the
difficulty estimator overrides defaults *within* the cascade (one signal, three consumers).

**Canonical roster — 5 agents + the meta-agent (Overseer).** Resisting agent proliferation is a
v1 lesson; everything else is a *function/tool/mode*, not a standalone agent.

| Agent | Role | Model | Notes |
|-------|------|-------|-------|
| **Task Manager** | decompose Global Task → step graph; orchestrate | **Sonnet** (→ Opus for complex goals) | the difficulty-triggered **reasoning mode** folds in here |
| **Architect** | guided **"build-your-idea"** intake → confirmable flowchart; completion proposals | **Opus** | highest-stakes design reasoning |
| **Builder** | implement steps | **local/Haiku (easy) → Sonnet → Opus (hard)** | cost-cascade workhorse; the maturation curve migrates this first |
| **Validator / Judge** | gate completion + security/quality review | **OpenAI via Codex CLI** (Go plan; API fallback) | different provider from Builder = true independence (F5); **absorbs Auditor** |
| **Tester** | generate & run tests (incl. mutation/adversarial in the assurance loop) | **Haiku** (→ Sonnet if complex) | mechanical, high-volume |
| **Overseer (meta)** | periodic global sanity · evolves the PA · root-cause/diagnosis | **Opus** | bounded by the laws it enforces |

**Folded into functions/tools (NOT agents):** Reasoner → a difficulty-triggered reasoning *mode*
of Task Manager/Builder · Auditor → part of the Judge + deterministic security gates
(bandit/semgrep) · Diagnoser → an Overseer function · Explorer/Researcher → a retrieval *capability*
(code-graph/web) agents call · Reporter/Digest → deterministic summary functions over the event log
· Clarify → the intake/escalation "ask the user" function · Fan-out → a dispatch capability ·
Monitor → deterministic SPC/CUSUM.

**Anti-collusion, concretely:** the **Judge runs on OpenAI while the Builder runs on Claude —
true cross-provider independence from day one**, the strongest form of F5: no shared training,
no self-enhancement bias, no judge↔builder co-adaptation. Verdicts are still re-anchored against
ground-truth test execution.

**D4 mechanism — Codex CLI headless, on your ChatGPT Go plan** *(corrected, verified June 2026).*
OpenAI's **Codex CLI** now runs headless exactly like Claude Code CLI: **`codex exec --json`** runs
a single session to completion, streams JSONL events to stdout, and exits — the direct analogue of
`claude -p --output-format json`. It signs in with **your ChatGPT plan (Codex is included on Go)**
*or* an API key. So the Judge can be driven by the **£7 Go subscription with no separate per-token
billing**, within the plan's usage limits. Notes: (1) OpenAI *recommends* an API key for heavy
automation/CI and predictable accounting, but subscription sign-in is supported and the Judge is
**low-volume** (≈once per completion); (2) if it ever exceeds the plan's usage limits, fall back to
the OpenAI API; (3) minor known quirks switching between subscription and API-key auth.
**Architecturally tidy:** Builder (`claude` CLI) and Judge (`codex` CLI) are *both* headless-CLI-
with-JSON, so the provider layer is a thin **agent-runner** that shells out to the right CLI per the
registry — true cross-provider independence at near-zero marginal cost, on a subscription you
already own.

**Maturation hook:** **Builder and Tester** migrate first to a **local LLM as cascade tier-0**;
**Architect / Judge / Overseer** stay on the strongest available model longest (highest stakes).
This *is* the maturation curve, encoded in the registry.

> **L5 enforcement:** every agent resolves its model from this table; the
> `test_reported_model_eq_chosen` check fails the build if a running agent's emitted model ≠ the
> table. The table is the only place model assignments may be changed.

---

## Status
**All four ratified.** D1 Python-first + native-where-profiled · D2 v2 lives in its own new local
directory with a gitignored `projects/<Name>/` inside · D3 soft god-file guardrail at 700–800 LOC
(never blocking) · D4 Judge on OpenAI via **Codex CLI headless on the ChatGPT Go subscription**
(cross-provider independence, no extra billing; OpenAI API as overflow fallback). Phase 0's open
decisions are closed; the build can begin with the enforcement-tooling skeleton.
