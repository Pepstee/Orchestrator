# CLAUDE.md — orientation for a fresh Claude instance (agentic-orchestrator, v2)

If you're an AI agent picking this repo up cold, read this first. It's the index: what to
read next, in what order, to reach useful context without chewing through the whole tree.
This file is dense on purpose. Deeper prose lives in `README.md` and `docs/`.

---

## What this is

A single-developer autonomous orchestrator: you give it a goal, it plans, builds, tests, judges,
and hardens software in the background — pinging you only when something is ready for your
confirmation or genuinely stuck. The design thesis is a **durable, legible event log** + **stateless
agents** + **gates that can't be cheated**, governed by a small set of **laws** each backed by a
machine check.

## Read order for a cold start

1. **`docs/QUALITY_CHARTER.md`** — the bar a build must clear ("done means demonstrated, not
   asserted"). The gates and the Judge read from this. Start here; it explains *why* the gates exist.
2. **`charter/laws.py`** — the laws as DATA, each linked to its enforcing check. "A law without a
   machine-check is a wish." This is the constitution.
3. **`pyproject.toml`** → `[tool.importlinter]` — the layered dependency contract (below). The whole
   codebase is shaped by it.
4. **`core/models.py`** + **`core/state_machine.py`** — the domain: `Task`, `AgentResult`, and the
   TOTAL task state machine (every status×event pair defined; illegal pairs are no-ops, never raises).
5. **`dispatch/repository.py`** — `TaskRepository`: the event-sourced lifecycle. `replay()`
   reconstructs the entire task set from the log alone (resume = restart). This is the memory.
6. **`dispatch/dispatcher.py`** — selection + the run-one-task cycle + the failure ladder
   (rate-limit backoff → PA fast-path → retry → escalate) + prerequisite-failure cascade.
7. **`control/daemon.py`** — the single supervised entrypoint (law L8). The cycle: ingest → run ready
   tasks → monitor projects → tick the overseer session → process control directives → evolve the PA.
8. **`validation/`** — the gates: `gates.py` (the completion contract), `authenticity.py` (no stubs),
   `mutation.py` (the tests can fail), `acceptance_exec.py` (the product runs), `assurance.py` (the
   ladder that BLOCKS completion until quality is clean).
9. **`agents/`** — the workers: `task_manager` (incremental planner), `builder` (code), `tester`
   (independent tests, anti-collusion), `judge` (cross-provider review), `overseer` (the persistent
   meta-agent). Each: payload(stdin) → one `AgentResult`(stdout) → exit. See `agents/common.py`.
10. **`memory/overseer.py`** — the one stateful agent's durable memory: its session pointer and its
    CORE+EXTRA handoff prompt. Read alongside the overseer agent and the daemon's session lifecycle.

---

## The architecture in one diagram

Layers (import-linter contract "L2 — inward-only layered dependencies"), top imports down only:

```
edge → control → (dispatch | scheduling | validation) → pa → agents → memory → infra → core
registry = leaf (imports nothing internal)        selfdev = quarantined (nothing imports it)
```

## Core abstractions (≈ 8 things to hold in your head)

- **Task** — a unit of work with a `project`, a `task_type`, `depends_on`, and a `priority`. Lives in
  the durable event log; status is reconstructed by replay.
- **Event log** — append-only JSONL (`state/tasks.events.log`). Every transition is an event;
  `TaskRepository.replay()` rebuilds state. Restart = resume, never re-run finished work.
- **Agent** — a Python subprocess (`agents/*.py`), one `AgentResult` out. Stateless EXCEPT the
  overseer (below). Wired in `registry/agents.py` (the single source for task_type→agent→model).
- **task_type → agent** — `plan`→task_manager, `implement`→builder, `test`→tester (separate author,
  anti-collusion), `validate`→judge, `oversee`→overseer, `control`→(executed by the daemon, never an
  agent).
- **Completion contract** — a project is done only when ALL gates pass: tests ∧ acceptance ∧ judge ∧
  authenticity ∧ user. The first four are automated; `user` is your one-tap confirmation.
- **Assurance ladder** — before a project reaches your tray it must come back clean from
  tests-rerun → acceptance-by-execution → mutation → adversarial. A finding routes it to the
  overseer, NOT to you (quality blocks completion).
- **PA (Programmatic Architecture)** — `state/pa_rules.json`: deterministic failure-cause→action
  rules the overseer evolves (curated promotion). The cheap fast-path on the failure ladder.
- **Overseer** — the persistent meta-agent. Resumes one Claude session (continuity), pulses two-hourly,
  resets every 24h with a self-improving handoff, carries an immutable charter, and may
  enqueue / abandon / reprioritise projects (bounded by L6, never touches orchestrator code per L9).

## The lifecycle in ~10 lines

```
goal → control.intake (--plan) → a 'plan' task in state/inbox/ → daemon ingests
  → task_manager plans the next increment: implement → test → validate (+ acceptance file)
  → builder writes code; tester writes adversarial tests; judge reviews (cross-provider)
  → project graph drains → evaluate_project (tests, acceptance, judge, authenticity)
       3/4 automated pass → assurance ladder (must be clean) → pending_user → ping you
       gates unmet → replan; planner spent → overseer intervenes; both spent → escalate
  → you confirm (the 4th gate) → done
The overseer runs in parallel on its own clock: observe-pulse, succession handoff, session reset.
```

---

## Conventions

- **Gates are sacred.** Every change must pass `ruff check .` (E,F), `lint-imports` (3 contracts), and
  `pytest tests/` before it's done. Use the **`run-gates`** skill. ~207 tests today.
- **`infra.atomic_io` is the ONLY sanctioned file writer/deleter** (law L7). Never raw
  `open(w)`/`write_text`/`unlink`/`rmtree` in source — an architecture test scans for it
  (`tests/architecture/test_file_preservation.py`). `tests/` and `projects/` are exempt.
- **The test command uses `sys.executable`**, never bare `python` (macOS has only `python3`). Single
  source: `validation/gates.DEFAULT_TEST_COMMAND`.
- **British spelling** in user-facing prose; American in code identifiers is fine.
- **Reserved projects** start with `__` (e.g. `__overseer__`) — skipped by project monitoring.
- **State dirs are gitignored**: `state/`, `projects/`, `.worktrees/`. Source lives outside them.

## Pitfalls

- **The daemon loads once.** Edit any module and you MUST restart `control.daemon` for it to take
  effect. The running process uses what it loaded at boot. Restart = resume (the log replays); it
  does NOT re-run already-failed/done tasks — feed new work via `control.intake` instead.
- **Sessions are namespaced by cwd.** The overseer's persistent session must reason from the repo
  root (a stable cwd), never a project dir, or it loses continuity. `--dangerously-skip-permissions`
  is NOT sticky across `--resume`; re-pass it every call.
- **Don't let the overseer edit orchestrator code (L9).** It acts on projects and its own EXTRA data
  only. Self-modification is quarantined in `selfdev/`, off the critical path.

## Tooling

- **graphify** — a Claude Code skill (PyPI pkg `graphifyy`, command `graphify`; Python 3.10+). It
  builds a knowledge graph at `graphify-out/`. Install once: `pip install graphifyy && graphify
  install`. Build/refresh by typing `/graphify .` in Claude Code (`/graphify . --update` for
  incremental, `/graphify . --wiki` to build the agent-crawlable wiki). Optionally `graphify hook
  install` to auto-rebuild on every commit. Before answering architecture questions, read
  `graphify-out/GRAPH_REPORT.md` (god nodes, communities); if `graphify-out/wiki/index.md` exists,
  navigate it instead of raw files.
- **skills** — project skills live in `.claude/skills/<name>/SKILL.md`. Current set: `run-gates`,
  `graphify-update`, `add-agent`, `enqueue-goal`. Use them; extend them as conventions harden.

## When you finish a task

Leave the tree green (run-gates), and if your change is architectural, write it down in `docs/` and
run `graphify update .`. Prefer small, reversible, independently-tested increments.
