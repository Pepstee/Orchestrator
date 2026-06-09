---
name: run-gates
description: Run the agentic-orchestrator green-gate ritual — ruff (E,F) + import-linter (3 contracts) + pytest. Use before declaring any change done, and whenever asked to "check the gates" or "is it green".
---

# Run the gates

Every change to this repo must pass all three gates before it is "done". Run them from the repo root:

```bash
python3 -m ruff check .
lint-imports
python3 -m pytest tests/ -q
```

If `lint-imports` is not on PATH, it ships with `import-linter`: `python3 -m pip install import-linter`
(or add the user's local bin to PATH).

What each gate guards:
- **ruff (E,F)** — real errors (bare except, unused imports, shadowing), not style. Auto-fix safe
  issues with `ruff check . --fix`.
- **import-linter** — the architecture: the L2 layered dependency order, "registry is a leaf", and
  "L9 — selfdev is quarantined". A layering violation means you imported the wrong direction.
- **pytest** — the behavioural + architecture test suite (the contract). All must pass.

Report the outcome as: `ruff PASS | import-linter 3/3 | N passed`. If anything fails, fix it before
moving on — do not mark work complete with a red gate (that is the one rule the orchestrator enforces
on itself).
