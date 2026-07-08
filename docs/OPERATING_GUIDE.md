# Operating Guide — how to run and use the orchestrator

*The consolidated operator how-to. The code-understanding docs (below) explain how the system is
built; this explains how to **run, feed, watch, and stop** it, and the accumulated small operational
truths that were previously tribal knowledge. If you are a fresh agent or a human picking this up
cold, read this to operate it and `CLAUDE.md` to understand it.*

---

## 0. Where the system's knowledge already lives (read-order for a cold start)

A blank agent gets its context here, in this order:

1. **`CLAUDE.md`** (repo root) — the cold-start index for the codebase. For this project it is
   auto-loaded into an agent's context, so a fresh agent starts here whether it means to or not.
2. **This file (`docs/OPERATING_GUIDE.md`)** — how to operate it (the gap CLAUDE.md doesn't fill).
3. **`docs/QUALITY_CHARTER.md`** — the bar a build must clear ("done means demonstrated").
4. **`charter/laws.py`** — the laws as data, each linked to its enforcing check.
5. **`graphify-out/wiki/`** — a page per component (AgentResult, BudgetGovernor, each gate…). The
   place to look up any one part in detail. If stale, rebuild with the `graphify-update` skill.
6. **`docs/planning/00–15`** — the design corpus (vision → risk → enforcement → recovery → v3 plan).
   Rationale, not operation.
7. **`docs/RUNBOOK_GIGABYTE.md`** — the machine-specific *deploy* runbook (Windows + WSL2).
8. **`.claude/skills/`** — operational skills: `run-gates`, `enqueue-goal`, `add-agent`,
   `graphify-update`.

So: architecture and rationale are well covered. This guide is the operating layer on top.

## 1. Mental model (30 seconds)

You give it **one goal**; it plans an increment, builds code, writes independent tests, has a
cross-provider judge review it, and drives the project to a four-gate certification — pinging you only
when something is ready for your one confirmation or is genuinely stuck. A persistent **Overseer**
meta-agent watches the whole portfolio, keeps projects moving, and self-improves across resets.

Five worker agents + the Overseer, wired once in `registry/agents.py`:
`plan → task_manager`, `implement → builder`, `test → tester` (independent, anti-collusion),
`validate → judge` (cross-provider), `oversee → overseer`, plus `research → researcher` (v3).

The lifecycle: `goal → control.intake → a plan task in state/inbox/ → daemon ingests → plan →
implement/test/validate → four gates (tests ∧ acceptance ∧ judge ∧ authenticity) → your confirmation
→ done`. State is an append-only event log; **restart = resume** (it replays; it never re-runs
finished work).

## 2. Control surfaces

- **Shell / CLI** — start, stop, feed goals, read logs. The source of truth.
- **GUI** — `python -m edge.server` → `http://127.0.0.1:8765/?token=…`. Health, projects, the
  "NEEDS YOU" tray, activity feed. Token is `AGENTIC_GUI_TOKEN` or a persisted random one
  (`state/gui_token.json`).
- **Telegram** — notifications to your phone and simple commands (report, stop), if
  `state/telegram.json` is configured.
- **SSH over Tailscale** — everything the shell does, remotely (see the runbook).

## 3. Daily operations

**Start** (the supervisor keeps the daemon alive; you launch the supervisor once):
```
cd <repo> && rm -f STOP && nohup bash run_forever.sh > supervisor.log 2>&1 & disown
sleep 30 && tail -3 supervisor.log
```

**Feed a goal:**
```
python3 -m control.intake "<clear goal sentence>" --project <name> --plan \
  --accept "acceptance criterion 1" "acceptance criterion 2" "…"
```
`--plan` routes it through the planner (recommended). `--accept` locks acceptance criteria — the more
concrete and *executable* they are, the better the gates can judge "done". (Skill: `enqueue-goal`.)

**Monitor:**
```
tail -f supervisor.log                       # launches / relaunches / exits
python3 - <<'EOF'                            # a quick state summary from the event log
import json,collections
ev=[json.loads(l) for l in open('state/tasks.events.log') if l.strip()]
t={}; [t.__setitem__(e['data']['task']['task_id'],[e['data']['task']['project'],'queued'])
      for e in ev if e.get('kind')=='task_created']
for e in ev:
    if e.get('kind')=='task_transition' and e['data']['task_id'] in t: t[e['data']['task_id']][1]=e['data']['to']
c=collections.Counter((p,s) for p,s in t.values()); print(dict(c))
EOF
```
Plus the GUI and Telegram. The Overseer's own reasoning is in `state/overseer/journal.jsonl`.

**Confirm a finished project (gate 4 — the only unfakeable gate):** when a project reaches
`pending_user`, it appears in the GUI's "NEEDS YOU" tray / a Telegram ping. Confirm it there (or drop a
file into the confirmations dir). This is your one asynchronous tap; the system never idles waiting for
it — other projects keep advancing.

