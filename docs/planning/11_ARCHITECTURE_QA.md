# 11 — Architecture Q&A: how the orchestrator actually works

*Thirty-four questions in technical-adjacent language, answered from the code as it stands
(9 June 2026, 288 tests green), plus five questions only the operator can answer. Written to be
read end-to-end; each answer names the mechanism so you can find it in the source.*

---

## A. Boot and lifecycle

**1. What happens, in order, when the daemon starts?**
It acquires a PID lock (one instance, ever — L8). It runs the boot self-test: every test file
named by an active charter law must exist, collect, and pass, or the daemon exits without
dispatching anything (BG-1, no bypass). It replays `state/tasks.events.log` to reconstruct every
task and every budget exactly as they were. It re-queues tasks orphaned mid-flight by the last
shutdown, and revives transiently-failed tasks *that still have budget*. It reads the flagship
file, arms the budget governor and kill-switch, then enters the serve loop.

**2. What is "the event log" and why is it the centre of everything?**
An append-only JSONL file. Every task creation, state transition, result, budget charge, and
certification is one appended event; nothing is ever edited in place. The running state of the
system is just a *fold* over this log, so a crash or restart loses nothing — the log is replayed
and the world is rebuilt, including failure counts and attempt fingerprints. Restart = resume,
never re-run.

**3. How do I stop it, and what's the difference between the three stop mechanisms?**
`touch STOP` (or Ctrl-C/SIGTERM) is a graceful stop: in-flight agents finish, then the loop
exits. `state/KILL` is the kill-switch: all dispatch halts immediately, engaged by you or
automatically when the budget cap is hit. The burn-rate breaker is the soft third: it parks paid
project work for 30 minutes but keeps the overseer thinking. STOP ends the process; KILL and the
breaker end the spending.

**4. What survives a crash or a `kill -9`?**
Everything that matters: the task graph, budgets, fingerprints, certifications (event log),
the overseer's beliefs/journal/dossiers (its mind directory), and the burn-pause (durable
event). What dies: in-flight agent subprocesses (their tasks are reclaimed to QUEUED at next
boot) and the in-memory session cache (the overseer rehydrates from disk).

**5. The daemon loads code once — what does that mean operationally?**
Any edit to orchestrator source takes effect only at the next process start. The running daemon
uses what it imported at boot. So: change code → restart (cheap, because restart = resume) —
never assume a live daemon picked up a fix.

## B. Work: intake → plan → build

**6. How does work enter the system?**
One task = one JSON file dropped in `state/inbox/`. Each cycle the daemon folds inbox files into
the event log and deletes them. Writers (you, scripts, the overseer) never touch the log
directly — multi-writer-safe by construction. The dubbing-studio re-scope contract is sitting
there now.

**7. What is a task, precisely?**
A unit of work with a type (`plan`/`implement`/`test`/`validate`/`oversee`/`control`), a
project, dependencies, a payload, acceptance criteria, and a priority. Its status lives in the
state machine: QUEUED → IN_PROGRESS → DONE/FAILED (+BLOCKED), with every status×event pair
defined — illegal transitions are no-ops, never crashes (L11).

**8. Who decomposes a goal into tasks?**
The task_manager (planner) agent. It receives the goal plus the current project state (what's
done, what failed and why, what files exist) and plans the *next increment* — not a grand
upfront plan. When a project's graph drains but gates are unmet, the daemon feeds failures back
and replans, up to 20 planning passes (L6 cap).

**9. How do several agents work without trampling each other?**
Two mechanisms. Per-project concurrency is capped at 1 — one writer per project tree, so
intra-project merge conflicts structurally can't happen; concurrency lives *across* projects.
And each file-editing task runs in its own ephemeral git worktree, merged back on success; a
genuine collision surfaces as a merge-conflict failure rather than silent clobbering.

**10. Which model does each agent use, and who decides?**
The registry (`registry/agents.py`), single source of truth (L5): planner/builder/tester on
Sonnet, judge on OpenAI Codex (different provider from the builder — anti-collusion), overseer
on **Fable 5** (promoted 9 Jun; strongest model to the highest-stakes judgement). Per-agent env
overrides (`AGENTIC_OVERSEER=claude:opus`) exist for provider outages — reversible, no code
edit.

