"""memory.knowledge — the load-bearing knowledge base (DV-2, DV-5, DV-6).

An append-only, human-readable (Obsidian-style) decision/learning log that the planner reads before
planning and every task writes to on completion — the store the system CANNOT skip. It is also the
Overseer's bounded context digest (DV-5), which retires the raw-event-log rebuild and bounds context
growth over long soaks (A3).

Store layout (gitignored state, like `state/`):
    <root>/entries/<id>.md   one entry per file, written ONCE, atomically (L7). Never edited in place.
    <root>/INDEX.md          one line per entry, regenerated on each write (the always-loaded index).

Design notes:
- Reuses the repo's proven memory pattern (frontmatter + index), not a new store (N1, N6).
- Writes go through infra.atomic_io only (L7); reads use Path.read_text (a read, not a mutation).
- Layer: `memory` — imports only infra/core (import-linter L2 holds).
- Retrieval is deliberately simple first (tag/keyword + project + recency); no embeddings until measured
  to be needed (N5).
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from infra.atomic_io import write_text_atomic

VALID_KINDS = {"decision", "learning", "finding", "failure", "research"}
_NEEDS_WHY = {"decision", "failure"}          # these must justify themselves
_KIND_WEIGHT = {"decision": 3, "failure": 3, "research": 2, "learning": 1, "finding": 1}


class InvalidEntry(ValueError):
    """An entry that fails minimal validity — so the write-gate cannot be satisfied with junk."""


@dataclass
class KBEntry:
    kind: str
    body: str
    project: str = "global"
    task_id: str = ""
    task_type: str = ""
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    id: str = ""
    created: float = 0.0

    def validate(self) -> None:
        if self.kind not in VALID_KINDS:
            raise InvalidEntry(f"kind {self.kind!r} not in {sorted(VALID_KINDS)}")
        if not self.body or not self.body.strip():
            raise InvalidEntry("entry body is empty")
        if self.kind in _NEEDS_WHY and "**Why:**" not in self.body:
            raise InvalidEntry(f"a {self.kind} entry must include a '**Why:**' line")

    def title(self) -> str:
        first = next((ln.strip() for ln in self.body.splitlines() if ln.strip()), self.kind)
        return first[:80]


def default_root() -> Path:
    """The canonical KB location in the live repo (repo_root/knowledge)."""
    return Path(__file__).resolve().parents[1] / "knowledge"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48]


def _make_id(entry: KBEntry) -> str:
    base = _slug(entry.title())
    h = hashlib.sha1(f"{entry.body}{entry.created}{entry.task_id}".encode()).hexdigest()[:6]
    return f"{base}-{h}" if base else h


def _dump(entry: KBEntry) -> str:
    return "\n".join([
        "---",
        f"id: {entry.id}",
        f"project: {entry.project}",
        f"task_id: {entry.task_id}",
        f"task_type: {entry.task_type}",
        f"kind: {entry.kind}",
        f"tags: [{', '.join(entry.tags)}]",
        f"links: [{', '.join(entry.links)}]",
        f"created: {entry.created}",
        "---",
        "",
        entry.body.strip(),
        "",
    ])


def _parse_list(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [item.strip() for item in raw.split(",") if item.strip()]


def _load(path: Path) -> KBEntry | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not m:
        return None
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
    try:
        created = float(meta.get("created", "0") or 0)
    except ValueError:
        created = 0.0
    return KBEntry(
        kind=meta.get("kind", "finding"),
        body=m.group(2).strip(),
        project=meta.get("project", "global"),
        task_id=meta.get("task_id", ""),
        task_type=meta.get("task_type", ""),
        tags=_parse_list(meta.get("tags", "")),
        links=_parse_list(meta.get("links", "")),
        id=meta.get("id", ""),
        created=created,
    )


class KnowledgeBase:
    """The append-only markdown KB rooted at `root` (default: repo_root/knowledge)."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()
        self.entries_dir = self.root / "entries"
        self.index_path = self.root / "INDEX.md"

    # ---- write side of the gate -------------------------------------------------
    def record(self, entry: KBEntry) -> str:
        """Append one validated entry atomically and rebuild the index. Returns its id.
        Append-only: a new file per entry; corrections are new entries that [[link]] the old."""
        entry.validate()
        if not entry.created:
            entry.created = time.time()
        if not entry.id:
            entry.id = _make_id(entry)
        write_text_atomic(self.entries_dir / f"{entry.id}.md", _dump(entry))
        self._rebuild_index()
        return entry.id

    def _rebuild_index(self) -> None:
        entries = sorted(self._all(), key=lambda e: e.created, reverse=True)
        lines = ["# Knowledge index", ""]
        for e in entries:
            lines.append(f"- [{e.title()}](entries/{e.id}.md) — {e.kind} · {e.project}")
        write_text_atomic(self.index_path, "\n".join(lines) + "\n")

    # ---- read side of the gate --------------------------------------------------
    def _all(self) -> list[KBEntry]:
        if not self.entries_dir.exists():
            return []
        out = []
        for p in self.entries_dir.glob("*.md"):
            e = _load(p)
            if e is not None:
                out.append(e)
        return out

    def _scope(self, project: str | None) -> list[KBEntry]:
        entries = self._all()
        if project is None:
            return entries
        return [e for e in entries if e.project == project or e.project == "global"]

    def recall(self, query: str, *, project: str | None = None, k: int = 12) -> list[KBEntry]:
        """Retrieve the entries most relevant to a goal/task, for injection into an agent's context.
        Simple, explainable ranking: keyword + tag overlap, then kind weight, then recency."""
        terms = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
        scored: list[tuple[float, float, KBEntry]] = []
        for e in self._scope(project):
            hay = f"{e.body} {' '.join(e.tags)}".lower()
            overlap = sum(1 for t in terms if t in hay)
            tag_hits = sum(1 for t in e.tags if t.lower() in terms)
            score = overlap + 2 * tag_hits + _KIND_WEIGHT.get(e.kind, 1)
            scored.append((score, e.created, e))
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        return [e for score, _, e in scored[:k] if score > 0] or [e for _, _, e in scored[:k]]

    def has_entry_for(self, task_id: str) -> bool:
        """Did this task append an entry? Backs the completion gate (H2)."""
        return bool(task_id) and any(e.task_id == task_id for e in self._all())

    # ---- DV-5: the Overseer's bounded memory ------------------------------------
    def digest(self, *, project: str | None = None, max_tokens: int = 4000) -> str:
        """A BOUNDED curated summary (importance then recency) — the context the Overseer rebuilds from
        each pulse. Bounding it here is what retires the unbounded event-log rebuild (A3/BG-6)."""
        budget = max_tokens * 4  # ~4 chars/token, a deliberate over-estimate kept conservative below
        entries = sorted(
            self._scope(project),
            key=lambda e: (_KIND_WEIGHT.get(e.kind, 1), e.created),
            reverse=True,
        )
        lines = ["# Knowledge digest", ""]
        used = len(lines[0]) + 2
        for e in entries:
            hook = " ".join(e.body.split())[:160]
            line = f"- [{e.kind}] {e.title()} — {hook}"
            if used + len(line) + 1 > budget:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines) + "\n"
