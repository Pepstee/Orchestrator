# Orchestrator v2 — Foundation Charter

**Status:** foundation phase (pre-code). This document is the constitution. Code
that violates it does not get written; tooling rejects it. Everything else in the
project — feature inventory, module map, the build itself — hangs off this file.

**Carried forward from v1:** the substrate works; the *discipline* didn't hold.
v1 had an excellent written ruleset (N1–N12) and still drifted into duplicate
`AgentResult`s, god-files, and three-layer model-assignment drift. The single
lesson that shapes v2: **a rule without a machine check is a wish.**

---

## 1. Vision & scope

**What v2 is:** a reliable, observable, autonomous multi-agent orchestrator that
takes *one goal* for an *external project*, decomposes it (via a task-manager
agent) into hundreds of small, immediate steps, routes each to the *specialised
agent* that owns it — each running the *deterministic model its role demands* —
and drives the goal to completion with full auditability and crash recovery.

**Nothing in it is arbitrary.** Model choice, agent routing, retry budgets,
file locations — all are declared once, in a single source of truth, and enforced.

### In scope (v1 of v2)
- Goal intake → decomposition → dependency-ordered dispatch.
- Specialised agents with deterministic, registry-declared model assignment.
- Builds into **external project repos**, cleanly isolated from orchestrator state.
- Observable: structured event log, live status, legible failures.
- Recoverable: atomic state, crash-safe resume, bounded retries.
- Bounded autonomy: every loop has a cap, a budget, and a kill-switch.

### Deferred (designed-for, not built in v1)
- **Self-modification** (the orchestrator editing its own code). It lives behind
  a clean seam, OFF by default, never in the critical path. v1's instability was
  overwhelmingly *self-development machinery reacting to its own state* — so it is
  quarantined until the core is proven.

### Explicit non-goals
- A self-improving system in v1.
- Feature parity with v1 on day one.
- Realtime infra, databases, or distributed execution (file-based, single-node —
  the v1 substrate proved this is enough).

---

## 2. Prime directive

> **Every architecture law ships with an enforcement mechanism — a linter rule, a
> CI test, or a registry. If a law cannot be machine-checked, it is not a law.**

This is the difference between v1 and v2. v1's rules were prose in a CLAUDE.md;
entropy beat them. v2's rules are executable.

---

## 3. Architecture laws (inviolable)

Each law states the rule, the v1 failure that motivates it, and how it is enforced.

| # | Law | Motivating v1 failure | Enforcement |
|---|-----|----------------------|-------------|
| **L1** | **Single source of truth.** Each responsibility has exactly one canonical definition (agent→command, agent→model, task schema, config). | `AgentResult` defined twice and diverged; model intent in a comment that the code contradicted. | Registries as Python modules; a CI test asserts no duplicate definitions and that the comment/registry/runtime agree. |
| **L2** | **Dependency arrow points inward.** `core ← infra ← queue ← dispatch ← control ← edge`. Nothing inward imports outward. | v1's whole module surface was the API; any rename broke 5 consumers. | `import-linter` contract in CI; build fails on a back-edge. |
| **L3** | **Module size budget.** No file over N LOC (start N=500). | v1 god-files: orchestrator.py 4,067 LOC, dashboard.py 2,650. | Architecture test fails the build when any file exceeds the budget. |
| **L4** | **Deliverables are pristine.** The external project repo NEVER contains orchestrator scratch (handoffs, build reports, state, logs). | The situation-monitor run leaked `context/handoffs/`, `reports/build_report_*`, `planner_blocked_*` into the deliverable. | Orchestrator bookkeeping is rooted outside the project; a test asserts the project tree contains only declared artifacts. |
| **L5** | **No arbitrary choices.** Model-per-agent, routing, budgets are declared in a registry, not chosen ad-hoc. The reported value must equal the chosen value. | Model drift: builder documented sonnet, coded haiku/opus, logged sonnet; reporter defaulted by accident. | `agent→model` registry; a test asserts every agent resolves a model from it and that the emitted usage event's model matches. |
| **L6** | **Bounded autonomy.** Every autonomous loop has a max-iteration cap, a cost budget, and a kill-switch. No action can self-amplify. | Overseer parse-failure loop with no backstop; self-repair storm; ~$1 burned on zero user work. | Each loop carries an explicit cap; tests assert termination; a global cost cap + kill-switch sentinel are mandatory and tested. |
| **L7** | **File preservation.** Writes are atomic (temp+fsync+rename); deletes go through tombstones with a recovery path; no destructive op without one. | (Preserve from v1 — this part worked.) FUSE truncation/permission handling. | All persistence goes through one IO module; a test forbids raw `open(...,'w')`/`unlink` outside it. |
| **L8** | **One supervised entrypoint; no false alarms on startup.** Exactly one way to launch; health checks never fire during a startup grace; soft-stop cannot resurrect. | False `no_heartbeat` storm from launching the daemon without its supervisor; zombie/duplicate processes on soft-kill. | Single launcher script; startup-grace before health escalations; a single PID lock; a stop that hard-stops; smoke test of the full lifecycle. |
| **L9** | **Self-modification is quarantined.** It is an isolated, optional module, OFF by default, never on the critical path of user work. | v1 self-development monopolised agent slots and hijacked runs. | Feature flag default-off; `import-linter` forbids the core importing the self-mod module; test asserts user work is never starved by self-mod. |
| **L10** | **Every failure is self-explaining.** A failed step's event carries the cause (stderr/exit/contract violation), not just "failed". Cross-agent contracts are explicit, never implicit. | "Always a different thing" = an observability gap; the planner's hidden explore-prerequisite was an implicit contract. | Failure events schema requires a `cause`; a test rejects empty causes; agent input/output contracts are typed and validated. |
| **L11** | **State machine is total and correct.** Every legal transition is defined; dep-waiting tasks have a real state. | `queued→blocked` "invalid transition" spam every second on dep-waiting tasks. | The transition table is exhaustive; a test enumerates every (state, event) pair. |

