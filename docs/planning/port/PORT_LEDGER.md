# v1 → v2 Port Ledger (FOUNDATION §5, finally executed)

*Staged 9 June 2026 into `port/v1/` — the canonical donor copies. The v1 installation retires
once every row below is dispositioned (Estate A, `10_DELETE_MANIFEST.md`). Per BG-7: each row
closes as code-in-v2 **plus its test**, or an explicit waiver with owner + expiry. Reworks must
honour L1: one canonical implementation in v2 — reconcile, never duplicate.*

| Module | What it is (proven in v1) | Disposition | Lands in | Closes |
|--------|---------------------------|-------------|----------|--------|
| `error_triage.py` | 3-class failure taxonomy (TRANSIENT / RECOVERABLE / PERMANENT), `MAX_TRANSIENT_REQUEUES=5`, rate-limit-as-transient, repair-spawn on last retry | **Rework-port** — replaces v2's string-matched classifier (B1) | Phase C | F9, I16 |
| `admission_control.py` | AIMD concurrency control against rate-limit cascades | **Port as-is** | Phase C | R6 mitigation |
| `io_utils.py` | Atomic write ladder (mkstemp+fsync+replace) + tombstones | **Reference** — v2 likely has an equivalent; reconcile to ONE (L1/L7) | Phase B | L7 |
| `task_checkpoint.py` | Mid-run crash-recovery snapshots, injected on retry | **Port** — the timeout-resume mechanism | Phase C | I2 |
| `session_checkpoint.py` | 30-min warm-start summaries of queue state | **Reference** — fold into journal/digest design | Phase B | — |
| `reasoning_session.py` | Per-task failure context accumulated across retries | **Rework-port** — feeds the replan rung with prior-attempt context | Phase C | BG-3 |
| `supervisor.py` | Restart guard (max 20), graceful `RESTART_REQUESTED` sentinel, health file | **Port the pattern** — gives v2 hot-restart (no more manual bounces) under launchd | Phase B | I13, L8, I23 |
| `watchdog.py` | Journal-scanning health monitor + alert emission | **Reference only** — its alert semantics are the 5,384-spam pathology; donor for the signal list, rebuilt under BG-4 | Phase B | BG-4 |
| `velocity_monitor.py` | 5-state stall-detection machine over 6 FS signals | **Port with reworked thresholds** | Phase F | soak instrumentation |
| `tail_metrics.py` | Deterministic ops metrics from the event log (no LLM) | **Port** | Phase C | 09 §7 metrics |
| `preflight.py` | Boot-time environment validation (CLI, git config, disk, quota window) | **Donor** for the boot self-test | Phase B | BG-1 |
| `health_check.py` | PID + staleness verdict with exit codes (healthy/degraded/down) | **Donor** for the dead-man checks | Phase B | BG-5 |

**Not ported, deliberately:** the three-tier self-mod policy (seam stays shut — L9);
`orchestrator.py`/`dashboard.py` god-files (their lessons travel as laws L3/D3, not as code);
the 2,600-test suite wholesale (each ported module brings or gains its own tests; the rest of
the suite's knowledge is encoded in the architecture checks).
