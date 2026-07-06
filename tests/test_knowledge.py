"""Behavioural: the load-bearing knowledge base — append-only store, recall, digest, validity gate."""
from __future__ import annotations

from pathlib import Path

import pytest

from memory.knowledge import InvalidEntry, KBEntry, KnowledgeBase


def _kb(tmp_path: Path) -> KnowledgeBase:
    return KnowledgeBase(tmp_path / "knowledge")


def test_record_and_recall_round_trip(tmp_path: Path):
    kb = _kb(tmp_path)
    kb.record(KBEntry(kind="learning", body="Use aiogram for the booking bot",
                      project="crm", tags=["telegram", "aiogram"]))
    hits = kb.recall("which telegram library", project="crm")
    assert hits and "aiogram" in hits[0].body


def test_record_is_append_only(tmp_path: Path):
    kb = _kb(tmp_path)
    kb.record(KBEntry(kind="finding", body="First"))
    kb.record(KBEntry(kind="finding", body="Second"))
    files = list((tmp_path / "knowledge" / "entries").glob("*.md"))
    assert len(files) == 2                         # two records -> two files, nothing overwritten
    assert (tmp_path / "knowledge" / "INDEX.md").exists()


def test_invalid_entries_rejected(tmp_path: Path):
    kb = _kb(tmp_path)
    with pytest.raises(InvalidEntry):
        kb.record(KBEntry(kind="finding", body="   "))          # empty body
    with pytest.raises(InvalidEntry):
        kb.record(KBEntry(kind="nonsense", body="x"))           # bad kind
    with pytest.raises(InvalidEntry):
        kb.record(KBEntry(kind="decision", body="chose X"))     # decision without a **Why:**
    # a decision WITH a Why is accepted
    kb.record(KBEntry(kind="decision", body="Chose X\n\n**Why:** it fits"))


def test_recall_filters_by_project(tmp_path: Path):
    kb = _kb(tmp_path)
    kb.record(KBEntry(kind="finding", body="crm secret", project="crm", tags=["crm"]))
    kb.record(KBEntry(kind="finding", body="edge secret", project="edge", tags=["edge"]))
    kb.record(KBEntry(kind="finding", body="shared truth", project="global", tags=["shared"]))
    bodies = {e.body for e in kb.recall("secret truth", project="crm")}
    assert "crm secret" in bodies and "shared truth" in bodies   # project + global
    assert "edge secret" not in bodies                            # other project excluded


def test_has_entry_for(tmp_path: Path):
    kb = _kb(tmp_path)
    assert kb.has_entry_for("t1") is False
    kb.record(KBEntry(kind="learning", body="did t1", task_id="t1"))
    assert kb.has_entry_for("t1") is True
    assert kb.has_entry_for("") is False


def test_digest_is_bounded(tmp_path: Path):
    kb = _kb(tmp_path)
    for i in range(200):
        kb.record(KBEntry(kind="learning", body=f"entry number {i} " + "detail " * 40))
    d = kb.digest(max_tokens=500)
    assert len(d) <= 500 * 4                       # stays within the char budget
    assert d.startswith("# Knowledge digest")


def test_frontmatter_persists_and_reloads(tmp_path: Path):
    kb = _kb(tmp_path)
    tid = kb.record(KBEntry(kind="research", body="finding\n\nsource: archive",
                            project="edge", task_id="r1", tags=["a", "b"], links=["other-id"]))
    # a fresh KB over the same root reads the persisted entry with its metadata intact
    reloaded = KnowledgeBase(tmp_path / "knowledge").recall("finding archive", project="edge")
    assert reloaded and reloaded[0].id == tid
    assert reloaded[0].tags == ["a", "b"] and reloaded[0].task_id == "r1"
