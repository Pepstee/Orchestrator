# Session Handoff — orchestrator, as of 8 July 2026

*For a fresh agent (e.g. Fable 5) picking up this work. Mapping the code gives you structure; this
gives you the live state and the decisions that are NOT recoverable from the code. Read this first,
then follow the read-order in §7.*

---

## 1. TL;DR — where things actually stand

- **The orchestrator works.** Verified this session: it planned and built a real throwaway project
  (`smoke-test`) end-to-end — plan → implement → done — with live Claude calls. Every failure this
  session was environmental (auth, usage limits, uncommitted-tree fence), **not** a design defect.
- **It is currently STOPPED** — `STOP` sentinel at the repo root, supervisor + daemon killed — because
  the Claude weekly usage window is exhausted.
- **Direction:** build a clean **v3** orchestrator, and have the **v2 orchestrator build it** — as a
  separate product in `projects/orchestrator-v3/`, sliced into ten independently-certifiable increments.
- **v3 is already kicked off:** `state/flagship = orchestrator-v3`, and a Slice 1 `plan` task is in the
  durable log. It failed on the rate limit and will re-run when the window resets.

## 2. The single biggest constraint

The **weekly Claude Max usage window** is *the* bottleneck (the recovery plan named it as the scarce
resource). Nearly every stall this session traced to it or to auth. A ten-slice v3 build is
token-heavy — budget and pace accordingly. Do not assume a stall is a bug before checking the window.

## 3. Key decisions made this session

- **Build v3 clean (fork), not evolve-in-place.** DV-1 originally argued "evolve" — the operator
  overrode it, for good reasons: the `.git/index.lock` recurs on *every* change in this environment
  (not a one-off), plus escaping accumulated entropy and making the KB load-bearing from day one. This
  is settled; do not relitigate.
- **v3 is built BY the orchestrator, as a product.** Building a separate codebase in `projects/` is
  **not** self-modification (L9 stays intact) — the agents never touch their own running code.
- **DV-1..7 laws** (`docs/planning/13_V3_CAPABILITY_PLAN.md`): capability-plus-gate discipline; KB is
  load-bearing (DV-2); research is gated deep-or-fail (DV-3); modules plug in with a **fail-closed
  seam-gate** (DV-6); **DV-7** — the daemon runs a clean/committed checkout while operators develop out
  of its path (a `state/DEVMODE` sentinel), because the self-mod fence can't tell operator edits from
  agent tampering.
- **Port verbatim, don't reinvent** (`FOUNDATION §5`, the port v2 itself skipped): the KB module
  (`memory/knowledge.py`), the research module (`agents/researcher.py` + `validation/research_contract.py`),
  v1's `error_triage.py` failure taxonomy, the laws + gate designs, and the seeded core+spine.
- **Enforcement spine BEFORE features** — the ordering v2 skipped and paid for (R10 / `07 §8.3`).

## 4. Recurring operational gotchas (each cost real time — do not rediscover)

- **Claude auth expires** → surfaces as `claude exited 1` / 401. Fix: `claude login`. (Known hardening
  TODO: a 401 currently misclassifies as *transient* and loops — it should fail fast and notify.)
- **The L9R self-mod fence flags UNCOMMITTED operator edits** as an agent modifying orchestrator code —
  it quarantines them (backups in `state/quarantine/`), fails tasks, and spams identical alerts. Fix:
  commit before the daemon runs, or use DV-7 dev-mode. Building v3 inside `projects/` sidesteps it
  entirely (product territory, fence-skipped).
- **`state/flagship` is read ONCE at daemon boot** — repointing it requires a daemon restart. BG-2 does
  *flagship-only dispatch until a first certification exists*, so a non-flagship project is silently
  starved (this is exactly why `smoke-test` stalled).
- **`.git/index.lock` recurs in this environment** and blocks all git writes → `rm -f .git/index.lock`.
- **Stopping properly:** `STOP` must be at the repo ROOT; a full stop is `touch STOP` **plus**
  `pkill -9` of BOTH `run_forever` and `control.daemon`. Plain SIGTERM won't kill a daemon mid-call.
- **One orchestrator per account** — two daemons share (and exhaust) the same weekly window.
- **Stray `projects/p`** (a broken git repo) collides with the test project named "p" → `rm -rf projects/p`.

## 5. Where the v3 artifacts live (NOT yet in this repo)

The v3 **build charter** (the ten-slice plan + the exact intake commands) and the **green foundation**
(`core/`, `infra/`, `dispatch/`, tests — 9 passing, ruff clean) are in a scratchpad at
`outputs/orchestrator-v3/`. They are NOT in this repo, so codebase analysis alone will miss them. They
need to move in: the charter → `docs/planning/16_V3_BUILD_CHARTER.md`; the foundation → seed
`projects/orchestrator-v3/`.

## 6. What NOT to do

- Don't run two orchestrators on the shared Max account.
- Don't develop in the daemon's working tree without committing (or dev-mode) — the fence will fight you.
- Don't build v3 breadth-first (all ten slices at once) — depth before breadth, each certified first.
- Don't relitigate evolve-vs-fork (decided: fork clean) or the no-mocks / done-means-demonstrated laws.

## 7. Read order (read the prose — don't just map files)

1. `CLAUDE.md` — the cold-start index.
2. `docs/OPERATING_GUIDE.md` — how to run/feed/watch/stop it, plus the gotchas.
3. `docs/QUALITY_CHARTER.md` + `charter/laws.py` — the bar and the laws-as-data.
4. `graphify-out/wiki/` — a page per component (rebuild with the `graphify-update` skill if stale).
5. `docs/planning/` — the corpus: `09` (recovery & build governance), `13` (v3 capability plan, DV-laws),
   `14` (KB module spec), `15` (research module spec), and the v3 build charter (§5, once moved in).
6. `docs/planning/RUN_LEDGER.md` — the incident log.

## 8. Immediate next steps (when the usage window resets)

1. Auth: `claude login`; verify `claude -p "Reply with exactly: ok"`.
2. Clean the tree: commit outstanding work; `rm -f .git/index.lock`; `rm -rf projects/p`.
3. Move the v3 artifacts into the repo (§5).
4. Confirm `state/flagship = orchestrator-v3`, then start the daemon (`rm STOP && nohup bash
   run_forever.sh > supervisor.log 2>&1 &`) — it reads the flagship at boot and dispatches v3.
5. The Slice 1 `plan` task is already in the log; it re-runs. When it certifies, load Slice 2 from the
   charter (§4 of the charter has the exact intake command).
6. Watch the usage window throughout — it is the binding constraint on the whole build.
