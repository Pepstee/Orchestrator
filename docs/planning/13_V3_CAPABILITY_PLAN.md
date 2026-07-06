# Orchestrator v3 — Capability Plan

*Written 28 June 2026. Successor to 09 (Recovery & Build Governance). Where 09 fixed the missing
feedback loops that made v2 waste its budget, this document adds the four capabilities that make v3
materially **more capable** — without repeating the over-build mistake (R10). It obeys the same prime
directive: **a capability the system "should" use is a wish; a capability it cannot skip is a gate.***

**Status:** proposed. Each capability ships with its machine-check, in the same change (05 §4).

---

## 1. What changed since 09

| # | Update | Consequence |
|---|--------|-------------|
| U1 | Claude **Fable 5** is public again | DG-3 adoption path reopens; strongest-role-first |
| U2 | The system **ignores its own knowledge base** (graphify + memory both present, neither read nor written) | The single most diagnostic failure: it proves the prime directive — an ungated "should" is ignored |
| U3 | **dubbing-studio certified** (~late May 2026), on GitHub | The pipeline CAN drive a project to full sign-off; the substrate is not broken → *evolve, don't rewrite* |
| U4 | Requirement: **deep, tiered online research** (excavate, not skim) | A genuinely new subsystem, valuable and under-exploited |

## 2. Governing principle

Every one of U1–U4 must be planned as **(capability + enforcing check)**, never as a feature. U2 is the
proof: v2 already has graphify AND a memory system and uses neither, because nothing *forces* it. If v3
adds a research subsystem without a gate that fails shallow research, it will skim exactly as v2 ignores
graphify. **No new capability lands without the check that makes the system use it.**

## 3. The central decision — DV-1: evolve v2, do NOT fork from scratch

**Decision:** reach v3 by **evolutionary inheritance** — harden v2's spine (09), bolt these four
capabilities on as gated subsystems, adopt Fable 5 behind the registry. Call the result v3; reach it by
inheritance.

**Rationale:** U3 shows the plumbing works (a real certification). Every catastrophic failure was a
missing loop, not a broken substrate — a rewrite re-purchases every solved problem (the exact v1→v2
mistake, FOUNDATION §5). A clean-room v3 now is R10 recurring.