**11. Why is only dubbing-studio allowed to run?**
BG-2, depth before breadth: until the system has *earned one real certification*, dispatch is
restricted to the human-set flagship (`state/flagship`). Eight half-built projects taught
nothing the first project wouldn't have, at eight times the burn. After the first certification
the cap lifts and the DG-4 ratchet governs breadth (double after a clean soak, halve on breach).

## C. Failure handling and budgets

**12. A task fails. What exactly happens next?**
Its cause string is classified once (infra/triage): PERMANENT → fail immediately, surfaced —
no retries burnt on a deterministic dead-end. TRANSIENT (rate limit, restart-kill, env fault) →
requeue without penalty, but at most 5 times per task. Otherwise RECOVERABLE → the PA rulebook
is consulted (deterministic known fixes), then the ordinary retry budget (3), then a recorded
escalation and terminal failure.

**13. What stops the 90-retry loop from ever happening again?**
Three independent walls. The transient budget (a misclassified cause caps at 5). The durable
retry budget (counters derive from the event log — a restart reconstructs them, so restarts
can't launder budgets, which they previously did). And the input fingerprint: a conflict-class
failure may only be re-attempted if the hash of (task fields + payload + project HEAD rev)
*changed* — a rebase/replan re-permits, an identical retry is refused at the second attempt.

**14. What's the difference between "the task failed" and "the project failed"?**
Tasks fail constantly and cheaply; that's the ladder's job. A project only *stalls* when gates
are unmet and the planner is out of moves — then the overseer intervenes (up to 3 times), and
only when both are spent is the project abandoned: logged, slot freed, re-enqueueable. Under
zero-touch nothing parks waiting for a human.

**15. What happens when the Claude usage window is exhausted?**
The CLI's failure (even the bare, message-less `exited 1` that once stranded a night's work) is
classified transient; in-flight work finishes, the batch backs off, tasks requeue without
penalty. Combined with the burn breaker, the system idles politely through the window instead of
thrashing — June's log shows 994 rate-limit failures from exactly that thrash.

