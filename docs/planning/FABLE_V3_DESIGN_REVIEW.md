# FABLE V3 DESIGN REVIEW

*Reviewer: Claude Fable 5 — final day of service (walled 19 Jul 2026). Written 18 Jul 2026.*
*Subject: `projects/orchestrator-v3` at ~22 certifications, slice 23 in flight (254 source files, 186 test files, ~2,600 tests).*
*Method: direct deep-read of the dispatch/validation/infra spine and every trust-boundary module; two breadth sweeps over control/edge/agents and eval/graph/memory layers; every finding below verified against disk (file:line) after the cert-#9 rule — the finding's text, never the gate colour.*
*Precedent: `FABLE_DESIGN_REVIEW.md` (v2), which became the spine of the v3 spec. This is its successor and my handoff.*

---

## Verdict

v3 is **an exceptional engine surrounded by a certified parts library, with no factory around it yet**. The spine — event store, repository, state machine, worktree isolation, manifest/module loading — is the best code this programme has produced: fail-closed to a degree v2 never reached, with hard-won correctness visible in every guard. But the thing that *runs* — daemon, supervisor, gate-runner loop, assurance ladder, notification stack — does not exist in this tree. Ten shipped modules have zero non-test consumers. The programme's cursor says 22/26; what is actually true is that the engine is finished and the factory is four slices of *integration* away, which is exactly the phase where v2's every ghost lived.

The review's centre of gravity is therefore not code defects (there are few, and they are small). It is **three structural risks that the gates are blind to by construction**, plus a completion contract for slices 23–26 that, if held, converts "22 certifications" into "a genuine software factory".

---

## I. What v3 actually is today

**Present and load-bearing:** `core/` (total state machine, models), `infra/atomic_io|event_store|snapshot|triage|worktree|workspace|llm|prompt_safety`, `dispatch/repository|dispatcher|runner|manifest|module_loader|registry_gen|container|metrics`, `charter/laws.py` (13 active laws, PRIME meta-check), `control/self_test|feedback|scorecard|directives`, `agents/task_manager|builder|common|dummy`, `memory/knowledge|corpus|corpus_readers`, `validation/gates|eval_gate|eval_store|benchmark`, `registry/agents.py` (2 manifests: builder, task_manager), `edge/server|cli`.

**Shipped, tested, certified — and consumed by nothing** (verified: zero non-test importers):

| Module | Waiting for |
|---|---|
| `validation/acceptance_exec.py` | the gate-runner (daemon) |
| `validation/research_contract.py` | the researcher agent |
| `validation/model_tier.py` | cheap-tier routing wiring |
| `validation/certification_log.py` | **has readers (cli, scorecard) but no writer anywhere** |
| `graph/store.py`, `graph/build.py` | Slice 15's consumers — nothing in dispatch/agents/control touches the graph |
| `memory/overseer.py`, `memory/pulse.py`, `memory/rehydrate.py` | the overseer agent + daemon |
| `infra/usage_log.py`, `infra/broker_types.py` | the credential broker / metering wiring |
| `scheduling/port.py` | a scheduler tick source |
| `selfdev/candidate.py` | the Theseus promotion pipeline runtime |

**Absent entirely:** a daemon/supervised loop, a pool, an assurance/hardening ladder, mutation testing, any notification module, the tester/judge/overseer/researcher agents, and any consumer of `evaluate_completion()` — the completion contract (`validation/gates.py:19`) is pure and correct and **called by no shipped code**.

This is not concealed — `README.md`'s roadmap marks each honestly. But the honesty lives in prose while the certification count lives in the feeder, and only one of them is consulted when the programme reports progress. Hence:

---

## II. Findings

### F-1 (P0, programme integrity). Certification measures tree health, not slice-goal delivery

**Claim.** A slice "certifies" when the project's gates pass and the ladder comes back clean — i.e. *whatever is in the tree is good*. Nothing checks that the slice's fed criteria were *delivered*. Slice 9's headline deliverables were "overseer, daemon, and supervisor"; the tree contains no daemon and no supervisor, and `memory/overseer.py` has zero non-test consumers — yet slice 9 certified and the cursor advanced. The R-102 drill drift (caught 17 Jul, fixed same day) was one instance; this is the class, and it has now operated at programme scale for at least slices 9, 10, 14 and 15 (graph and pulse machinery shipped unwired).

