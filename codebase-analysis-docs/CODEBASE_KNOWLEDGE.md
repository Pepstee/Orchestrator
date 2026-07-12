# CODEBASE_KNOWLEDGE — agentic-orchestrator (v2) Master Knowledge Document

*Produced by a direct-exploration pass on 2026-07-08 against the LIVE system at
`/Users/admin/Documents/agentic-orchestrator`; **refreshed 2026-07-10** against the current tree
(HEAD `4753656`). Every claim is grounded in source read during these sessions, cited by file and
symbol. Read alongside `docs/HANDOFF.md` (decisions) and `docs/OPERATING_GUIDE.md` (how to run it)
— this document maps the code; the handoff carries the why. British spelling throughout.*

*Companion: `claude-orchestrator-main/codebase-analysis-docs/CODEBASE_KNOWLEDGE.md` maps **v1**,
the retired predecessor — useful only as the port-source reference for v3 (FOUNDATION §5).*

---

## PART 1 — HIGH-LEVEL OVERVIEW

### 1.1 What this application is

**agentic-orchestrator (v2)** is a single-developer autonomous software factory: you hand it a
goal, and it plans, builds, tests, judges, hardens, and certifies working software in the
background — pinging your phone when something is certified or genuinely stuck. The design
thesis, stated in `CLAUDE.md` and enforced throughout: a **durable, legible event log** +
**stateless subprocess agents** + **gates that cannot be cheated**, governed by a small set of
**laws-as-data** (`charter/laws.py`), each backed by a machine check.

It is the deliberate antithesis of v1 (`claude-orchestrator-main`): 5 agents instead of 28,
~6,300 lines of live source instead of ~26,000, one event log instead of five status
directories, laws with enforcing tests instead of a policy file agents merely read, and
**no self-development pipeline at all** — self-modification is structurally quarantined (L9)
and fenced at runtime (L9R).

**Current live state** (volatile — `state/tasks.events.log` is the truth; this snapshot is
10 July 2026): the daemon is **RUNNING** under `run_forever.sh`. `state/flagship` =
`orchestrator-v3`: the mission is for this orchestrator to **build its own successor (v3)** as a
product in `projects/orchestrator-v3/` — ten certifiable slices governed by the build charter
(`docs/planning/16_V3_BUILD_CHARTER.md`) and the DV-1..7 laws (`docs/planning/13`). The Slice-1
foundation is seeded in the repo; a companion **slice feeder** process (`control/slice_feeder.py`)
feeds Slices 2–10 one at a time as each certifies. As of this refresh Slice 1 has passed all four
gates once and is in the assurance ladder (an adversarial finding routed to the Overseer — the
intended behaviour). The judge is temporarily rerouted `AGENTIC_JUDGE="claude:opus"` while Codex
CLI auth is broken (weakens F5 independence — see §5.6).

### 1.2 Tech stack

| Layer | Technology | Where |
|---|---|---|
| Runtime | Python 3 (≥3.10 typing), stdlib-only core — **no Flask, no Tauri, no database** | all packages |
| LLM access | provider CLIs via subprocess: `claude` and `codex` (both parsers validated against real CLI output; codex validated 2026-06-01) | `infra/llm.py` |
| Persistence | append-only JSONL event logs + atomic writes | `infra/event_store.py`, `infra/atomic_io.py` |
| Concurrency | thread pool for the *LLM call only*; all state mutation on the main thread | `control/pool.py` |
| Isolation | per-task git worktrees per project | `infra/worktree.py` |
| Architecture enforcement | import-linter (3 contracts), ruff (E,F), pytest architecture tests, docs-drift checks | `pyproject.toml`, `tests/architecture/`, `tests/test_docs_claims.py` |
| GUI | stdlib HTTP server, one-tap actions | `edge/server.py` (port 8765) |
| Notifications | macOS `osascript` + Telegram (sender-locked, two-way) | `infra/notify.py`, `control/operator_chat.py` |
| Tests | pytest — 58 test files, ~359 test functions incl. the architecture meta-tests | `tests/` |
| Supervision | `run_forever.sh` (bash relaunch loop; honours STOP; a BG-1 refusal **stays down**) + `control/slice_feeder.py` (v3 slice ritual) | repo root, `control/` |

### 1.3 The features and their business purposes

1. **Laws-as-data with machine checks** (`charter/laws.py`) — 19 laws (17 active, 2 deferred:
   L10, A2); every `active` law names its enforcing test or import-linter contract, and the
   PRIME meta-check (`tests/architecture/test_every_law_has_a_check.py`) fails the build if one
   doesn't. *Purpose: "a law without a machine-check is a wish" — governance that cannot
   silently rot.* Since 8 July the same idiom covers prose: `tests/test_docs_claims.py` pins the
   greppable ground truths of CLAUDE.md/QUALITY_CHARTER/HANDOFF so doc-vs-code drift turns the
   build red.
2. **Event-sourced task lifecycle** (`infra/event_store.py` + `dispatch/repository.py`) — every
   transition is an appended event; `TaskRepository.replay()` rebuilds the entire task set from
   the log. Restart = resume; finished work is never re-run; retry budgets are derived from the
   log so **a restart can never launder a budget** (BG-3). *Purpose: crash-safe autonomy on the
   Claude Max 5-hour restart cadence.*
3. **Total state machine** (`core/state_machine.py`, L11) — every (status × event) pair defined;
   illegal pairs are no-ops, never exceptions. `QUEUED + BLOCK → BLOCKED` is legal — the
   structural fix for v1's transition spam. *Purpose: no undefined behaviour in the lifecycle.*
4. **Five-agent roster + one meta-agent** (`registry/agents.py`, laws L1/L5) — `task_manager`
   (incremental planner), `builder`, `tester` (independent author — anti-collusion),
   `judge` (cross-provider: openai/codex), `researcher`, plus the persistent **Overseer**
   (claude-fable-5). *Purpose: resist v1's agent proliferation; one responsibility each.*
5. **The un-cheatable completion contract** (`validation/`) — a project is done only when
   `REQUIRED_GATES = (tests, acceptance, judge, authenticity)` all pass **and** the
   progressive-assurance ladder comes back clean. *Purpose: an agent under budget pressure
   always finds the cheapest path to green; every gate exists to make the cheap path fail.*
