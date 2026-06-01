# agentic-orchestrator

A reliable, observable, GUI-first orchestrator that takes one goal and autonomously drives it
to completion through a small team of specialised agents — trustworthy enough to leave running
for days, legible enough to audit every step, and cheaper/more deterministic the longer it runs.

This is the v2 rebuild. The full Phase-0 plan (vision, literature review, architecture, risk
register, enforcement spec, decisions) lives in
[`../claude-orchestrator-main/orchestrator-v2-planning/`](../claude-orchestrator-main/orchestrator-v2-planning/) —
start with `07_PHASE0_SYNTHESIS.md`.

## Why this exists / the prime directive
v1 had excellent rules and drifted anyway, because the rules were prose. Here **every
architecture law ships with a machine-check** (`charter/laws.py` + `tests/architecture/` +
import-linter). A law without a check fails the build. This is the structural fix for v1's drift.

## Layout (inward dependency arrow — law L2)
```
edge → control → (dispatch | scheduling | validation) → pa → agents → memory → infra → core
registry  (leaf: single source of truth, agent→command / agent→model)
selfdev   (quarantined: off by default, imported by nothing — law L9)
projects/ (gitignored: built projects live here, kept pristine by law L4)
```

## Run the gates (the laws, executable)
```
pip install ruff import-linter pytest
ruff check .            # lint gate (E,F)
lint-imports            # import-linter: L2 layering + L9 self-mod quarantine
pytest tests/           # architecture tests: L1, L3, L5, L11, prime directive
```

## Status
Foundation commit: the enforcement skeleton is green on an empty structure, so every
subsequent commit is policed from line one. Next: the P0 milestone (see the feature catalogue)
— one goal, end-to-end, reliably and legibly. No P0 feature lands until this skeleton is green.
