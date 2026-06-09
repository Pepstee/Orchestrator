---
name: graphify-update
description: Keep the agentic-orchestrator knowledge graph current with graphify. Use after modifying code files in this repo, or to (re)generate graphify-out/ for architecture questions.
---

# graphify: keep the knowledge graph current

This repo's knowledge graph lives at `graphify-out/` (god nodes, community structure, and an optional
agent-crawlable wiki). graphify is a **Claude Code skill** — built and refreshed by typing `/graphify`
in Claude Code, not by a bespoke CLI verb.

**Install once (Python 3.10+ — note the doubled-y package name; the command stays `graphify`):**

```bash
pip install graphifyy && graphify install
```

**Build / refresh the graph (in Claude Code, from the repo root):**

```
/graphify .                 # build (or rebuild) the full graph into graphify-out/
/graphify . --update        # incremental: re-extract only changed files (cheap, AST-only)
/graphify . --wiki          # also build the agent-crawlable wiki (graphify-out/wiki/index.md)
```

**Auto-keep-current (recommended for this repo):**

```bash
graphify hook install        # post-commit hook rebuilds the graph after every commit
```

**Before answering an architecture or codebase question:** read `graphify-out/GRAPH_REPORT.md` for the
god nodes and community structure; if `graphify-out/wiki/index.md` exists, navigate that instead of
reading raw files.

Notes:
- Requires Claude Code + Python 3.10+. If the default `python3` is older (e.g. macOS system 3.9),
  install graphifyy under a 3.10+ interpreter (`brew install python@3.12`, or `pipx`).
- `graphify-out/` is a generated artifact — treat it as derived, never hand-edit it.
- If `/graphify` isn't available, graphify isn't installed; say so and skip — never fake the graph.