6. **Progressive assurance / hardening ladder** (`validation/assurance.py`) — tests-rerun →
   mutation testing (`validation/mutation.py`, kill threshold 0.8) → acceptance-by-execution →
   adversarial LLM tiers. A finding routes to the Overseer, never to you. *Purpose: quality
   blocks completion (Quality Charter bar 6).* (Working as designed on 10 July: Slice 1 passed
   the four gates, then the adversarial tier found an issue and blocked certification.)
7. **Zero-touch self-certification** (DG-2) — when gates + assurance are clean the daemon
   **self-certifies** (`repo.record_confirmation`) and notifies; then FOREVER-IMPROVE opens
   another improvement round until the planner returns `[]`. *Purpose: nothing waits on the
   operator; the phone ping is informational.* (CLAUDE.md and the Quality Charter were
   reconciled to this in commit `3d3474a` — the drift is gone and now machine-checked.)
8. **Failure ladder with durable budgets** (`dispatch/dispatcher.py::_handle_failure` +
   `infra/triage.py`) — PERMANENT fail-fast → TRANSIENT requeue (capped at
   `MAX_TRANSIENT_REQUEUES = 5`) → BG-3 input-hash refusal of identical deterministic
   re-attempts → PA fast-path → bounded retry → escalate. **Auth failures
   (401/oauth-expired/not-logged-in) are PERMANENT and fail fast with a notify**
   (`infra/llm.py::_AUTH_ERROR_HINTS` + `infra/triage.py`, commit `3d3474a`) — the
   401-as-transient overnight loop is retired; opaque bare exits and rate-limit wording stay
   TRANSIENT (the usage-cap signature). *Purpose: every requeue path finite.*
9. **PA rule engine, overseer-evolved** (`pa/rules.py`, `pa/overseer.py`) — deterministic
   failure-cause → action rules; the Overseer mines recurring causes into candidates, promoted
   to active only with evidence and only for safe (non-code) actions. *Purpose: known failures
   handled for free, maturation curve without self-modification.*
10. **The persistent Overseer** (`agents/overseer.py`, `memory/overseer.py`) — one continuous
    Claude session (resumed by id from a stable cwd), hourly observe pulses, 24-h session reset
    with a **self-improving CORE+EXTRA handoff** (CORE immutable — the quality floor; EXTRA is
    data the overseer revises, so L9 holds). It can intervene in projects, abandon them
    (directives stick via the abandonment watermark), and reprioritise — via `control` tasks the
    daemon executes, never as code changes. BG-5 alarms on a wedged/dying guardian. *Purpose:
    a bounded "Jarvis" that steers without touching the machinery.*
11. **Runtime self-mod fence L9R** (`infra/worktree.py::selfmod_fence`, wired at every settle in
    `control/pool.py`) — any write to the orchestrator's own tree is diffed, quarantined
    to `state/quarantine/`, reverted, and fails the settling task. Born from the 12 Jun incident:
    a builder, blocked by the mutation gate, **edited the gate**. Note it fences *operator* edits
    too — see gotcha 7. *Purpose: the examined never edit the examiner.*
12. **Budget governor + burn-rate breaker** (`control/budget.py`) — durable spend cap
    (`AGENTIC_BUDGET_USD`), kill-switch sentinel `state/KILL`, and a breaker that pauses paid
    work for 30 min when the trailing-40-run success ratio drops below 0.4 (min 20 runs).
    *Purpose: L6 bounded autonomy — burn-vs-progress can never run silent again (June ran at
    6.8% and nobody saw).*
13. **Depth before breadth, BG-2** (`control/breadth.py`) — until a first certification exists,
    dispatch is restricted to the human-set flagship (`state/flagship`; nothing in the codebase
    writes it — an architecture test asserts this). *Purpose: one project done properly beats
    eight half-built.*
14. **Boot self-test, BG-1** (`control/self_test.py`) — the daemon refuses to dispatch unless
    every law-linked check is present, collected, and passing; deliberately no bypass flag.
    Since commit `4971a75` the supervisor treats the refusal (exit 3) as deterministic: it
    **writes STOP and stays down** instead of crash-looping (the 8 Jul lesson — ~30 s per futile
    relaunch while planning/16 was missing). *Purpose: enforcement before features.*
