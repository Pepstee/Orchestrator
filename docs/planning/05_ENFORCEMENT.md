# Orchestrator v2 — 0.6 Enforcement Toolchain

*The prime directive made concrete: **a law without a machine-check is a wish.** Every charter
law (Ln) maps to a named, automated check that runs in CI, pre-commit, or at boot. This is the
machinery v1 lacked — and the direct structural defence against drift (R10). Tight; the snippets
are illustrative specs, not the final implementation.*

---

## 1. Law → enforcement map

| Law | Check (named) | Tool | Runs at | Fails when |
|-----|---------------|------|---------|-----------|
| **L1** single source of truth | `test_no_duplicate_domain_types`, `test_registries_canonical` | pytest | CI | a domain type (e.g. AgentResult) defined twice; a responsibility has 2 definitions |
| **L2** dependency arrow inward | `contract: layers` | import-linter | CI + pre-commit | any back-edge (e.g. `core` imports `dispatch`) |
| **L3** module size budget | `test_loc_budget` (≤500, configurable) | pytest | CI + pre-commit | any source file exceeds the budget |
| **L4** deliverables pristine | `test_project_tree_purity` | pytest | CI + runtime | a project tree contains orchestrator scratch (handoffs/reports/state/logs) |
| **L5** no arbitrary choices | `test_model_resolves_from_registry`, `test_reported_model_eq_chosen` | pytest | CI | an agent picks a model not via the registry; emitted usage model ≠ chosen |
| **L6** bounded autonomy | `test_every_loop_has_cap`, `test_budget_killswitch_halts`, `test_assurance_loop_terminates` | pytest | CI | a loop lacks a max-iteration/budget cap; kill-switch doesn't halt |
| **L7** file preservation | `test_no_raw_writes_outside_io`, `test_delete_via_tombstone` | pytest (AST scan) | CI + pre-commit | `open(...,'w')`/`unlink` used outside the io module; delete without tombstone |
| **L8** one supervised entrypoint, no false alarms | `test_lifecycle_smoke`, `test_startup_grace`, `test_single_pid_lock` | pytest (integration) | CI | start→stop→resume not clean; health fires during startup grace; two instances run |
| **L9** self-mod quarantined | `contract: selfdev-isolated`, `test_selfmod_flag_default_off` | import-linter + pytest | CI | `core/dispatch/validation` imports `selfdev`; self-mod on by default |
| **L10** failures self-explaining | `test_failure_event_has_cause`, `test_agent_io_schema` | pytest | CI + runtime | a failure event has empty `cause`; an agent payload/result violates schema |
| **L11** total state machine | `test_transition_table_total` | pytest | CI | any `(state, event)` pair is undefined (no more `queued→blocked` spam) |
| **prime directive** | `test_every_law_has_a_check` | pytest | CI | a law exists in the charter with no linked check |
| **A2 (charter)** evals required | eval harness (see §3) | pytest + eval runner | CI on behaviour change | a behaviour change ships without a passing/non-regressing eval |

---

## 2. The four components

**(a) import-linter contracts** (`importlinter.ini`) — encode 0.4 §2's layering:
```
[importlinter:contract:layers]
name = inward-only dependency arrow
type = layers
layers =
    edge
    control
    dispatch | scheduling | validation
    pa
    agents
    memory
    infra
    core
# core/infra/registry import nothing outward; higher layers may import lower.

[importlinter:contract:selfdev-isolated]
name = self-modification quarantine
type = forbidden
source_modules = core, infra, dispatch, scheduling, validation, control, agents
forbidden_modules = selfdev
```

**(b) Architecture tests** (`tests/architecture/`, pure pytest, no LLM) — the structural laws:
```python
def test_loc_budget():               # L3
    over = [f for f in src_files() if loc(f) > BUDGET]
    assert not over, f"god-files forming: {over}"

def test_reported_model_eq_chosen():  # L5
    for agent in registry.agents():
        assert agent.run().usage["model"] == registry.model_for(agent.name)

def test_project_tree_purity(tmp_project):  # L4
    build_into(tmp_project)
    assert not any(p in tree(tmp_project) for p in SCRATCH_DIRS)

def test_transition_table_total():    # L11
    for s in TaskStatus: 
        for e in Event:
            assert (s, e) in TRANSITIONS  # explicit, even if -> no-op

def test_every_law_has_a_check():     # prime directive
    assert {law.id for law in CHARTER.laws} <= {c.law for c in registered_checks()}
```

**(c) Lint gate** — `ruff (E,F)` at test-collection time (port v1's pytest-hook gate; pin the
ruff version in `requirements-dev.txt` so the gate doesn't drift red on a contributor's newer
linter — a real v1 papercut).

**(d) Eval harness** (`evals/`) — charter law A2; encodes the 0.5 falsification tests:
- **regression evals** — a fixed task set; a behaviour change must not decrease pass-rate.
- **judge-calibration eval** — the self-generated known-correct/known-wrong pair set;
  fails if high-confidence approvals fall through to test failures (R3).
- **bugs-per-$ eval** — the maturation north-star; tracked over time (P2 prediction).
- **single-model-parity eval** — the foundational falsification (R1): v2 vs thin single-model
  harness at equal cost; a *tripwire*, reported not blocking.

---

## 3. Where it runs

```
pre-commit  : ruff · import-linter · test_loc_budget · test_no_raw_writes   (fast, local)
CI (PR gate): full architecture/ suite · import-linter contracts · ruff ·
              registry tests · lifecycle smoke · eval regression + judge-calibration
boot self-test: policy/registry self-test · single-PID lock · startup grace ·
                failure-event schema validation (runtime guards from L8/L10)
```

CI order mirrors cost: lint → architecture (cheap, deterministic) → integration smoke →
evals (most expensive, last). A red at any stage blocks merge.

---

## 4. The "law intake" rule (keeps the directive honest)

> **Adding or amending a charter law requires adding/changing its check in the *same* change.**
> `test_every_law_has_a_check` enforces this mechanically: a law with no linked check fails the
> build. This is what stops v2's ruleset from decaying into prose the way v1's N1–N12 did.

---

## Note for 0.7
This is the "Methods / Reproducibility" section of the Phase 0 paper: it makes the charter
executable. Combined with 0.5's kill-criteria, the build is now accountable to machines and to
evidence — not to discipline alone.
