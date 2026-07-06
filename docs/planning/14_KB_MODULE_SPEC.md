# KB Module Spec — the load-bearing knowledge base (DV-2, DV-5, DV-6)

*Module spec for the first v3 capability. Implements DV-2 (knowledge base the system cannot skip),
DV-5 (KB doubles as the Overseer's on-disk memory), DV-6 (isolated module, fail-closed seam-gate).
Spec only — no code yet.*

---

## 1. Purpose & placement

A single canonical, agent-facing **append-only markdown decision/learning log** that the planner reads
before planning and every task writes to on completion — enforced, not optional. It is also the
Overseer's context digest (DV-5), which retires the raw-event-log rebuild and bounds context growth.

**Layer:** `memory/knowledge.py` (a new module in the existing `memory/` layer). `agents`, `dispatch`,
and `control` sit above `memory` and may import it; it imports only `infra`/`core` (import-linter L2
holds). It reuses the repo's proven memory pattern — one file per entry with YAML frontmatter + a loaded
index — rather than inventing a store (N1 reuse, N6 consistency).

## 2. The store — schema

A `knowledge/` directory (gitignored state, like `state/`):

- **One markdown file per entry**, `knowledge/entries/{id}.md`, written **once, atomically** via
  `infra.atomic_io` (L7). Never edited in place (append-only; corrections are new entries that
  `[[link]]` the old).
- **`knowledge/INDEX.md`** — one line per entry (`- [title](entries/{id}.md) — hook · project · kind`),
  regenerated atomically on each write. This is the cheap, always-loaded index (mirrors `MEMORY.md`).

**Entry format:**

```markdown
---
id: <kebab-slug-or-hash>
project: <project | "global">
task_id: <origin task, or "">
task_type: plan | implement | test | validate | oversee
kind: decision | learning | finding | failure | research
tags: [<keyword>, ...]
links: [[other-entry-id]], ...
created: <iso8601>
---

<the fact/decision. For decision/failure, follow with **Why:** and **How to apply:** lines.
Link related entries with [[id]]. Keep it economical — capture what would be lost otherwise.>
```

Minimal validity: an entry MUST carry `kind`, a non-empty body, and (for `decision`/`failure`) a
`Why:` line — enforced at write (a noise-only entry is rejected, so the write-gate can't be satisfied
with junk).

## 3. The module API

| Function | Purpose |
|----------|---------|
| `recall(query, *, project=None, k=12) -> list[Entry]` | Retrieve the entries relevant to a goal/task for injection into an agent's context. **Read side of the gate.** |
| `record(entry: KBEntry) -> str` | Append one entry atomically + regenerate the index; returns its id. Rejects invalid entries (§2). **Write side of the gate.** |
| `digest(*, project=None, max_tokens=4000) -> str` | A **bounded** curated summary (recent + high-importance entries) — the Overseer rebuilds context from this (DV-5). |
| `has_entry_for(task_id) -> bool` | Did this task append an entry? Backs the completion gate. |

**Retrieval, kept simple first (N5):** tag + keyword match, filtered by `project` (plus `global`),
ranked by recency and `kind` weight. No embeddings initially; revisit only if recall quality is
measurably poor (don't pre-build a vector store).

## 4. How entries flow (respecting the main-thread-only state rule)

Agents are subprocesses — they cannot mutate shared state. So, exactly like `spawned_tasks`:

- **`AgentResult` gains a `knowledge: KBEntry | None` field.** The agent *produces* its entry; it does
  not write the store.
- The **main-thread `settle()`** calls `knowledge.record(result.knowledge)` — the only writer, on the
  dispatch thread, race-free (consistent with the pool's invariant).
- `recall()` output is injected into the agent's **payload** before launch (read side), so the
  subprocess receives the context without importing the store itself.

## 5. The three seam-gates (DV-6 — minimal, mandatory, fail-closed)

| # | Hook | File | Fail-closed behaviour |
|---|------|------|-----------------------|
| H1 | **Read-before-plan.** Inject `knowledge.recall(goal, project)` into the payload of every `plan` task (and, later, workers) before launch | `dispatch/runner.py` | if the KB module is absent, the boot self-test (H3) blocks dispatch |
| H2 | **Write-on-complete.** In `settle()`, after `ok`, `record()` the entry and require it; **no entry ⇒ the task does NOT complete** (fails with cause `"no knowledge entry (DV-2)"`) | `dispatch/dispatcher.py` `settle()` | a task that skipped the KB cannot be marked done |
| H3 | **Boot self-test.** Assert the module loads, the store dir exists, H1 is wired into the runner, and H2 is active | `control/self_test.py` | daemon **refuses to dispatch build tasks** if any is missing |

These three are the *entire* core footprint. Everything else lives inside `memory/knowledge.py`.

## 6. DV-5 — the KB is the Overseer's memory

`digest()` replaces the Overseer's context reconstruction: each pulse rebuilds from the bounded digest,
not the raw event log. This (a) makes `--resume` a non-fatal optimisation (BG-6), and (b) bounds context
growth over the weeks-long soak — quietly solving the entropy problem that was deferred earlier. The
existing BG-6 test (delete session store → pulse must succeed) now asserts the pulse reads `digest()`.

## 7. graphify as derived (per the locked decision)

The markdown log is the **primary, agent-facing** store. graphify stays a **derived, read-only code-map**
built from the codebase (AST, no API cost); entries may reference graph nodes. graphify is never a write
target for agents — it's a lens over the code, not the knowledge of record.

## 8. Machine-checks (ship with the module — DV-2/DV-6)

- `test_completion_requires_kb_entry` — a task returning no `knowledge` entry fails, is not `DONE` (H2).
- `test_plan_payload_includes_recall` — a `plan` task's payload carries injected KB context (H1).
- `test_record_is_append_only_and_atomic` — writes go through `infra.atomic_io`; no in-place edits (L7).
- `test_invalid_entry_rejected` — an entry missing `kind`/body/`Why:` is refused (no junk-satisfies-gate).
- `test_digest_is_bounded` — `digest()` ≤ `max_tokens`.
- `test_overseer_pulse_reads_digest` — DV-5/BG-6.
- boot self-test assertion — H3, fail-closed.
- layer-contract (import-linter) — `memory.knowledge` imports nothing above `memory`.

## 9. Non-goals & open questions

- **Gate activation vs build:** the module can be built now, but H2 only bites once the 09 completion
  path is gated. Build early; activate the write-gate with the spine.
- **Log compaction** (pruning stale entries) is a future concern — the *read* side is already bounded by
  `digest()`; note, don't build.
- **Entry quality beyond the minimal schema** — the gate forces an entry, not a *good* entry. A later
  quality check (or Judge pass over entries) is deferred; the minimal-validity rule (§2) is the floor.
- **Retrieval quality** — if keyword/tag recall proves weak, revisit embeddings (measure first).
