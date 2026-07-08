# 17 — Modular Engine Specification (kernel, modules, containers, selfdev, focus)

*Status: PROPOSED — drafted 8 July 2026 from an operator design session; awaiting ratification.
Feeds the v3 build charter (16, pending move-in from the operator scratchpad). House rule applies
throughout: every mechanism below names the machine check that will police it — a mechanism
without a check does not ship (PRIME). British spelling.*

*Provenance: operator-ratified positions from the 8 Jul session are marked **[RATIFIED-8JUL]**;
everything else is proposed. Prior art this spec builds on rather than replaces: DV-1..7
(`13_V3_CAPABILITY_PLAN.md`), DG-2 zero-touch, DG-5 Theseus, DG-8 overseer mind-on-disk,
BG-1/BG-3/BG-5, and the existing seams in v2 (`registry/agents.py`, `assurance.Tier`,
`pa_consult`, `notify`, `Invoke`, the quarantined `selfdev/` package).*

---

## 0. The one-paragraph shape

v3 is a **small frozen kernel** (event store, state machine, repository, dispatcher, budget +
law enforcement, boot self-test — target ≤ ~1,500 LOC) surrounded by **modules** that implement
a closed set of **ports**. Modules declare themselves in **manifests** (laws-as-data, extended);
a module whose manifest is invalid, whose declared tests are not green, or whose producing
project is not **certified** does not load — fail-closed (DV-6). Worker agents run in
**containers** whose profiles are *generated from* their module manifests. The **Overseer runs
on the host with full control** [RATIFIED-8JUL], and rewrites the orchestrator only through the
**selfdev candidate/promotion pipeline** (edit a candidate checkout → gates → blue-green promote
→ auto-revert on failure). Exactly **one project holds focus** at a time, hot-switchable
[RATIFIED-8JUL]. Certification gates **trust** (publication, module activation, slice
progression), never attention [RATIFIED-8JUL].

---

## 1. Proposed laws (ME series — Modular Engine)

*Numbering note: ME-n is a new series to avoid collision with DV-n (v3 capability laws) and
DG-n (ratified decision gates). On ratification these join `charter/laws.py` as data.*

| Id | Law | Enforcing check (to be written) |
|---|---|---|
| ME-1 | **Closed port set.** Every non-kernel capability implements exactly one declared port; the port catalogue (§3) is code, defined once. | `tests/architecture/test_ports_closed.py` — every module's manifest names a port from the catalogue; no module imports the kernel beyond its port API surface |
| ME-2 | **Fail-closed module load.** A module loads only if its manifest parses, its declared tests are collected and green, and its producing project is certified. No bypass flag. | `tests/architecture/test_module_load_fail_closed.py` (BG-1 extended to modules; asserts absence of any bypass, mirroring `test_boot_self_test.py`) |
| ME-3 | **No lateral module imports.** Modules import kernel API only; module→module imports are forbidden. | import-linter contract "ME-3 — modules are islands" (forbidden-modules matrix, generated from the module list) |
| ME-4 | **Manifest is the sandbox.** A worker module's container profile (mounts, network egress, secrets) is generated from its manifest capabilities; an undeclared capability is an absent capability. | `tests/test_container_profiles.py` — profile generator output matches manifest exactly; a manifest with no `network` yields a no-egress profile |
| ME-5 | **Promotion only through the pipeline.** The running orchestrator is never edited in place. Self-development flows: candidate checkout → full gates (incl. BG-1 in the candidate) → blue-green promote → auto-revert on boot/crash failure. | `tests/test_promotion_pipeline.py` (promote refuses an ungated candidate; simulated bad candidate auto-reverts) + the L9R fence retained on the RUNNING tree |
| ME-6 | **The guardian is resurrectable.** Overseer transcript mirrored per pulse; per-pulse diary to the KB; a rehydration protocol exists and is exercised by test. | `tests/test_overseer_resurrection.py` — kill a synthetic session, rehydrate from handoff+diary+status, assert key facts present (DG-8 made checkable) |
| ME-7 | **Focus is singular, hot, and human-held.** Exactly one focused project; the focus file is re-read every cycle; no agent code path writes it (Overseer may recommend, only operator surfaces write). | `tests/architecture/test_focus_single_writer.py` (successor of `test_breadth_cap.py`) + `tests/test_focus_hot_switch.py` |
| ME-8 | **Certification is the trust boundary.** Publication, module activation, and v3 slice progression each require a recorded certification of the producing project. | `tests/test_certification_trust_boundary.py` — uncertified module refuses to load (with ME-2); publish script refuses uncertified project |

