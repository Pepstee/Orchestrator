# Orchestrator v2 — historical release

> [!IMPORTANT]
> This repository is the preserved **v2** of an evolving Orchestrator product. It is an old
> version retained for provenance, comparison and portfolio evidence. It follows v1 and precedes
> v3, but each major version has a deliberately independent repository and Git history.

## Original v2 documentation

A reliable, observable, GUI-first orchestrator that takes one goal and autonomously drives it
to completion through a small team of specialised agents — trustworthy enough to leave running
for days, legible enough to audit every step, and cheaper/more deterministic the longer it runs.

This is the v2 rebuild. Its design replaced v1's prose-only architectural constraints with
machine-enforced laws and deterministic gates.

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

## Historical status

v2 development has ended. The repository is preserved as the completed second-generation
architecture; subsequent product evolution occurs in the separate v3 line.
