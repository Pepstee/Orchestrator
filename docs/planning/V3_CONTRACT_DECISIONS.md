# V3 COMPLETION-CONTRACT DECISIONS — Part IV points 3, 4, 5

*Operator decision artefact (C2/C3: rationale, alternatives, ownership). Drafted 18 Jul 2026 by
the Fable cowork session with the operator; RATIFIED when the operator sends the Telegram
ratification below or lands this file in the repo. Supersedes nothing; feeds the overseer's
live contract ledger.*

## Point 3 — Containers: gated off until the real-orb drill passes

**Decision.** The container execution path stays behind an explicit opt-in gate (env allowlist,
default OFF) until a real-runtime drill has passed ON THE OPERATOR'S OWN MACHINE: one dummy
agent run end-to-end through the actual `orb` CLI with the parsed AgentResult round-tripping.
The drill is a slice/improvement criterion; passing it flips the default. Until then the
uncontained fallback (already loud and metadata-marked) is the honest posture and the
constitution must say so — a deferred law entry, not silence.

**Why.** FABLE_V3_DESIGN_REVIEW F-3: the container invocation was built against an assumed CLI
shape; OrbStack is installed on the production machine, so mere detection would take the whole
factory down on unknown flags. Gates cannot see reality-accuracy; only an executed drill can.
**Rejected:** enabling on detection (the current shape — proven dangerous); removing container
code (the design is right, only unverified).

## Point 4 — Settle-time fence: build it, containment or not

**Decision.** The v3 daemon slice carries a settle-time fence criterion: after every task
settles, diff the orchestrator's own source tree; an unsanctioned delta quarantines that task's
work, fails it loudly, and journals the event. This ships REGARDLESS of container status —
containers, once proven, make it belt-and-braces; today it is the only belt.

**Why.** v2's L9R fence caught real incidents (12 Jun; the July cowork-commit desyncs). v3's L9
enforcement is gate-time-only (AST scan), which is nothing at the moment an uncontained
skip-permissions agent writes. Cheap: one function, proven pattern. **Rejected:** relying on
the static scan alone (temporal hole); waiting for containers (F-3 says that wait has no bound).

## Point 5 — Judge provider: F5 cross-provider RESTORED, not retired

**Decision.** v3's `infra/llm.py` grows a `codex` provider seam (a port of v2's, with two baked
lessons: provider-correct remedy text in every auth error — never "run `claude login`" for a
codex failure — and auth-error classification identical to the v2 triage taxonomy). The judge
agent, when it ships, runs cross-provider on the Codex account (currently Terra; Sol when the
GPT Max plan lands, per the pre-ratified phase-2 swap in v2's registry). Same-provider judging
is permitted ONLY as the documented outage fallback via the env override, never the default.

**Why.** Anti-collusion (F5) is a ratified doctrine that survived the entire Codex outage on
its merits; the outage is FIXED (codex login, 17 Jul), so the only reason to retire F5 was
operational and it no longer exists. The eval-gate's consecutive-PASS rule handles judge NOISE;
only provider independence handles judge COLLUSION. **Rejected:** retiring F5 (solves nothing
now); ollama as the second judge provider (local models are not yet judge-grade; revisit when
the eval harness says otherwise).

## Ownership and audit

DRI: the operator. The overseer verifies each decision's implementation against disk (its
lineage rule: finding text vs tree, never gate colour) and holds certification of slices 23-26
to the full Part IV checklist including these three. F-001 (criterion burial) countermeasure:
this artefact names its own verification — each decision above is DONE only when the overseer
cites the enforcing test/drill by path in the contract ledger.