**Stop — do it properly (this is the #1 operational trap):**
```
cd <repo> && touch STOP && pkill -9 -f run_forever && pkill -9 -f control.daemon
```
`STOP` must be at the **repo root** (the supervisor checks for it there — a `touch STOP` in the wrong
directory does nothing). Kill **both** the supervisor (`run_forever`) and the daemon (`control.daemon`)
— killing only the daemon leaves the supervisor to relaunch it in 5s. `SIGTERM` (plain `pkill`) does
not stop a daemon mid-agent-call; use `-9`. Verify: the event log stops advancing and
`supervisor.log` says "STOP present — staying down".

**Apply a code change:** the daemon loads its code **once at boot**. Edits do nothing until you
restart it (`pkill -9 -f control.daemon`; the supervisor relaunches with the new code; replay resumes).

## 4. Configuration knobs (environment variables)

| Var | Effect |
|-----|--------|
| `AGENTIC_MAX_WORKERS` | max concurrent agents (default 20) |
| `AGENTIC_PROJECT_CONCURRENCY` | agents per project (default 1 — one writer per tree, no intra-project merge conflicts) |
| `AGENTIC_BUDGET_USD` | imputed spend cap; the kill-switch trips at it |
| `AGENTIC_DEADLINE_HOURS` | writes STOP at expiry (a strictly bounded run) |
| `AGENTIC_JUDGE`, `AGENTIC_OVERSEER`, `AGENTIC_<AGENT>` | reroute one agent's model, e.g. `AGENTIC_JUDGE=claude:opus`, without editing code (provider-outage escape hatch) |
| `AGENTIC_GUI_HOST` / `AGENTIC_GUI_PORT` / `AGENTIC_GUI_TOKEN` | GUI bind + auth |
| `AGENTIC_LLM_TIMEOUT` | per-call subprocess timeout |
| `AGENTIC_NOTIFY_MUTE` / `AGENTIC_NOTIFY_PLAIN` | silence / simplify notifications |

## 5. The golden rules (the small things that bite)

- **One orchestrator per account.** The Claude Max / Codex accounts are a shared budget. Never run two
  daemons against them — stop the Mac's before launching the Gigabyte's. Two daemons quietly halve (and
  can exhaust) your weekly window. A forgotten idle daemon still counts.
- **Never develop in the daemon's working tree.** The L9R self-modification fence cannot tell your
  uncommitted edits from an agent tampering with orchestrator code — it will quarantine your work and
  spam alerts. Either run the daemon on a clean/committed checkout while you edit on a branch/worktree,
  or set the dev-mode sentinel (v3, DV-7). Practically: **commit your work before the next settle.**
- **A hit usage limit looks like a bare `claude exited 1`** (no message). The system now treats an
  opaque non-zero exit as *transient* — it backs off and resumes after the weekly reset, rather than
  failing the work permanently. So "stuck, all failing with exit 1" late in the week usually means
  "waiting for the reset", not "broken".
- **`state/` and `projects/` are gitignored by law.** A fresh clone has no event log, no project code,
  no secrets. Seed them separately (see the runbook). The event log deliberately does not travel —
  a fresh log is a clean slate.
- **Kill switch:** `state/KILL` (or the GUI/remote) halts paid work immediately, independent of the
  Overseer — so it works even when the Overseer is rate-limited and mute.
- **Keep the machine awake and on mains** — local inference and long runs die if the OS sleeps.

## 6. Troubleshooting (symptom → cause → fix)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| It won't stop / keeps coming back | `STOP` in the wrong dir, or only the daemon killed | `touch STOP` at repo root; `pkill -9 -f run_forever` **and** `-f control.daemon` |
| "an agent tried to modify the orchestrator's own code" alerts | uncommitted operator edits in the daemon's tree (L9R fence) | commit your work (or set dev-mode); files are backed up in `state/quarantine/` |
| Everything failing with `claude exited 1` | weekly usage limit reached | wait for the reset; it resumes automatically (transient) |
| A task loops / retries forever | a genuine (non-transient) failure mis-flagged, or a persistent merge conflict | check the cause in `state/tasks.events.log`; conflicts are bounded-retry then surface |
| `git` operations refuse ("remove the file manually") | stale `.git/index.lock` from a crashed git process | `rm -f .git/index.lock` |
| "merge conflict" on a task that shouldn't conflict | stale/locked worktrees | `git -C <proj> worktree remove -f -f <path>`; `git -C <proj> worktree prune` |
| A code change had no effect | daemon loaded old code | restart the daemon (`pkill -9 -f control.daemon`) |
| GUI shows nothing / can't reach it | wrong token or host bind | use the token from `state/gui_token.json`; check `AGENTIC_GUI_HOST` |
| Nothing is building, no errors | empty inbox / nothing queued | feed a goal via `control.intake`; restart does **not** re-run finished work |

## 7. Before every change: prove the gates

Never commit or launch on red. Run the full gate set (skill: `run-gates`):
```
python3 -m ruff check .        # E,F
python3 -m pytest tests/ -q    # the behavioural + architecture suite
lint-imports                   # the layered dependency contracts (L2, registry-leaf, L9)
```
The daemon re-runs the boot self-test at every start regardless — if it refuses to dispatch, it prints
why. That is the law working, not a defect.

---

*Deeper detail on any component: `graphify-out/wiki/`. Design rationale: `docs/planning/`. Deployment
on the Gigabyte: `docs/RUNBOOK_GIGABYTE.md`. This guide should be kept current as new operational
truths are learned — add them to §5/§6 the same day (the BG-7 spirit).*