15. **Knowledge base + deep research** (`memory/knowledge.py`, `agents/researcher.py`,
    `validation/research_contract.py`) — an append-only Obsidian-style KB (DV-2) and a tiered
    research agent whose evidence bundle must pass the DV-3 contract (depth floor, no
    link-dumps, independent corroboration, public-sources-only). **Committed but gates
    unwired in v2** (commit `eb31792`) — deliberately: wiring them fail-closed is v3 Slices 7–8
    (see the feeder's SLICES table). *Purpose: v3's load-bearing memory and research capability,
    staged in v2 first.*
16. **Operator surfaces** — `control/enqueue.py` / `control/intake.py` (goal → task graph via
    `state/inbox/`), `control/confirm.py` (manual confirmation channel), `edge/server.py`
    (one-tap GUI: `/api/state`, `/api/confirm`, `/api/goal`, `/api/instruct`),
    `control/operator_chat.py` (two-way Telegram: your messages become turns in the Overseer's
    one continuous session), `control/scorecard.py` (deterministic metrics: success ratio,
    time-in-agent, waste counters, runs-per-certification).
17. **The slice feeder** (`control/slice_feeder.py`, commit `4753656`) — the build charter's
    ritual (16 §4: feed ONE slice, wait for certification, feed the next) automated as a
    companion process. See §3.6. *Purpose: the hands-off v3 build — depth before breadth
    without a human dropping each slice.*

### 1.4 How it all composes (one paragraph)

A goal enters through intake/enqueue/GUI/Telegram as a task file in `state/inbox/`; the daemon
(`control/daemon.py` — the single supervised entrypoint, L8) ingests it into the event log.
The concurrent pool claims ready tasks (dependency-gated, priority-ordered, one writer per
project tree by default) and runs the registry-resolved agent subprocess in a per-task git
worktree; results settle on the main thread through the failure ladder, and the L9R fence
checks the orchestrator's own tree at every settle. When a project's graph drains, the monitor
evaluates the four automated gates; unmet gates trigger a replan (incremental planner, ≤20
iterations per era) or an Overseer intervention (≤3 per era), then abandonment — never a silent
stall. Gates met triggers the assurance ladder; clean means self-certified, phone ping, and a
FOREVER-IMPROVE round. In parallel the Overseer pulses hourly in its one persistent session,
evolves the PA from failure history, and answers your Telegram messages; the slice feeder
watches the same log and feeds the next v3 slice on each certification; the budget governor,
burn breaker, breadth cap, deadline, STOP sentinel and kill-switch bound everything.

---

## PART 2 — SYSTEM ARCHITECTURE

### 2.1 The layer contract (import-linter, law L2)

```
edge  →  control  →  (dispatch | scheduling | validation)  →  pa  →  agents  →  memory  →  infra  →  core
registry = leaf (imports nothing internal)
selfdev  = quarantined (NOTHING may import it — L9 contract)
```

Three enforced contracts in `pyproject.toml [tool.importlinter]`: the layer ordering, the
registry-as-leaf rule, and the selfdev quarantine. `scheduling/` and `selfdev/` are
**placeholder packages** (4-line `__init__.py` each) — the seams exist before the features.

### 2.2 Directory map (live source only)

```
agentic-orchestrator/
├── charter/laws.py            # 19 laws as frozen dataclasses (17 active), each naming its check
├── core/                      # pure domain, stdlib only
│   ├── models.py              #   Task, AgentResult (defined ONCE — fixes v1's dual definition),
│   │                          #   TaskStatus, Event; AgentResult.cause (L10) + .intent
│   └── state_machine.py       #   TRANSITIONS: total (status × event) table; transition() never raises
├── infra/                     # IO + provider seams
│   ├── atomic_io.py           #   THE only sanctioned writer/deleter (L7): write_json_atomic,
│   │                          #   write_text_atomic, append_jsonl (fsync), read_jsonl (truncation-tolerant)
│   ├── event_store.py         #   append-only JSONL log + replay()
│   ├── llm.py                 #   call_llm(provider, model, prompt…) → LLMResult{text, cost};
│   │                          #   RateLimited marker; _AUTH_ERROR_HINTS → fail-fast + notify;
│   │                          #   codex parser validated 2026-06-01
│   ├── triage.py              #   ErrorClass TRANSIENT/RECOVERABLE/PERMANENT; classify();
│   │                          #   auth-error patterns are PERMANENT; is_input_deterministic()
│   │                          #   (BG-3); RATE_LIMIT_HINTS (v1 port, row B1)
│   ├── worktree.py            #   per-task worktrees, merge-back on main thread; selfmod_fence() (L9R)
│   ├── workspace.py           #   resolve_project_dir (L4 containment), check_pristine (no scratch)
│   ├── notify.py              #   desktop + Telegram (config: state/telegram.json); never raises
│   └── pidlock.py             #   single instance (L8); stale-PID reclaim; no auto-restart
├── registry/agents.py         # TASK_TYPE_TO_AGENT, AGENT_COMMANDS, AGENT_MODELS, model_for()
│                              #   (env override AGENTIC_<AGENT>="provider:model")
├── memory/
│   ├── knowledge.py           #   KnowledgeBase: entries/<id>.md + INDEX.md (DV-2; gates unwired in v2)
│   └── overseer.py            #   session pointer + CORE(immutable)+EXTRA(self-improved) handoff
├── agents/                    # 6 subprocess agents, all with INJECTED LLM calls (token-free tests)
│   ├── common.py              #   read_payload(stdin) / emit(stdout) / safe_main (crash → caused failure)
│   ├── task_manager.py        #   INCREMENTAL planner: state in → next small batch out; [] = goal met
│   ├── builder.py             #   builds in projects/<name>/ (worktree cwd); L4 purity guard
│   ├── tester.py              #   independent adversarial test author (anti-collusion, F5)
│   ├── judge.py               #   cross-provider review (openai/codex); suite-green ≠ proof (F2)
│   ├── overseer.py            #   modes: intervene / observe / succession (persistent session)
│   └── researcher.py          #   tiered deep research → evidence bundle → KB (kind=research)
├── pa/
│   ├── rules.py               #   load/save/consult over state/pa_rules.json (active rules only)
│   └── overseer.py            #   evolve(): recurring causes → candidates → curated promotion (SAFE_ACTION only)
├── validation/
│   ├── gates.py               #   REQUIRED_GATES=(tests,acceptance,judge,authenticity); run_test_gate;
│   │                          #   DEFAULT_TEST_COMMAND uses sys.executable (macOS python3 trap)
│   ├── authenticity.py        #   no-stub static scan (AST + regex; abstract/Protocol exempt)
│   ├── acceptance_exec.py     #   run declared `acceptance` file criteria; NO declaration = FAIL;
│   │                          #   mock tells (--mock/fake/dummy/stub) = FAIL (DG-6 / D2.5)
│   ├── mutation.py            #   AST mutants in a throwaway copy; killed/total ≥ 0.8 or fail
│   ├── assurance.py           #   run_assurance over Tiers; first finding halts; governor duck-typed
│   └── research_contract.py   #   DV-3: depth floor, excerpts required, ≥N independent domains,
│                              #   paywalled source rejects the bundle
├── dispatch/
│   ├── repository.py          #   TaskRepository over the event store (see §2.3)
│   ├── dispatcher.py          #   select_next_task, settle(), _handle_failure ladder,
│   │                          #   propagate_prerequisite_failures (fixpoint), MAX_SPAWNED_PER_TASK=50
│   └── runner.py              #   make_subprocess_invoke(): registry command, stdin payload,
│                              #   one stdout AgentResult; failures always carry cause (F10)
├── control/
│   ├── daemon.py              #   THE entrypoint: python -m control.daemon (see §2.4)
│   ├── pool.py                #   run_concurrent: ≤ max_workers (default 8; run_forever sets 20)
│   ├── slice_feeder.py        #   v3 slice ritual automated: log-watch → inbox drop (see §3.6)
│   ├── budget.py              #   BudgetGovernor: durable cap + KILL + burn breaker (0.4/40/20/30min)
│   ├── breadth.py             #   BG-2 flagship allowance (human-only file)
│   ├── project.py             #   evaluate_project → ProjectOutcome{gates, complete}
│   ├── self_test.py           #   BG-1 boot self-test (no bypass)
│   ├── intake.py / enqueue.py / inbox.py    # goal → graph → inbox → log
│   ├── confirm.py             #   manual confirmation channel (state/confirmations/)
│   ├── operator_chat.py       #   two-way Telegram (sender-locked; durable offset)
│   ├── scorecard.py           #   deterministic metrics from the durable records
│   └── loop.py                #   bounded sequential driver (L6) — pool.py is the production driver
├── edge/server.py             # stdlib HTTP GUI :8765 — reads the log, acts via inbox/confirm only
├── selfdev/, scheduling/      # quarantined / placeholder seams
├── tests/                     # 58 files, ~359 tests; tests/architecture/ = the law checks;
│                              #   test_docs_claims.py = docs-drift checks; test_auth_failfast.py
├── docs/                      # HANDOFF.md, OPERATING_GUIDE.md, QUALITY_CHARTER.md,
│                              #   RUNBOOK_GIGABYTE.md, planning/ (00–17, FOUNDATION, port/)
├── graphify-out/              # knowledge graph (2026-07-08: 1358 nodes, 93 communities)
├── run_forever.sh             # external supervisor (relaunch loop; STOP-aware; singleton lock;
│                              #   BG-1 exit 3 → writes STOP and stays down)
└── state/ (gitignored)        # tasks.events.log, budget.events.log, pa_rules.json, flagship,
                               # inbox/, confirmations/, quarantine/, overseer_session.json,
                               # handoff_latest.md, handoff_extra.md, telegram*.json,
                               # v3_slice.json (feeder cursor), KILL, STOP(root)
```

Notes: `docs/planning/` now contains the ratified v3 corpus — `16_V3_BUILD_CHARTER.md` (the
ten-slice build charter), `17_MODULAR_ENGINE_SPEC.md` (kernel+ports+manifests ME-1..8, container
runner, selfdev candidate/promotion pipeline — RATIFIED 8 Jul as v3-charter input, **no v2
retrofit**), `FOUNDATION.md`, and `port/` (PORT_LEDGER.md + `v1/` snapshots: error_triage,
admission_control, watchdog, velocity_monitor…). `projects/orchestrator-v3/` holds the seeded
Slice-1 foundation (gitignored product territory). `projects.archived-*/` holds retired v2-built
products (deal-sniper, situation-monitor, writing-assistant, travel-designer…) — reference
output, not live code.

### 2.3 The event-sourced lifecycle

```mermaid
flowchart TD
    G[goal: enqueue/intake/GUI/Telegram] --> IB[state/inbox/*.json]
    FEED[control/slice_feeder.py<br/>certification n → slice n+1] --> IB
    IB -->|ingest each cycle| LOG[(state/tasks.events.log<br/>append-only JSONL)]
    LOG -->|replay at boot| REPO[TaskRepository<br/>+ reclaim_orphans + revive_transient_failures]
    REPO -->|claim_next: ready, priority-max,<br/>per-project cap 1, BG-2 allowance| POOL[control/pool.py<br/>≤ max_workers invokes on threads]
    POOL -->|subprocess: stdin payload| AG[agents/* in a git worktree]
    AG -->|one AgentResult on stdout| SETTLE[settle on MAIN thread:<br/>merge worktree · L9R fence · ladder]
    SETTLE -->|ok| DONE[COMPLETE + spawn ≤50 subtasks]
    SETTLE -->|fail| LADDER{PERMANENT? TRANSIENT≤5?<br/>BG-3 same-inputs? PA rule?<br/>retries left?}
    LADDER -->|requeue| LOG
    LADDER -->|fail + escalation event| LOG
    DONE --> MON[monitor_projects when a<br/>project graph is fully terminal]
    MON -->|gates unmet, planner has moves| REPLAN[plan task, mode=state-fed]
    MON -->|planner spent| OV[oversee task ≤3/era] --> ABANDON[record_abandoned<br/>era closes; project parks]
    MON -->|4 gates pass| ASSURE[assurance ladder]
    ASSURE -->|clean| CERT[record_confirmation — SELF-CERTIFIED<br/>notify · FOREVER-IMPROVE round]
    ASSURE -->|finding| OV
```

Key `dispatch/repository.py` mechanics: failure budgets are Counters rebuilt from
`task_result` events at replay (BG-3); `record_abandoned` stamps a **watermark** so an
abandonment closes the budget era (the 12 Jun lesson — a resurrected project must not inherit
its dead predecessor's spent planner); `dormant_since_abandonment` parks abandoned projects so
the monitor can never resurrect them on its own initiative; `reclaim_orphans` +
`revive_transient_failures` run at every boot (the 5-hour-restart recovery pair);
`claim_next(per_project_cap=1)` serialises writers per project tree (env
`AGENTIC_PROJECT_CONCURRENCY` raises it — worktrees make >1 safe).

### 2.4 The daemon cycle (`control/daemon.py::main` + `serve`)

Boot: pidlock → **BG-1 boot self-test (SystemExit 3 on failure — no bypass; the supervisor
writes STOP and stays down on it)** → replay log → reclaim orphans → revive transients →
BudgetGovernor (cap from `AGENTIC_BUDGET_USD`, default 10.0; `run_forever.sh` sets 1,000,000 —
the Max-subscription posture where the *usage window* is the real budget) → read flagship →
serve. `serve()` threads `projects_root` through to the pool (commit `8a44831` — lets tests run
hermetically against a temp projects dir; the stray `projects/p` bug).

Every cycle (`_maintain` + `on_cycle`, which also run *during* long batches so the pool can't
starve them): ingest inbox → cascade prerequisite failures → ingest confirmations → burn-flag
notification → `monitor_projects` → `tick_overseer_session` (reset/succession/pulse, BG-5
wedge alarm) → `poll_operator_messages` → `process_overseer_control` (abandon/reprioritise
directives) → PA evolve+save → 12-h heartbeat notify.

Stop conditions (`should_stop`): SIGTERM/SIGINT flag, `STOP` sentinel at repo root,
`governor.should_stop()` (cap or `state/KILL`), `AGENTIC_DEADLINE_HOURS` expiry (writes STOP
itself — a self-chosen stop stays stopped).

Constants that shape behaviour: `MAX_PLAN_ITERATIONS = 20` (per era),
`MAX_OVERSEER_INTERVENTIONS = 3` (per era), `HEARTBEAT_SECONDS = 12*3600`,
`OVERSEER_PULSE_SECONDS = 3600`, `OVERSEER_PROJECT = "__overseer__"` (reserved `__` prefix —
skipped by monitoring, always dispatchable under BG-2). **Pending change** (10 Jul, prepared
and fence-quarantined at `state/quarantine/selfmod_1783652034.patch`, apply at the next daemon
pause): per-slice eras (the feeder's slice plans carry `payload.mode="rescope"`) + the
intervention cap made operator-tunable via `AGENTIC_MAX_OVERSEER_INTERVENTIONS` — without it,
all ten v3 slices share ONE 20+3 era budget.

### 2.5 Agent invocation contract

`dispatch/runner.py::make_subprocess_invoke`: resolve agent from
`registry.TASK_TYPE_TO_AGENT` → command from `AGENT_COMMANDS` (always `sys.executable -m
agents.<name>`) → JSON payload on **stdin** → exactly one AgentResult JSON line on **stdout**.
Non-zero exit, timeout, or unparseable output all become a failed AgentResult **with a
`cause`** (L10/F10) — the orchestrator never sees a bare traceback. `agents/common.py::
safe_main` guarantees the same from inside the agent. All LLM calls inside agents are
**injected callables**, so every agent's logic is tested without tokens.

`infra/llm.py::call_llm(provider, model, prompt, cwd, timeout, session…)`: claude path parses
the CLI's JSON (text + cost); rate/usage-limit wording raises `RateLimited` (its message is a
transient cause by construction); **auth-error wording (`_AUTH_ERROR_HINTS`, matched only
against provider stderr on a non-zero exit) raises a plain RuntimeError with an "auth error"
prefix that `infra/triage.py` classifies PERMANENT, plus a one-shot notify — fail fast, never
loop**; hard CLI errors and session errors are distinguished (a dead session falls back to a
fresh one — the work doesn't die with the session); the codex parser was validated against real
`codex exec --json` output on 2026-06-01 (`_parse_codex_output`) — the earlier
"deliberately raises until validated" posture is retired.

### 2.6 Cross-cutting concerns

- **File mutation** — only via `infra.atomic_io` (L7), enforced by
  `tests/architecture/test_file_preservation.py` scanning source for raw `open(w)`/
  `write_text`/`unlink`/`rmtree` (`tests/` and `projects/` exempt; git operations in
  worktree.py exempt because git owns the tree).
- **Security** — L9 (static: nothing imports `selfdev`) + L9R (runtime fence at every settle,
  forensic quarantine, hermetic under pytest); Telegram sender-lock (only the operator's
  `chat_id` is read; others dropped unread); GUI acts only through channels the daemon already
  ingests (`edge/server.py` never writes the log); agents hold zero GitHub credentials —
  publication is a human act (`scripts/publish_projects.sh`); no secrets in repo
  (`state/telegram.json` gitignored).
- **Observability** — the event logs ARE the observability; `control/scorecard.py` computes
  success ratio, wall-clock-per-run (the honest cost proxy on a Max subscription),
  waste counters, merges landed, and runs-per-certification. `notify()` is advisory only —
  nothing depends on a notification arriving.
- **Model wiring** (`registry/agents.py::AGENT_MODELS`) — planner/builder/tester/researcher:
  claude sonnet; judge: **openai codex** (F5 cross-provider independence); overseer:
  **claude-fable-5** (DG-3 — strongest model to the highest-stakes judgement; watch
  retries-per-completion). Per-agent env override `AGENTIC_<AGENT>="provider:model"` for
  outages; a rejected model string is a PERMANENT (loud) failure. (Live posture 10 Jul:
  `AGENTIC_JUDGE="claude:opus"` while Codex CLI auth is broken.)
- **Docs integrity** — `tests/test_docs_claims.py` (spec 17 §10 backport) asserts the greppable
  ground truths: the four-gate zero-touch contract wording, every docs/ path named in HANDOFF
  exists, no user-gate language. Deliberately no brittle numbers (test counts/LOC were removed
  from prose instead).

---

## PART 3 — FEATURE-BY-FEATURE DETAIL

### 3.1 Planning: the incremental replan loop

`agents/task_manager.py` receives the goal + current project state (files, done steps, failed
steps **with causes** from `repo.last_results()`) and emits only the *next small batch* —
never a big-bang decomposition (v1's planner routed test-writing to the judge and dead-ended).
`[]` means "goal met" (`_planner_done`), which terminates the loop. The daemon feeds state
back on every replan (`_project_state`). Budgets are **per era** (`_era_counts`): a `plan`
task with `payload.mode == "rescope"` or an abandonment watermark opens a fresh era — without
this, a re-scoped project arrives pre-exhausted (the 11 Jun stall read "20/20 iterations"
mostly belonging to an abandoned goal). `payload.mode == "improve"` marks FOREVER-IMPROVE
rounds after certification. (The pending quarantine patch makes the slice feeder emit
`mode="rescope"` so each v3 slice opens its own era — see §2.4.)

### 3.2 The gates (why each exists)

| Gate | File | Cheap path it kills |
|---|---|---|
| tests | `validation/gates.py::run_test_gate` (project's own suite, 1800 s timeout) | code that doesn't run |
| authenticity | `validation/authenticity.py` | stubs/TODO/`pass`-bodies/mock identifiers in shipped code |
| acceptance | `validation/acceptance_exec.py` | green suite over a dead product; **no declaration = FAIL**; `--mock` in a criterion = FAIL (the June demo literally ran `acceptance.py --mock` against a dead package) |
| judge | `agents/judge.py` (cross-provider) | builder blessing its own work; suite-green treated as proof |
| mutation (assurance) | `validation/mutation.py` (0.8 kill threshold, throwaway copy) | tests that cannot fail |
| adversarial/LLM tiers (assurance) | `validation/assurance.py::hardening_tiers` | anything the deterministic tiers can't see |

The assurance loop **never regresses**: tiers only verify; first finding halts and routes to
the Overseer. The governor is duck-typed and injected (validation must not import control —
the arrow points inward).

**A judge-scope subtlety surfaced by the v3 build (10 Jul):** the judge reads the deliverable's
own self-description. Slice 1's seeded README said "Slice 1 of 8" (stale — the charter is ten
slices), and the judge repeatedly refused to bless a self-declared partial product. Lesson,
destined for the v3 charter: **a sliced build must teach its judge what "done" means per
slice** — each slice's README/acceptance must describe the slice as a complete deliverable
within a larger roadmap. The README is product territory; agents may fix it.

### 3.3 The Overseer subsystem (the one stateful agent)

- **Session continuity**: `memory/overseer.py` persists the session pointer;
  every oversee task resumes the same Claude session from the **repo root** (sessions are
  namespaced by cwd; `--dangerously-skip-permissions` must be re-passed on every resume).
- **Lifecycle** (`tick_overseer_session`): boot/24-h reset → fresh session seeded with the last
  handoff; near the wipe → a `succession` task writes the CORE+EXTRA handoff (CORE immutable
  floor; EXTRA self-improved, length-capped); otherwise hourly `observe` pulses.
- **BG-5 guardian liveness** (`overseer_pulse_health`): ≥2 outstanding pulses (wedge — stop
  stacking) or last two terminal runs failed (alarm, but fresh pulses allowed — a new session
  is the self-heal). Queued operator messages don't count as wedges.
- **Authority**: spawns `control` tasks (abandon/reprioritise) that the daemon executes —
  `dispatch` never runs `control` tasks as agents. Abandon directives are recorded durably so
  they **stick** (12 Jun: an operator-ordered fleet park was undone by the monitor within
  minutes before this fix). It never touches orchestrator code (L9), and directive-bearing
  pulses notify the operator in the overseer's own words.

### 3.4 Intake and operator surfaces

`control/enqueue.py` (one task) and `control/intake.py` (goal → build+validate graph) write
files to `state/inbox/`; the daemon folds them into the log (multi-writer safe, works whether
the daemon is up or not). `edge/server.py` (:8765) reads the log for `/api/state` and acts by
dropping inbox/confirmation files (`/api/goal`, `/api/confirm`, `/api/instruct`) — it can
never bypass a law or race the daemon. `control/operator_chat.py` polls Telegram getUpdates
each cycle (zero-timeout), sender-locked, durable offset written *after* enqueue
(at-least-once); first contact drains history without enqueueing. `control/confirm.py` lists
and confirms `pending_user` projects manually — retained even though certification is now
automatic.

### 3.5 The v3 build mission (context any agent here must hold)

Per `docs/HANDOFF.md`, `docs/planning/13_V3_CAPABILITY_PLAN.md` and
`docs/planning/16_V3_BUILD_CHARTER.md`: v3 is built **by this orchestrator as a product** in
`projects/orchestrator-v3/` (product territory — the L9 fence does not apply there; this is not
self-modification). Ratified DV-laws: capability-plus-gate discipline; the KB is load-bearing
(DV-2); research is deep-or-fail (DV-3); modules plug in behind a fail-closed seam-gate (DV-6);
DV-7 dev-mode separates operator edits from agent tampering (lands as v3 Slice 9's
`state/DEVMODE` sentinel). `docs/planning/17_MODULAR_ENGINE_SPEC.md` (RATIFIED 8 Jul) adds the
modular-engine shape — kernel+ports+manifests (ME-1..8), fail-closed module loader, selfdev
candidate/promotion pipeline (Theseus realised; L9 amendment), container runner with two-phase
Max auth — **as v3-charter input only; no v2 retrofit**. The pure-Python ME core (ME-1..3) is
folded into v3 Slices 2–3 via the feeder's SLICES table. The port list (FOUNDATION §5) draws
from **v1**: atomic-write ladder, queue semantics, the agent contract, dependency cascade with
the correct state machine, supervisor lifecycle, bounded anti-storm retry — snapshots under
`docs/planning/port/v1/` with `PORT_LEDGER.md`. Fork-clean vs evolve-in-place is **settled —
do not relitigate**. The charter (planning/16) and the seeded Slice-1 foundation
(`projects/orchestrator-v3/`) are **in the repo**; `tests/test_docs_claims.py` makes the
charter's presence mandatory (BG-1 refuses without it).

### 3.6 The slice feeder (`control/slice_feeder.py`)

The charter's ritual — feed ONE slice, wait for certification, feed the next; never all ten at
once — automated as a **companion process** (same discipline as `edge/server.py`: read the
durable log, act only through existing channels; it never touches daemon state).

- **Trigger** (per slice n, 1-based; Slice 1 ships seeded): `certifications(repo) >= n` (count
  of `project_confirmed` events for `orchestrator-v3`) **AND** `all_terminal(repo)` (every
  project task DONE/FAILED) → `feed_next()` drops the Slice n+1 `plan` task into
  `state/inbox/` and advances the durable cursor `state/v3_slice.json` (`{"last_fed": n}`).
- **`SLICES: dict[int, tuple[goal, acceptance[]]]`** embeds Slices 2–10 verbatim from the
  charter's table (16 §3), with the ME-1..3 shape folded into Slices 2–3. This is the
  single in-code source of the v3 slice plan — if the charter's slices change, change this
  table with it.
- **Lifecycle**: polls every 60 s; STOP-aware (repo-root sentinel); exits by itself after
  feeding Slice 10; torn reads of the live log are swallowed and retried next poll ("never
  crash the ritual"). Safe to restart any time — cursor and inbox are durable and idempotent.
- **Run**: `nohup python3 -m control.slice_feeder > state/slice_feeder.log 2>&1 &` alongside
  the daemon. Missing cursor file = cursor 1 (nothing fed yet beyond the seed).
- **Tests**: `tests/test_slice_feeder.py`.

---

## PART 4 — THINGS YOU MUST KNOW BEFORE CHANGING CODE

### 4.1 Doc-vs-code drift — now machine-checked (status as of 10 July)

The 8-July exploration found four drift items; all are **resolved**, and the drift class itself
now turns the build red (`tests/test_docs_claims.py`, commit `3d3474a`):

1. ~~CLAUDE.md/project.py described a human confirmation gate~~ — reconciled to DG-2
   zero-touch (the code truth: `validation/gates.py` four automated gates; the daemon
   self-certifies). The confirmation channel (`control/confirm.py`) still exists but gates
   nothing. Trust `gates.py` + `daemon.py`.
2. ~~`docs/OPERATING_GUIDE.md` missing~~ — exists (restored from quarantine, commit `45e3dbc`);
   it is the consolidated operator how-to.
3. ~~`graphify-out/` missing~~ — exists (built 2026-07-08: 167 files → 1358 nodes, 93
   communities; read `graphify-out/GRAPH_REPORT.md` before architecture questions).
4. ~~"~207 tests" in CLAUDE.md~~ — stale counts removed from prose entirely (the docs-drift
   checks deliberately pin no brittle numbers).
5. **Still true and by design**: KB + research (`memory/knowledge.py`, `agents/researcher.py`,
   `validation/research_contract.py`) are committed but unwired in v2 — wiring them
   fail-closed is v3 Slices 7–8, not a bug.
6. **Live product-level drift**: `projects/orchestrator-v3/`'s seeded README self-describes as
   "Slice 1 of 8" — predates the ten-slice charter and causes judge scope-rejections (§3.2).
   Product territory; fix freely.

### 4.2 Operational gotchas (each cost real time — HANDOFF §4 + this week, verified against code)

7. **The usage window is the binding constraint.** A stall is usually the weekly Claude Max
   window, not a bug. A hit cap surfaces as a bare `claude exited 1` with no diagnostic —
   deliberately classified TRANSIENT (pause-until-reset). **Auth expiry is now distinct and
   PERMANENT**: 401/oauth-expired/not-logged-in wording fails fast with a notify (commit
   `3d3474a`); fix is `claude login`. Don't re-blur these two classes.
8. **The L9R fence flags uncommitted edits — including OPERATOR edits — to orchestrator source
   at every settle**, quarantining them to `state/quarantine/` and failing the settling task.
   Rule: **never edit tracked files while the daemon breathes**; commit at a pause, then
   relaunch (DV-7 dev-mode is the eventual fix, v3 Slice 9). The fence is hermetic under
   pytest; it once quarantined its own uncommitted implementation, and on 10 Jul it ate a
   prepared operator patch mid-flight (recovered from the quarantine's forensic copy — which
   doubles as a vault).
9. **`state/flagship` is read ONCE at daemon boot** (`main()` → `read_flagship`); repointing it
   requires a restart. Under BG-2 with no certification, a non-flagship project is silently
   starved (why `smoke-test` stalled).
10. **Stopping properly**: `STOP` must be at the repo **root**; a full stop is `touch STOP` plus
    `pkill -9` of both `run_forever` and `control.daemon` (SIGTERM won't interrupt a daemon
    mid-LLM-call). A deliberate STOP stays down; the supervisor only relaunches crashes — and
    since `4971a75` a BG-1 refusal (exit 3) **writes STOP itself** and stays down (a
    deterministic refusal can never be fixed by relaunching). The feeder also honours STOP and
    exits — **restart it after any STOP window** (`pgrep -f slice_feeder ||` relaunch).
11. **`.git/index.lock` recurs in this environment** — `rm -f .git/index.lock` (host-side; the
    sandbox mount cannot remove it).
12. **One orchestrator per account** — two daemons share and exhaust one weekly window.
13. **The daemon loads once** — restart after editing any module; restart = resume via replay.

### 4.3 Design invariants you must not casually break

14. **All state mutation on the main thread** (`control/pool.py`) — only the LLM subprocess
    call runs on workers. Do not move claiming/settling/git onto threads.
15. **Budgets derive from the event log** (BG-3) — never keep a retry counter only in memory,
    and never key era-opening on a payload field the overseer's directives can't set (the 12
    Jun resurrection died at first failure exactly this way).
16. **`sys.executable`, never bare `python`** — single source `validation/gates.py::
    DEFAULT_TEST_COMMAND` and `registry/agents.py::_PY` (macOS exit-127 trap).
17. **Illegal transitions are no-ops** — code that *relies* on an exception from the state
    machine is wrong; check `transition()`'s return instead. `cancel_task` routes
    QUEUED→BLOCKED→FAILED because QUEUED→FAILED is deliberately not legal.
18. **Reserved `__` projects** are skipped by monitoring and exempt from BG-2 — don't name a
    real project with a `__` prefix.
19. **New laws ship with their check in the same change** — the PRIME meta-check turns an
    unchecked active law into a red build. The same applies to prose ground truths: if you
    change the wording of the completion contract in CLAUDE.md/QUALITY_CHARTER or the HANDOFF
    read-order paths, update `tests/test_docs_claims.py` in the same change.
20. **`monitor_projects` re-evaluates only on signature change** (`_signature` = the
    (task_id, status) set) — status-neutral edits won't trigger re-evaluation; parked
    (abandoned-dormant) projects are skipped entirely.
21. **The Overseer's session must run from a stable cwd** (repo root) or continuity silently
    breaks; `--dangerously-skip-permissions` is not sticky across `--resume`.
22. **Companion processes act only through existing channels** — the feeder and the GUI read
    the log and write to `state/inbox/`; neither may mutate daemon state or the log directly.
    A new companion must follow the same discipline.

---

## PART 5 — TECHNICAL REFERENCE & GLOSSARY

### 5.1 Key data structures (`core/models.py`)

**Task**: `task_id, title, task_type, status(queued|in_progress|done|failed|blocked),
depends_on[], payload{}, acceptance_criteria[], artifacts[], retries, max_retries(3),
parent_task_id, project("default"), priority(0)`.
**Event enum**: CLAIM, COMPLETE, FAIL, BLOCK, UNBLOCK, REQUEUE, RECLAIM.
**AgentResult**: `ok, summary, artifacts[], spawned_tasks[], metadata{}, block_reason,
cause (L10 — a failed result must explain why), intent("inform_complete")`.
**Event-log kinds** (`dispatch/repository.py`): task_created, task_transition, task_result,
task_cancelled, task_reprioritised, project_status, project_confirmed, assurance_result,
project_abandoned, escalation, attempt_inputs.

### 5.2 Task-type → agent → model (`registry/agents.py`)

plan→task_manager (claude/sonnet) · implement→builder (claude/sonnet) · test→tester
(claude/sonnet) · validate→judge (**openai/codex**) · oversee→overseer (**claude/claude-fable-5**)
· research→researcher (claude/sonnet; Fable after the Overseer eval, DV-4) · `control` → executed
by the daemon, never an agent.

### 5.3 Environment variables & sentinels

| Name | Effect |
|---|---|
| `AGENTIC_BUDGET_USD` | budget cap (daemon default 10.0; run_forever sets 1e6) |
| `AGENTIC_MAX_WORKERS` | concurrent agents (pool default 8; run_forever sets 20) |
| `AGENTIC_PROJECT_CONCURRENCY` | writers per project tree (default 1) |
| `AGENTIC_DEADLINE_HOURS` | bounded run; writes STOP at expiry |
| `AGENTIC_<AGENT>="provider:model"` | per-agent model reroute (outages; live: `AGENTIC_JUDGE="claude:opus"`) |
| `STOP` (repo root) | drain and stay down (supervisor + feeder honour it; BG-1 exit 3 writes it) |
| `state/KILL` | immediate kill-switch (governor) |
| `state/flagship` | BG-2 flagship (HUMAN-ONLY; read once at boot; currently `orchestrator-v3`) |
| `state/v3_slice.json` | slice-feeder cursor `{"last_fed": n}`; missing = 1 (only the seed out) |
| `state/telegram.json` | `{token, chat_id}` — enables notify + operator chat |

### 5.4 CLI surfaces

`python -m control.daemon` (run) · `nohup bash run_forever.sh > supervisor.log 2>&1 &`
(supervised) · `nohup python3 -m control.slice_feeder > state/slice_feeder.log 2>&1 &` (v3
ritual) · `python -m control.enqueue "<goal>" --project X` · `python -m control.intake
"<goal>" --project X --accept "…" "…"` · `python -m control.confirm [project]` ·
`python3 -m control.scorecard [--since-hours N]` · `python -m edge.server` (:8765) ·
agents runnable directly: `echo '{"task":{…}}' | python -m agents.builder`.
Gates locally: the `run-gates` skill = `ruff check .` + `lint-imports` + `pytest tests/`.
Skills in `.claude/skills/`: run-gates, graphify-update, add-agent, enqueue-goal.

### 5.5 Glossary

- **Law** — a governance rule in `charter/laws.py` with a named machine check; PRIME enforces
  the pairing. Key ids: L2 layers, L4 purity, L6 bounded autonomy, L7 atomic IO, L8 single
  entrypoint, L9/L9R self-mod quarantine/fence, L10 self-explaining failures, L11 total state
  machine, BG-1 boot self-test, BG-2 depth-before-breadth, BG-3 durable budgets, BG-5 guardian
  liveness, D25 acceptance-by-execution.
- **Gate** — an automated completion check (tests/acceptance/judge/authenticity); **assurance
  ladder** — post-gate hardening (rerun→mutation→execution→adversarial).
- **Era** — the budget window for a project's planner/overseer counters; opened by a rescope
  plan or closed-and-reopened by an abandonment watermark. (Pending patch: each v3 slice
  opens its own era.)
- **Flagship** — the single project BG-2 allows before a first certification; human-set.
- **Zero-touch (DG-2)** — self-certification: no human gate blocks completion.
- **FOREVER-IMPROVE** — post-certification improvement rounds until the planner returns [].
- **PA** — deterministic failure-cause→action rules, overseer-evolved, curated promotion.
- **Overseer** — the persistent meta-agent (one resumed Claude session; CORE+EXTRA handoff).
- **Wedge** — ≥2 outstanding overseer pulses (BG-5): stop stacking, alarm.
- **Fence (L9R)** — settle-time quarantine+revert of writes to the orchestrator tree; the
  quarantine dir doubles as a forensic vault (`state/quarantine/*.patch` are recoverable).
- **Slice / slice feeder** — one of the v3 charter's ten certifiable increments; the feeder
  (`control/slice_feeder.py`) drops slice n+1 on certification n (the ritual, automated).
- **ME-1..8 / spec 17** — the ratified modular-engine positions (kernel+ports+manifests,
  fail-closed loader, selfdev promotion pipeline, container runner) — v3-charter input, no v2
  retrofit; ME-1..3 folded into v3 Slices 2–3.
- **Inbox / confirmations** — file-drop channels the daemon ingests (multi-writer safe).
- **DV-1..7 / DG-n / F-n / R-n** — ratified v3 laws / decision-gates / findings / risks in
  `docs/planning/` (13 for DV, 08 for the registry, 09 for build governance, 16 for the build
  charter, 17 for the modular engine).
- **Da Nang model** — design the operator can steer from a phone; survives zero-touch as the
  notification + Telegram + edge surfaces.

### 5.6 ASSUMPTIONS

| # | Assumption | Confidence | Verify |
|---|---|---|---|
| 1 | ~~User-gate removal is ratified (DG-2)~~ — confirmed and reconciled into docs (commit `3d3474a`); now machine-checked | Settled | `tests/test_docs_claims.py` |
| 2 | `scheduling/` and `selfdev/` are intentional empty seams | High | 4-line `__init__.py`s; L9 contract references selfdev |
| 3 | ~~Codex judge unusable until parser validated~~ — parser validated 2026-06-01; the LIVE blocker is Codex CLI **auth**, hence the `AGENTIC_JUDGE="claude:opus"` reroute (weakens F5 while active) | High | `infra/llm.py` docstring; run_forever env |
| 4 | The archived `tasks.events.log.archived-*` marks a deliberate log reset alongside `projects.archived-*` | Medium | ask operator; timestamps match |
| 5 | The fence-quarantined patch (`state/quarantine/selfmod_1783652034.patch`: per-slice eras + tunable intervention cap) is intended to be applied at the next daemon pause | High | operator session 10 Jul; apply via `git apply` then commit + restart |

---

## STATE BLOCK (final)

- `INDEX_VERSION`: v2-2026-07-10.1 (refresh of v2-2026-07-08.1 at HEAD `4753656`)
- `FILE_MAP_SUMMARY` (live source; archived projects excluded): edge/server.py (578) ·
  control/daemon.py (530) · agents/overseer.py (372) · dispatch/repository.py (280) ·
  memory/overseer.py (240) · infra/llm.py (220) · memory/knowledge.py (216) ·
  dispatch/dispatcher.py (216) · control/slice_feeder.py (182) · infra/worktree.py (166) ·
  control/scorecard.py (164) · control/pool.py (154) · infra/triage.py (118) ·
  validation/* (six gates) · charter/laws.py (77) · registry/agents.py (74) · core/* (123) ·
  ~6.3 k live lines, 58 test files / ~359 test functions.
- `OPEN_QUESTIONS`: (a) apply the quarantined per-slice-era + tunable-cap patch at the next
  daemon pause (until then all ten slices share one 20+3 era); (b) fix Codex CLI auth and drop
  `AGENTIC_JUDGE` to restore F5 cross-provider independence; (c) fix the v3 foundation README's
  stale "Slice 1 of 8" self-description (judge scope-rejections); (d) teach per-slice "done"
  semantics to the judge via the charter (v3-charter lesson, §3.2).
- `KNOWN_RISKS`: the weekly usage window is the single bottleneck; fence-vs-operator friction
  until DV-7 dev-mode lands (Slice 9); overseer interventions at 3/era shared across the whole
  v3 build until the patch applies; git index.lock recurrence; judge reroute weakens F5 while
  active; notify() silence is by design — the log is the truth.
- `GLOSSARY_DELTA` (since 07-08): Slice/slice feeder, ME-1..8/spec 17, fence-as-vault.

*End of knowledge document.*