**Fork trigger (rejected for now):** a genuine from-scratch v3 is justified ONLY if v2's core proves
unfixable within budget (the corpus's substrate kill-criterion). It has not been earned. **If forked
anyway, the fork is gated on certifying the 09 spine (Phases B–D) on v2 first, then forking carrying the
proven parts** — never fork into an empty repo and start features (how this began).

## 4. v3 capability laws (DV-laws) — capability + machine-check

| # | Law | Machine check |
|---|-----|---------------|
| **DV-2** | **The knowledge base is load-bearing.** One canonical store. The planner MUST read it before planning (injected into context); every task MUST write a structured entry on completion (decision, rationale, learning); a task cannot be marked done otherwise | `test_task_reads_and_writes_kb`: a task whose run did not read the KB and did not append a curated entry fails; boot self-test asserts the KB exists and is non-empty |
| **DV-3** | **Research is deep or it fails.** Every research task emits an evidence bundle with each claim tagged by source tier (see §5); a gate fails shallow work (below minimum Tier-2/3 coverage, link-dumping without extraction, or key claims uncorroborated) | `test_research_evidence_contract`: reject a bundle with < N Tier-2/3 sources or with claims lacking ≥2 independent corroborations |
| **DV-4** | **Model changes only via registry + eval.** Fable 5 (and any model) is adopted strongest-role-first (Overseer, Planner) behind an eval; metric tokens-per-certified-criterion and retries-per-completion must improve on the slices it serves; Judge stays cross-provider | Registry is the single source (existing `test_registry_single_source`); an eval gate blocks promotion without a measured win |
| **DV-5** | **The KB is also the guardian's memory (BG-6 unification).** The curated, compressed KB is the context digest the Overseer rebuilds from each pulse; `--resume` stays an optimisation whose failure is non-fatal | Existing BG-6 test (delete session store, pulse must succeed) now reads the KB digest |
| **DV-6** | **Capabilities ship as isolated modules, gated at the seam.** Each capability is a self-contained module (own package + tests + clean interface) plugged in with MINIMAL core change — but that minimal change is a **mandatory, fail-closed seam-gate** into the critical path (planner read, task-completion check, registry entry), never an optional hook. Modular in build; unskippable at the seam — "a plugin the core doesn't depend on" is exactly how graphify/memory ended up ignored | boot self-test asserts each module's seam-gate is wired and fails CLOSED if the module is absent or unsatisfied; layer-contract test (L2) confirms the module respects the architecture |

**On DV-6, concretely (the modular blast-radius):** the architecture already makes most of this clean-plug.
The **research capability** is a new `agents/` module + one `registry/agents.py` entry (the registry *is*
the plug point — adding a `research` task_type→agent is the whole core change). **Fable 5** is a pure
registry/config change behind the eval — zero structural edits. Only the **KB** needs real seam hooks —
three small *mandatory* edits: planner-reads-before-planning, completion-check-requires-an-entry, and the
boot self-test. Minimal, but fail-closed: skip the KB and the task fails; omit the module and the daemon
refuses to dispatch. That is the line between "may use" and "cannot skip".

## 5. Deep research — the tier ladder (definitions fixed here)

- **Tier 1** — popular open web: mainstream sources, top search results. Breadth, orientation.
- **Tier 2** — depth in the open: open archives (archive.org), open-access journals and their APIs,
  articles, and **non-Western / non-English sources** (translated). This is where the real,
  under-used depth lives; Fable 5's long-horizon synthesis is the right tool for it.
- **Tier 3** — genuinely-public but obscure: low-traffic public pages, niche public datasets, primary
  documents nobody indexes. Included **only where public.**

**Hard boundary (non-negotiable):** v3 will NOT circumvent paywalls, logins, robots/anti-bot
protections, or otherwise access controlled content. "Soft-locked" content behind such barriers is out
of scope — it is a ToS/legal line and unreliable in practice. Tier 1–2 plus *public* Tier 3 is already
far deeper than "nobody uses it"; that is the legitimate edge.

## 6. Sequencing (order is the point)

These attach to the 09 spine and are sequenced **after** it — added before the spine, they will be
ignored exactly as graphify is today.

1. **09 Phases B–D first** (enforcement spine → economic layer → real verification gates). Non-negotiable prerequisite.
2. **DV-2 knowledge base** — the load-bearing store + its read/write gate. Highest leverage; also unlocks DV-5.
3. **DV-4 Fable 5** — Overseer then Planner, behind the eval. Do this before DV-3 so research runs on the strongest synthesis.
4. **DV-3 deep research** — the research capability + evidence contract, exercised first on ONE project (edge / Situation Monitor is the natural fit — it *is* a research product).
5. Re-certify one project end-to-end with all of the above live (the P0 bar, verbatim).

## 7. Decisions (locked 28 June 2026)

1. **KB substrate:** an append-only **markdown decision/learning log is the agent-facing KB**
   (read/write in the loop); **graphify is a derived code-map** built from it, not the primary store.
2. **Research reach:** the Tier-3 boundary in §5 stands — public obscure content yes; paywall/anti-bot
   circumvention no.
3. **Fable role order:** **Overseer first**, then Planner, behind the DV-4 eval.
4. **v3 shape:** **keep evolving `agentic-orchestrator` in place** (DV-1 evolution, not fork).
5. **Build style:** **modular — isolated feature modules with a fail-closed seam-gate** (DV-6).

## 8. Non-goals of this phase

No from-scratch rewrite (DV-1). No self-modification of orchestrator code (L9 stays shut; v3 is built by
inheritance, not self-surgery). No paywall/anti-bot circumvention (§5). No new agents beyond a research
capability. No Fable adoption before the 09 spine and the DV-4 eval exist.