**Law text amendment required (operator ratification):** L9 changes from
"self-modification is quarantined" to **"no LIVE self-modification — self-development flows
exclusively through the selfdev candidate/promotion pipeline (ME-5)"**. L9R (the runtime fence
on the running tree) is retained unchanged; its threat model shrinks because containerised
workers cannot see the running tree at all (§5).

---

## 2. The kernel

Contents: `core/` (models, state machine), `infra/event_store`, `infra/atomic_io`,
`dispatch/` (repository, dispatcher, runner shell), budget governor, boot self-test,
module loader. Explicitly **not** kernel: agents, gates, assurance tiers, intake surfaces,
notification channels, PA, KB, research, scheduler, GUI — all modules.

Kernel API exposed to modules: narrow and versioned from day one (`kernel_api_version: 1` in
every manifest; loader refuses a version it does not speak). Modules never touch `EventStore`
directly — they receive port-scoped handles.

Deliberately NOT built (N4/N5): dynamic hot-reload of modules, a plugin marketplace, module
dependency resolution (modules are islands, ME-3), config frameworks. Boot-time discovery of
`modules/` is sufficient.

## 3. Port catalogue (closed set, ME-1)

| Port | Contract (payload → result) | v2 seam it formalises |
|---|---|---|
| AgentPort | task payload (stdin) → one AgentResult (stdout), containerised | `registry/agents.py` + `dispatch/runner.py` |
| GatePort | project_dir → GateResult | `validation/gates.py` members |
| AssuranceTierPort | project_dir → findings | `assurance.Tier` |
| IntakePort | external input → task files in inbox | `control/{enqueue,intake}`, edge `/api/goal` |
| ChannelPort | notification/dialogue in+out | `infra/notify`, `control/operator_chat` |
| RulePort | failure cause → action \| None | `pa/rules.consult` |
| MemoryPort | write/recall entries | `memory/knowledge` (DV-2) |
| SchedulerPort | clock → task specs | empty `scheduling/` seam |

Adding a *port* (not a module) is a kernel change and goes through ME-5 like any other.

## 4. Module manifests

One file per module (`modules/<name>/manifest.json` or `.py`-as-data, matching `charter/laws.py`
style):

```
name, version, port, kernel_api_version,
capabilities: [project-fs, network:<allowlist>, llm:<provider>, secrets:<names>],
tests: [paths],                # ME-2: must be collected + green to load
produced_by: <project>,        # ME-8: must hold a certification
```

Loader behaviour: parse → verify certification (ME-8) → run declared tests (ME-2) → generate
container profile from capabilities (ME-4) → register against the port. Any failure = module
absent + one loud notify. The registry remains the single source of truth (L1/L5) — generated
from manifests, never hand-edited.

## 5. Container runner (worker agents only)

**[RATIFIED-8JUL: containers for workers; the Overseer is never containerised.]**

Profile per agent run, generated from the manifest (ME-4): task's git worktree bind-mounted RW;
scratch tmpfs; **the orchestrator tree not mounted at all** (L9R's threat class removed
structurally — the fence remains as belt-and-braces on the running tree); egress per manifest
allowlist; no host home. Runtime: OrbStack / Apple container tooling preferred over Docker
Desktop (many short-lived containers). The DV-7 operator-vs-fence friction disappears for
workers by construction.

### 5.1 Auth to Claude Max — two phases [RATIFIED-8JUL direction]

The browser/Gmail login is OAuth; it leaves a bearer token on the host (macOS: Keychain item;
Linux: `~/.claude/.credentials.json`). That token is the credential we manage.

- **Phase 1 — headless token.** Mint a long-lived token for non-interactive use
  (`claude setup-token` — VERIFY exact command against current CLI docs when the usage window
  resets); inject into worker containers as a secret; egress allowlist pinned to Anthropic
  endpoints so the token cannot travel anywhere else. Host is the sole refresher; a token
  expiring mid-run fails TRANSIENT and retries post-refresh.
  *Check:* `tests/test_runner_auth.py` — profile contains the secret iff manifest declares it;
  egress list is exactly the allowlist.
- **Phase 2 — host-side credential broker (a ChannelPort-adjacent kernel module).** Containers
  hold a dummy token and point their CLI at the broker via base-URL override; the broker reads
  the real token host-side, swaps the auth header, forwards. Containers hold nothing real.
  The broker is ALSO the metering point (per-agent/per-task token + wall-clock accounting),
  the AIMD backpressure point (v1 `admission_control` port target), and where 401-fail-fast
  lives (kills the 401-as-transient loop).
  *Check:* `tests/test_broker.py` — dummy-token request leaves with real auth; 401 classified
  PERMANENT-auth (notify), never TRANSIENT; per-call usage row appended.