These are the floor, not the ceiling. New laws are added the same way — with an
enforcement mechanism — never as bare prose.

---

## 4. v1 lessons catalogue (battle-hardened knowledge)

### 4a. Preserve — proven, port the *concept* (reimplement cleanly)
- **File-based queue, atomic status-dir transitions.** Renames between
  `queue/in_progress/done/failed/blocked`. Simple, debuggable, crash-safe.
- **Atomic IO with a retry ladder + tombstones.** `mkstemp`+`fsync`+`os.replace`
  with backoff; failed deletes degrade to skippable 0-byte tombstones.
- **Agent = one-shot subprocess.** JSON payload in, exactly one `AgentResult`
  line out, exit. The process boundary is the cleanest decoupling v1 had — keep it.
- **Dependency-gated task graph** with stable IDs.
- **Crash recovery:** reclaim `in_progress` on startup; per-task checkpoints;
  idempotency keys; append-only ledgers.
- **Event log + size-based rotation** as the audit trail.
- **Three-tier safety policy** — shelved with self-modification, but the concept
  is sound and returns when self-mod does.
- **Supervisor heartbeat + watchdog** — *the idea* is right; v1's bugs were in the
  details (see below), which the 2026-05-25 stress report already catalogued/fixed.

### 4b. Never repeat — failures observed directly
- **Self-repair storm from a false `no_heartbeat`** when launched without the
  supervisor. → L8.
- **Overseer parse-failure loop with no backstop**, self-amplifying into
  escalations + self-development. → L6.
- **Self-development monopolising the run** and starving user work. → L9.
- **Model-assignment drift** across comment/code/runtime; no registry. → L1, L5.
- **Implicit cross-agent contract** (planner silently required explorer
  artefacts). → L10.
- **`queued→blocked` invalid-transition spam** on dep-waiting tasks. → L11.
- **Soft-kill resurrection**: SIGTERM drains slowly and the supervisor restarts
  the daemon → zombies/duplicates fighting over the queue. → L8.
- **Bookkeeping bleeding into the deliverable repo.** → L4.
- **God-files & duplicate domain types.** → L1, L3.
- **Opaque failures** ("always a different thing") from missing failure causes. → L10.

---

## 5. Proven substrate to port (lift the algorithm, not the file)
1. Atomic-write retry ladder + tombstone scanning (`io_utils` concept).
2. Status-directory queue + atomic move semantics.
3. Agent subprocess contract (`AgentResult`: ok/summary/artifacts/spawned/metadata
   + a typed failure cause) — **defined once** this time.
4. Dependency cascade + prerequisite handling — with the *correct* state machine.
5. Supervisor lifecycle + heartbeat + startup grace — with the stress-report fixes
   baked in from line one.
6. Bounded-retry with anti-storm backoff (the load-churn report validated this).

---

## 6. Foundation-phase deliverables (this phase — before any product code)
- [x] **Foundation Charter** (this document): laws + enforcement + lessons.
- [ ] **Feature inventory**: exhaustive, modular, prioritised; v1-scope vs deferred.
- [ ] **Module / architecture map**: the layers of L2, the seam for L9 (self-mod).
- [ ] **Enforcement toolchain spec**: import-linter contracts, ruff config, the
      LOC-budget test, the registries, the CI pipeline — written before the code
      they police.
- [ ] **Tooling setup**: which Claude skills v2 leverages; graphify on the new repo.
- [ ] **Substrate port-list**: concrete extraction plan from v1 (section 5).

---

## 7. Open decisions (need your input)
1. **Stack.** Assumed **Python** (matches the proven substrate, the agent/CLI
   model, graphify, and the skills). Confirm, or name an alternative.
2. **Repo location & name.** Where v2 lives (a fresh repo, e.g.
   `~/Projects/orchestrator-v2`), separate from v1.
3. **LOC budget value** for L3 (proposed 500).
4. **Model assignments** (the L5 registry): ratify the intended map —
   planner→opus, builder→sonnet, tester/explorer/researcher→haiku, etc. — as the
   canonical source before any agent is written.
```
