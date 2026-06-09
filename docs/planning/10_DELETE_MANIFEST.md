# Orchestrator v2 — 10. DELETE Manifest (governed demolition)

*Authority: DG-7 (09 §4). Created 9 June 2026. Status legend: ☑ done · ☐ ready · ⛔H blocked on
host access (this session's sandbox cannot touch Mac processes) · ⛔M blocked on the v2 repo
being mounted.*

**The law, in one line each:** delete redundant / outdated / legacy / architecturally-misfit /
cheaper-to-rewrite code; keep anything whose regeneration would burn tokens on ~99%-similar
output; archive before delete (v1 has **no version control**); a control path is deleted only
after its replacement's drill is green; every deletion is a row here.

---

## 1. Kill procedure (run on the Mac — prerequisite for Estate A)

```
ps -p 45634 -o pid,command          # confirm the v1 supervisor
kill -9 45634                        # supervisor FIRST
pgrep -fl orchestrator               # find the current child (56404 as of 21:38 UTC, 9 Jun)
kill -9 <child_pid>
pgrep -fl orchestrator               # must return nothing
crontab -l 2>/dev/null | grep -i orch ; launchctl list | grep -i orch   # nothing may relaunch it
```

A partial kill was already attempted on 9 Jun: child 45637 died, the supervisor respawned it
as 56404 (`restart_count` 0→1). Supervisor first is not advice; it is the observed mechanism.

## 2. Estate A — v1 installation (`~/Documents/claude-orchestrator-main`, ~31,400 LOC, retires whole)

| Row | Action | Gate | Status |
|-----|--------|------|--------|
| A1 | Stop both processes (§1) | — | ☑ 9 Jun ~21:50 UTC — verified dead: state mtimes frozen 3.5+ min on a ~1/min writer |
| A2 | Stage port organs → `orchestrator-v2-planning/port/v1/` (12 modules + ledger) | — | ☑ |
| A3 | Archive the folder (zip; exclude caches **and `ui/node_modules` — 2.0 G of the 2.1 G total**) — before any deletion; no VCS exists | A1 | ☐ operator (amended Block 3) |
| A4 | Delete the v1 installation (operator action — it is the currently-mounted workspace; do last, after the port lands in v2) | A3 + port landed | ⛔H |

Keep-list for Estate A: nothing stays live. Knowledge survives as `port/v1/` + the planning
corpus + regression tests (BG-7). The 2,600-test suite is not ported wholesale — its *lessons*
arrive via the port ledger's per-module tests.

## 3. Estate B — v2 orchestrator code (⛔M until mounted; rows from verified evidence)

| Row | Target | Reason-class | Replacement / gate | Status |
|-----|--------|--------------|--------------------|--------|
| B1 | String-matched failure classifier | legacy logic, re-broke solved problem | ported `error_triage` (rework), Phase C cutover | ⛔M |
| B2 | Toothless gate-proxy bodies in `validation/gates.py` | working incorrectly | Phase D gates with teeth (tuple itself stays — ratified DG-2) | ⛔M |
| B3 | Overseer chat-resume **dependency** (resume-or-die path) | working incorrectly | BG-6 stateless pulse; resume demoted to optimisation | ⛔M |
| B4 | STOP-sentinel control path | legacy | deleted only when the signals surface (Phase G) is live — L8 | ⛔M |
| B5 | Boot-revival special-cases superseded by triage | redundant | dies with B1 | ⛔M |
| B6 | Any `*_new/_v2/_fixed/_final` files | N10 violation | scan on mount; rename-to-canonical or delete | ☑ scan clean, 9 Jun |
| B7 | Unreferenced modules | dead code | import-graph scan on mount; archive + delete | ⛔ Phase B |
| B8 | Remnants of the reverted conflict-as-transient change | dead branches | confirm clean revert; delete leftovers | ⛔ Phase B |
| B9 | Stuck `.git/index.lock` at repo root — blocked **all** commits (same FS class as v1's tombstone lore) | operational | deletion permission granted; lock cleared; git functional again | ☑ 9 Jun |

## 4. Estate C — project deliverables (DG-7 cost rule per item)

*Archive for every row: `projects.archived-20260609-delete-manifest.tar.gz` — 561 K, 596 entries,
repo root, gitignored. Created before any deletion.*

| Row | Target | Disposition | Status |
|-----|--------|-------------|--------|
| C1 | `dubbing-studio/tts_studio/` (dead duplicate) | **Archived; delete rides the project's re-scope** — zero-import check FAILED: `acceptance.py` imports the dead copy. The acceptance file was testing the abandoned implementation; Phase D recompiles it, and the package dies in that change | ☑ archived · delete-on-rescope |
| C2 | `digital-twin/panalytics/` (629 orphan lines) | Same pattern — live refs: `acceptance.py`, `tests/test_analytics.py`, `tests/test_ingestion.py` | ☑ archived · delete-on-rescope |
| C3 | `local-llm-stack/local_llm/` | Same pattern — live refs: 4 test files incl. `test_mock_backend_full.py` | ☑ archived · delete-on-rescope |
| C4 | `projects/p/` stray (+ its stuck nested `.git/index.lock`) | DELETED (archived first) | ☑ 9 Jun |
| C5 | pytest caches: repo-root `pytest-cache-files-7dxcl93g`, writing-assistant `pytest-cache-files-_050yovb` + `.pytest_cache` | DELETED | ☑ 9 Jun |
| C6 | Leftover `projects/situation-monitor/` dir (2.0 M) | Husk confirmed — `projects/edge/` carries the full `situation_monitor` package + tests. DELETED (archived first) | ☑ 9 Jun |
| C7 | edge still packaged as `situation_monitor`; tests don't collect | KEEP + repair (rename diff is small — DG-7) | ⛔M |
| C8 | writing-assistant `RecursionError` at collection | KEEP + repair | ⛔M |
| C9.x | Each project's product code (8 projects) | case-by-case at intake re-scope: mock-heavy paths → DELETE + re-seed from contract; substantial real logic → KEEP + repair. One row per project, added at Phase E/F | ⛔M |

**The cost rule for C9.x:** estimate repair (diff size × iteration risk) vs regeneration
(size × generation + integration risk). Within ~2×, prefer KEEP — regenerating 99%-similar code
is paying full price for a haircut. Mocked stubs almost always re-seed; working cores almost
always stay.

## 5. Execution order

1. §1 kill (host) → A3 archive → Estate B/C zero-risk rows (C1–C5) the moment the v2 repo is
   mounted → B-rows ride their phase cutovers (DG-5: replacement and deletion in the same
   change) → C9.x at intake re-scoping → A4 last.
2. Every row closed here gets its `RUN_LEDGER.md` incident/decision reference where applicable
   (BG-7 applies to deletions too: a deletion that breaks something becomes a test).
