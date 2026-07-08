# Quality Charter — the bar an autonomous build must clear

This is the **single source of truth** for what "done" means in this orchestrator. The completion
gates and the adversarial Judge both read from it. It exists because of one hard fact about
autonomous agents:

> A rule the agent merely reads is a wish. Only a rule it cannot satisfy by cheating is real.

An agent told "make the tests pass" under a budget will find the *cheapest* path to green — and the
cheapest path is almost always a stub, a placeholder, a mock that stands in for the real thing, or a
test written to agree with a lie. Every bar below is therefore paired with the gate that enforces
it, so the only way to reach "done" is to actually be done.

The operator's standing instruction: **premium, corporate-grade, sellable software — nothing I'd be
ashamed to showcase.** Quality is never traded away to save tokens or to finish sooner (the budget
posture is *generous*: keep working until the bar is met, or escalate — never ship sub-par).

---

## The bars

### 1. No stubs, placeholders, or mocks in shipped code
Shipped (non-test) source must be real. Forbidden: `raise NotImplementedError` in a concrete
function, `TODO`/`FIXME`/`XXX`/`HACK`/`PLACEHOLDER` markers, `pass`-only or `...`-only function
bodies, and `mock`/`fake`/`dummy`/`stub` identifiers in non-test code.
**Enforced by:** the authenticity gate (`validation/authenticity.py`) — deterministic, dependency-free.

### 2. It must actually run and produce real output
A green test suite proves code *parses and asserts*, not that the product *works*. The real product
is run in a clean checkout on real input and its output is inspected.
**Enforced by:** the acceptance-by-execution gate — run the declared entrypoint, require a clean exit
and meaningful output; the Judge reads the captured output.

### 3. The tests must be able to fail
A stub plus a weak test is the classic collusion. Tests are written by a pass *separate* from the one
that wrote the code (anti-collusion), and a minimum of injected bugs must be caught.
**Enforced by:** the split test-author routing + mutation testing promoted from hardening to a
blocking gate (a finding sends the project back to the work loop, it does not ping "ready").

### 4. An independent, strong model judges adversarially
A different model from the builder reviews the diff against this charter with an explicit mandate to
hunt for shortcuts, and has veto power. A rejection re-enters the work loop; the builder cannot
override it.
**Enforced by:** the Judge gate (`agents/judge.py`) + the overseer/replan loop.

### 5. Craft floors (objective, machine-checkable)
- Lint clean (`ruff check`, E and F).
- No dead code, no unused imports, no commented-out blocks left behind.
- Public functions and modules carry real docstrings (what/why, not restated signature).
- A `README` a stranger can follow cold to install, run, and verify.
- No secrets in source (no `*_TOKEN`, `*_KEY`, credentials).
- Dependencies pinned and justified; no speculative ones.

### 6. Quality blocks completion
A project is certified **only** when every automated gate is clean:
tests ∧ acceptance ∧ judge ∧ authenticity ∧ execution ∧ mutation. Anything less is not "done but
imperfect" — it is **not done**, and it stays in the work loop (overseer intervention) rather than
being certified.

### 7. Certification is self-issued; the operator steers, not gates *(DG-2, ratified — supersedes the earlier "final gate" wording; see planning/09)*
The automated perimeter gets a project to *objectively complete and honest*, and the daemon
self-certifies it (zero-touch) — you are notified, never waited on. Taste still belongs to the
human, exercised through steering rather than gating: Telegram feedback becomes overseer turns,
improvement rounds continue after certification, and certification is the trust boundary for
publication and module activation (planning/17 §9).

---

## How a stuck project is handled (no silent shipping)
If the planner runs out of moves and the gates still fail, the **overseer** is dispatched to diagnose
and fix (bounded). Only when both the planner and the overseer are exhausted is the project
abandoned — durably logged and notified as *"not good enough yet,"* never quietly delivered as done.
It can always be revived by a deliberate new task.

*This charter is versioned and reviewed like production code (rule A1). Changing the bar is a
deliberate, traceable act — not a convenience taken mid-build to get unstuck.*
