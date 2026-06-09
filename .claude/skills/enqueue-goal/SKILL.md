---
name: enqueue-goal
description: Submit a goal to the running orchestrator so it plans and builds it. Use when the operator wants to start (or re-run) a project, e.g. "have the orchestrator build X".
---

# Enqueue a goal

Goals enter through the intake funnel, which drops a task into `state/inbox/` that the running daemon
ingests on its next cycle (multi-writer-safe; works whether or not the daemon is up).

**Preferred — let the Task Manager decompose it incrementally (`--plan`):**

```bash
python3 -m control.intake '<the full goal, in one quoted string>' --project <project-name> --plan
```

- Use a **fresh project name** (e.g. `deal-sniper-v3`) so a re-run does not tangle with an old failed
  graph. Reserved names starting with `__` are not allowed.
- The planner will decompose into `implement → test → validate` increments and, for a runnable
  product, expect an `acceptance` file (used by the acceptance-by-execution gate).

**Deterministic alternative (a fixed build → judge pair, no planner):**

```bash
python3 -m control.intake '<goal>' --project <name> --accept "criterion one" "criterion two"
```

After enqueuing, the daemon must be running to pick it up:

```bash
AGENTIC_JUDGE=claude:opus AGENTIC_BUDGET_USD=1000 python3 -m control.daemon
```

(`AGENTIC_JUDGE=claude:opus` routes the judge to Claude when Codex is unavailable; the env override is
reversible — drop it to restore the registry default.)

Confirm it landed by checking that a `plan` task for your project appears in the event log / GUI. A
goal you submitted from a different machine than the daemon's will not reach it — enqueue on the box
the daemon runs on.