## 6. Selfdev: candidate/promotion pipeline (ME-5; DG-5 Theseus realised)

**[RATIFIED-8JUL: the Overseer has FULL CONTROL — host access, bash, stop/start/restart,
focus, and the authority to rewrite the orchestrator. Control is expressed as the operator's
own workflow, which is the only workflow physics permits: the daemon loads once.]**

Mechanism: `selfdev/` grows from quarantined placeholder into the pipeline —
1. Candidate checkout beside the live one (worktree or clone; never the running tree).
2. Overseer (or operator) edits the candidate freely — laws included.
3. Gates run IN the candidate: ruff, import-linter, full suite, and the candidate's own BG-1
   boot self-test. A version that cannot prove its own laws hold refuses to boot — this is the
   property that makes a month of unattended self-rewriting survivable.
4. `promote` directive → supervisor blue-green swap: point at the candidate commit, restart,
   event log replays (restart = resume; the log is shared state, versioned-forward only).
5. **Auto-revert:** boot self-test failure, or ≥ N crashes within M minutes post-promotion
   (default N=3, M=30), reverts to the last-good commit and notifies with the failure detail.
6. **Constitution veto window:** a candidate touching `charter/laws.py` or `validation/` gates
   notifies the operator and waits a default 24 h before promoting — default-ALLOW (absence
   never stalls the month-long run), Telegram veto cancels. Tunable; 0 disables.

*Checks:* `tests/test_promotion_pipeline.py` (§1), plus supervisor-level
`tests/test_autorevert.py` (crash-storm candidate ends on last-good commit).

## 7. Overseer: full control + mind-on-disk (ME-6; DG-8 realised)

Posture [RATIFIED-8JUL]: the Overseer is the operator-as-Fable. Host process, unsandboxed,
bash, all directives (stop/start/restart/focus/promote/abandon/reprioritise). Stated plainly:
an unsandboxed process with bash owns the host — the real safety system for the Overseer is
therefore *procedural* (ME-5 pipeline, veto window, budgets, BG-5) plus ME-6 resilience, not
containment. Containers protect against the five workers; the gates protect against the brain.

Memory (all three, agreed 8 Jul):
- transcript mirror after every pulse → `state/overseer/transcripts/` (atomic);
- per-pulse **diary delta** into the KB (DV-5's digest role; KB = long-term memory, session =
  working memory — a session death costs ≤ one pulse of train-of-thought);
- **resurrection drill** (ME-6 check) exercising the rehydration protocol, not assuming it.

## 8. Focus (ME-7; supersedes BG-2's certification-lift)

`state/focus` (successor of `state/flagship`): exactly one project; **re-read every cycle**
(retires the read-once-at-boot restart gotcha). Switching = repointing the claim allowance:
in-flight tasks of the old focus drain (already paid for); its queued tasks stay QUEUED but
unclaimable; nothing is cancelled or abandoned (abandonment semantics — era close, parking —
are reserved for genuine giving-up). Switch back and the graph resumes from the log, budgets
intact. Assurance and FOREVER-IMPROVE rounds follow focus (all discretionary window-spend
follows the operator's attention). Surfaces: `python -m control.focus <project>`, edge one-tap,
Telegram "focus X" (sender-locked = operator-only). Each switch appends `focus_changed` to the
log (scorecard: true window-cost per project). Reserved `__` projects dispatch regardless.

## 9. Certification (ME-8): trust boundary, not attention gate

Certification (gates + assurance clean, self-certified under DG-2) is required for:
1. **Publication** — `publish_projects.sh` refuses an uncertified project.
2. **Module activation** — ME-2/ME-8: an orchestrator-built module loads only from a certified
   project.
3. **Slice progression** — v3 build charter: slice n+1 loads only after slice n certifies.
It gates nothing else — not focus, not breadth. Runs-per-certification stays the efficiency
north star: it now measures how efficiently *trustworthy* artefacts are produced.

## 10. Sequencing and the v2 boundary

This spec is **v3-charter input**. Do not retrofit v2 (fork-clean is settled; the window is the
scarce resource). The only v2 backports permitted: 401 fail-fast in `infra/llm.py`,
commit-before-daemon discipline (until ME-5 makes it moot), a `test_docs_claims.py` docs-drift
check, and reconciling zero-touch language across CLAUDE.md / Quality Charter §7 / HANDOFF / 09.

Open items for the charter merge: exact slice placement of kernel/ports vs container runner vs
broker (suggested order: kernel+ME-2 loader first, Phase-1 auth runner second, focus third,
selfdev pipeline fourth, broker fifth, ME-6 drill sixth); ratification of the ME series and the
L9 text amendment; verification of `claude setup-token`; container runtime choice.

*End of spec.*