**16. What does the burn-rate breaker actually measure?**
The trailing 40 run outcomes. With ≥20 recorded and success below 40%, paid project work parks
for 30 minutes (durably — restart can't clear it) while the overseer keeps pulsing. It re-arms
with a fresh window so it can't flap.

**17. Can a prerequisite failure strand a graph?**
No — failed prerequisites cascade: any task depending on a failed one is itself failed with a
self-explaining cause (L10), transitively, so graphs always terminate instead of hanging as
"in progress" forever (the overnight-stall bug).

## D. Gates and certification

**18. What does it take for a project to be DONE?**
All four automated gates: tests (its own suite passes), acceptance (every declared criterion
*executes* against the real product with real output), judge (independent cross-provider
review), authenticity (no stubs/mocks/placeholders in shipped code). Then the assurance ladder
must come back clean (tests-rerun → acceptance-by-execution → mutation → adversarial). Then —
because you ratified zero-touch (DG-2) — the orchestrator self-certifies, notifies you, and
opens a forever-improve round. No human gate; the spot-audit breaker (pending) is the
compensating control.

**19. How is "acceptance" different from "tests"?**
Tests prove the code asserts what its author expected. Acceptance proves the *product does
something real*: each line of the project's `acceptance` file is one executable criterion; all
must exit 0 with non-empty output. No declaration = FAIL (no default-pass gates under
zero-touch), and a criterion containing a mock-tell is refused — June's "finished" demo
literally ran `--mock` against a deleted package.

**20. What does the authenticity gate catch?**
An AST scan of shipped (non-test) source: `NotImplementedError` bodies, `pass`-only functions,
TODO/FIXME/STUB markers, and Mock/Fake/Dummy classes outside tests. It's why dubbing-studio
currently *fails* — `MockTTSBackend` ships in the live package. The cheapest path to green is
now to implement the real thing.

**21. How do we know the gates themselves aren't broken?**
Calibration at both poles. Negative control: the gates were pointed at three projects the old
system certified — all three failed for true, specific reasons. Positive control: minimal honest
fixtures pass the same gates. A gate that fails everything would flunk the positive control; a
gate that passes everything would flunk the negative.

**22. What is "forever-improve" and when does it stop?**
After certification the planner opens improvement rounds (security, UX, perf, features). It
stops when a round produces nothing (planner returns empty) — and under DG-6, an improvement
must prove a measurable delta worth its tokens, so polishing can't become an infinite burn.

## E. The overseer

**23. What is the overseer, in one sentence?**
The one persistent agent: a steward that pulses hourly, reasons about the whole system against
its own durable memory, and may enqueue, abandon, or reprioritise project work — never touch
orchestrator code (L9).

**24. Where does its memory actually live?**
On disk, in `state/overseer/`: `BELIEFS.md` (its model of normal, self-updated, capped),
`journal.jsonl` (append-only: every observation and decision with rationale — readable by you
any time), and per-project dossiers. Every pulse wakes reading its own last entries and writes
back before sleeping. The Claude session is a cache: delete it and the next pulse rehydrates.

**25. What happens at the 24-hour session reset?**
Succession: it writes a self-handoff (immutable CORE format + its own evolvable EXTRA
refinements), the fresh session is seeded with it, and beliefs/journal persist untouched.
Compaction, not amnesia.

**26. What if the overseer itself dies or wedges?**
BG-5: two pulses outstanding (wedged) or two consecutive pulse failures raise an alarm — once
per episode. A wedge stops new pulses stacking; a failure streak still permits fresh pulses,
because a new session is the self-heal and budgets bound the cost. Even a failed pulse writes a
journal line, so there are no silent gaps.

**27. What are its hard limits?**
It never modifies orchestrator code or config (L9 — and the flagship file is provably outside
every agent's reach). Its directives are bounded (max 5 enqueues per pulse), executed by the
daemon as logged `control` tasks, reversible. It runs on Fable 5 but is bound by the same laws
as everything else — no unbounded guardian.

## F. Safety, control, and money

**28. What can the system never do, even fully autonomous?**
Leave the machine. Push to remotes, publish, send, spend on external services — policy-forbidden
unless whitelisted per project at intake (stop-and-don't, DG-2.4). The flagship contract
explicitly says nothing leaves the machine.

**29. What's the worst realistic failure now, and what does it cost?**
A novel failure mode the taxonomy misclassifies as transient: it gets 5 free requeues + 3
retries ≈ 8 agent runs before terminal failure — and if many tasks do this at once, the burn
breaker parks everything within ~20 runs. Compare June: one such mode ran 90 times on one task
and 1,573 times overall before a human noticed.

**30. Why does the budget show $0 — is money even being tracked?**
On the Max subscription the CLI reports no marginal dollars, so the cash cap rarely bites. The
*real* scarce resource is the usage window, and the real guards are run-based: transient caps,
retry budgets, the burn breaker, flagship-only breadth. Tokens-per-certified-criterion is the
efficiency metric once certifications exist.

**31. What tells a future session what happened here?**
The corpus (docs/planning 00–11), the delete manifest, the port ledger, `RUN_LEDGER.md`
(incidents → the tests that now prevent them), 18 charter laws each naming its check, and the
overseer's own journal. The repo is the memory; chat history is disposable.

## G. Operating it day-2

**32. How do I check on it from a glance?**
`state/overseer/journal.jsonl` tail (what it's thinking), the 12-hourly status notification,
`git log` in the project trees (what's actually being built), and the GUI (edge/server). After
Phase G: the same as signals over Tailscale from any device.

**33. How do I add the next project once dubbing-studio certifies?**
Drop a plan task in the inbox (goal + acceptance criteria — the D2.5 contract pattern), and
widen `state/flagship`/breadth per the DG-4 ratchet. Mock-heavy old projects get culled and
re-seeded through this path (manifest C9.x), substantial ones repaired.

**34. What would make the whole design wrong, and how would we know?**
The corpus's own falsification tests (04): if a thin single-model harness matches this at equal
cost on multi-step builds, the orchestration is over-engineered; if bugs-per-$ never improves,
the maturation thesis fails. The eval harness that measures these is still pending — until then
the honest claim is "instrumented and bounded", not "proven optimal".

---

## H. Five questions only the operator can answer

**H1.** Soak bar: 7 days at ≥95% run-success before doubling breadth — confirm or adjust?
**H2.** When dubbing-studio certifies: which project is second — and does any old project get
culled outright rather than re-scoped?
**H3.** Notifications: is the current desktop `notify` channel enough until Phase G, or do you
want an external channel (e.g. Telegram) earlier?
**H4.** D3 (full audit + standing SLOs): opt any project in now, or keep all at D2.5?
**H5.** The v1 archive (Block 3) and folder deletion (A4): when do you want to run them?