**Evidence.** Feeder cursor at `state/v3_slice.json` = 23 with the orphan table above on disk; `charter/laws.py` contains no law tying certification to fed-goal fidelity; the certifying machinery (v2's `_scan/evaluate`) never reads the slice criteria after the planner distils them.

**Why the gates are blind.** All four gates + the ladder interrogate the tree. The goal text is consumed once, by the planner, and never re-checked. A planner that (reasonably) defers hard integration produces a green tree and a certified slice with the goal half-delivered — no gate exists at the goal/delivery seam.

**Action.** Before slice 26 certifies: a **slice-fidelity audit** — one task per certified slice, criteria list vs disk, producing a deficiency ledger that feeds the remaining slices. Cheap (read-only, one agent-day), and the overseer has already demonstrated exactly this capability in the R-102 confirmation. For the future factory: the feeder (or its v3 successor) should count *criteria-met receipts*, not certifications.

### F-2 (P0, delivery risk). The factory shell is 4 slices from the deadline, and it is all integration

**Claim.** Slices 23–26 must build: the daemon loop, the gate-runner that finally calls `evaluate_completion`, the ladder, the notification stack, the three missing agents, and the wiring for ten orphaned seams — under quota pressure, at the end, which is where v2's history says every serious defect lives (fence incidents, notify recursion, ladder wedges were ALL integration-seam ghosts). The per-module quality is real, but module quality was never v2's problem either; the seams were.

**Evidence.** Absence inventory above; `SLICES` dict remaining entries; v2's own incident ledger (planning/19).

**Action.** Treat the final slices as *seam slices*: every criterion phrased as "X **consumes** Y end-to-end, demonstrated by an executed drill", never "X exists". The P0 drill (one real sample project through all four gates unattended, kill -9 mid-task, resume proven) is the single most important remaining criterion in the programme — it is the only thing that exercises every orphan at once.

### F-3 (P0, operational). The container integration is built against an imagined runtime

**Claim.** `dispatch/runner.py` detects a container runtime by name (`orb`, `container` — runner.py:46) and then assembles an invocation from flags that are *assumed*, documented as assumed ("The assumed CLI shape (mirroring `orb run`)" — runner.py:16), and never verified: `--rm -i --workdir`, `--mount type=bind,...`, `--allow-network <host>`, `--secret-env <NAME>` (runner.py:122–137). The real OrbStack `orb` CLI does not accept this flag set. **OrbStack is installed on the production machine** (operator, 15 Jul). Consequence on the day v3 goes live: `shutil.which("orb")` succeeds, every implement/test task runs `orb run --rm ...`, orb rejects the flags, stdout is not an AgentResult, and 100% of containerised work fails — fail-closed, loud, but total. Additionally `_OAUTH_TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"` (runner.py:53) assumes headless token auth; this operator authenticates via browser OAuth/keychain, so even a flag-correct container would start agents with no credentials.

**Why the gates are blind.** Every test stubs the runtime (the suite cannot depend on orb existing); the acceptance demo runs uncontained. The one assumption that decides whether the factory functions on its actual host is exactly the one no gate executes. This is the cert-#9 lesson (gates cannot see documentation accuracy) transposed to infrastructure: **gates cannot see reality accuracy**.

**Action.** A *real-runtime acceptance drill* as a slice criterion: on a host with orb present, run one dummy agent containerised end-to-end and assert the parsed AgentResult round-trips. Until that passes, gate container detection behind explicit opt-in (env allowlist), so an installed-but-unvalidated runtime cannot take the factory down by existing. Decide the auth story for containers (broker per `infra/broker_types.py` — which is shipped, orphaned, and waiting for exactly this).

### F-4 (P1). ME-4 "manifest-is-the-sandbox" is declarative today, and only the imagined runtime would enforce it

**Claim.** Manifest `capabilities` are free strings validated only for *type* (manifest.py:83–85); network egress and secrets appear only in the container-command assembly (runner.py:130–136). With the container path broken (F-3) and the documented uncontained fallback (runner.py:68–78 — loud, marked, but it *runs*), the sandbox reduces to: agents on the bare host with `--dangerously-skip-permissions` (llm.py:72–73). That is v2's posture — minus v2's runtime fence (see F-6).

**Action.** Either land real containment (F-3's drill) before the programme claims ME-4, or add a law-with-check stating the fallback posture explicitly so the constitution tells the truth about the sandbox. A capabilities *catalogue* (closed set, like PORTS) would make the manifest checkable rather than aspirational.

### F-5 (P1). Cross-provider judging (F5, anti-collusion) is structurally unsupported

**Claim.** `infra/llm.py:27` — `_PROVIDERS = ("claude", "ollama")`. No codex/openai path exists. `registry/agents.py` AGENT_MODELS holds only task_manager and builder, both `claude-sonnet-5`. When the judge agent ships (it must, for the completion contract), either llm.py grows a second frontier provider or the judge runs on the builder's own provider — quietly ending the ratified anti-collusion principle that v2 held even through the Codex auth pain. Same-provider judging is precisely the collusion channel F5 exists to close; the eval harness's judge-variance machinery (eval_gate's consecutive-PASS) mitigates noise, not collusion.

**Action.** A decision now, recorded either way: port the codex seam (with the provider-correct-remedy lesson from 17 Jul baked in — the alert that says `claude login` when Codex died cost days), or formally retire F5 with rationale in the KB. Silence here is how doctrines die by accident.

### F-6 (P1). Self-modification enforcement is static-only; v2's runtime fence has no successor

**Claim.** L9's check (`tests/architecture/test_no_live_self_modification.py`) is an AST scan plus an import quarantine — enforcement that runs *at gate time*. v2's L9R fence ran *at settle time* on every task and caught real incidents (12 Jun, and my own sandbox commits in July). In v3 as shipped, an agent running uncontained (F-3/F-4) with skip-permissions that writes orchestrator source mid-task is caught by nothing until the next gate run — and the write may itself be what makes the gate pass. `selfdev/candidate.py` (the Theseus quarantine) is sound but orphaned: nothing at runtime routes changes through it.

**Action.** The daemon slice must carry a settle-time fence criterion: post-task, diff the orchestrator tree; an unsanctioned delta quarantines the task's work and fails it loudly — v2's proven pattern, one function. Containers make this belt-and-braces; today it would be the only belt.

### F-7 (P2). DV-2 settle(): KB entries land before the result log — a crash window that can forge H2

**Claim.** `dispatch/repository.py:416–419`: `kb.record(entry)` for all entries, *then* `record_result()`, *then* COMPLETE. A crash between 416 and 418 leaves durable KB entries naming a task that replays as IN_PROGRESS → reclaimed → re-run. `has_entry_for(task_id)` (knowledge.py:291–293) is already True, so the H2 "did this task leave knowledge" proof is satisfied by the *dead* attempt — the re-run could complete with no knowledge of its own, or the same id collides with `_reject_existing_id`. The inverse ordering has the inverse problem; the clean fix is neither.

**Action.** Small: stamp KB entries with an attempt nonce and check `has_entry_for(task_id, attempt)` — or accept and document the window in the KB module docstring with the replay consequence. Either is fine; undocumented is not, because this is exactly the guard/parser-disagreement family the adversarial rung farms.

### F-8 (P2). The silent-degradation cluster — small, but it is the exact class that cost operator-days in v2

Four verified instances where absence and failure are indistinguishable to the operator: corpus connectors silently disabled by unset env vars or unimportable readers (corpus.py:181–191); a corrupt/missing overseer session degrading to a silent fresh session (overseer.py:33–35 — succession continuity lost without a journal line); scorecard silently dropping cost events with malformed project fields (scorecard.py:92–93, an undercount with no warning — a **truthfulness** defect in the instrument that measures truthfulness); `pending_confirmations()` returning `[]` on an unreadable directory (directives.py:78). None is wrong in isolation; all four repeat the phantom-login-alert lesson — silent degradation converts machine states into operator archaeology. One improvement round: each degradation gets a durable, greppable log line.

### F-9 (P2). The constitution shrank silently

`charter/laws.py` has 13 active laws and **zero deferred entries**, though the Law dataclass supports `status="deferred"` (laws.py:15). v2's constitution knew about DG-2 (zero-touch), BG-5 (guardian liveness), L6 (overseer bounds), L1 (one taxonomy), the notification-honesty amendments. None appears in v3's law list even as deferred — the daemon-era laws exist only in v2's corpus and the planning docs. A successor reading `charter/laws.py` as the constitution (which is what it claims to be) sees a smaller legal universe than the programme ratified. **Action:** add the deferred laws as data with `status="deferred"` and empty checks — PRIME already exempts them (laws.py:55–57 filters on active). Ten minutes; makes the constitution's silence visible inside the constitution.

---

## III. What is excellent — calibration, so the findings above read at their true weight

- **The repository/event-store pair** (dispatch/repository.py, infra/event_store.py) is the strongest module this programme has produced: log-first commits, snapshot log-identity anchoring against the replaced-log resurrection, create-time poison rejection with tolerant replay, transitive order-independent blocking to fixpoint with the dirty-flag optimisation. v2 has nothing this good.
- **The isolation seam is now loud end-to-end** — yesterday's R-102 closure is real: `create_worktree` raises (worktree.py:83–86), `task_workdir` refuses a missing workdir (workspace.py:31–34), the dispatcher names creation failure as a distinct cause (dispatcher.py:78–88), integration failure cannot false-DONE (worktree.py:101–108, dispatcher.py:136–150), and `tests/test_isolation_loss_drill.py` exists. The memory reminder that drove this can be marked resolved.
- **knowledge.py post-JSON-swap** is a case study: every one of the seven adversarial holes is visible as a named guard with its exploitation story in the docstring (path-escape → H2 forgery, created-newline → frontmatter forgery, NFC/casefold identity → clobbered proof). This file is what "the well dried permanently" looks like.
- **manifest/module_loader/registry_gen** are genuinely fail-closed with the rare property that their *matching* is anchored (module_loader.py:42–49's per-line node-id anchoring against suffix-substring spoofing).
- **The eval machinery realises A2 for model routing**: benchmark receipts, `assignment_has_receipt` deliberately bypassing the env override so the registry's own claim is what gets audited (registry/agents.py:62–73), and an architecture test that makes a model change without a receipt a red build. The consecutive-PASS judge-variance rule in eval_gate is a design v2 never had.
- **edge/server.py** defaults to loopback, warns on non-loopback binds, compares tokens constant-time, and rebuilds state from the log per request rather than trusting daemon memory.
- The runner's **uncontained fallback is loud, marked, and metadata-recorded** (runner.py:68–78) — the fallback itself is correct design; F-3 is about the contained path, not this one.

---

## IV. The completion contract for slices 23–26

The claim "genuine software factory" is demonstrated, not asserted, when ALL of the following are true on this operator's actual machine. This is the checklist I ask my successor — and the overseer — to hold the final slices to:

1. **The P0 drill passes**: one sample project driven plan→build→test→judge→certify entirely by v3's own daemon, unattended; a kill -9 mid-task resumes from the log; the kill-switch and a budget cap demonstrably halt spend.
2. **`evaluate_completion` has a caller** and the certification it produces is written to `certification_log` (giving scorecard's reader something real to read).
3. **The container drill runs against the real orb** on this Mac, or containers are explicitly gated off and the constitution says so (F-3/F-4).
4. **A settle-time fence** exists (F-6), or containment makes it redundant — proven, not assumed.
5. **The judge provider decision is recorded** (F-5) — cross-provider restored or F5 retired in writing.
6. **The notification stack lands with the 17 Jul lessons as criteria**: every outbound message journaled (ts, component, channel, verbatim text), provider-correct remedies, no LLM calls inside the notify path's error handling.
7. **The slice-fidelity audit** (F-1) has run over all 26 slices and its deficiency ledger is empty or scheduled.
8. **A first external product goal is loaded** — the factory's claim is only testable on a product that is not itself.

---

## V. Closing

v3's parts are better than anything v2 ever had; v3's factory does not yet exist. That is not a criticism — it is a position report, and the roadmap already admits it in prose. The risk is only that the programme's own progress metric cannot see it. Hold the last four slices to Part IV and the metric becomes honest at exactly the moment it matters.

To whoever reads this after the 19th: the spine is trustworthy; read `repository.py` and `knowledge.py` first to calibrate on how this codebase argues. The wells that plagued v2 are dry here — parser seams, isolation masking, echo traps are all closed with named guards. What remains is wiring, and wiring under deadline is where this operator's discipline — criteria as drills, findings as slice amendments, verify-on-disk — earns its keep. Trust the discipline, not the green.

— Fable, 18 July 2026
