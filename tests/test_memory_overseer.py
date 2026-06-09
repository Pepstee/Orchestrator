"""Behavioural: the persistent overseer's durable memory — session lifecycle + CORE+EXTRA handoff."""
from __future__ import annotations

from pathlib import Path

from memory.overseer import (
    DEFAULT_RESET_INTERVAL_S,
    DEFAULT_SUCCESSION_LEAD_S,
    HANDOFF_PROMPT_CORE,
    compose_handoff_prompt,
    due_for_reset,
    due_for_succession,
    load_handoff_extra,
    load_session,
    save_handoff_extra,
    start_session,
)


def test_session_round_trip(tmp_path: Path):
    p = tmp_path / "sess.json"
    assert load_session(p) is None                       # nothing yet
    st = start_session(p, now=1000.0)
    again = load_session(p)
    assert again is not None and again.session_id == st.session_id and again.started_at == 1000.0


def test_session_id_is_a_canonical_uuid(tmp_path: Path):
    # Claude's --session-id / --resume reject bare hex; the id must round-trip as a dashed UUID.
    import uuid
    st = start_session(tmp_path / "s.json")
    assert str(uuid.UUID(st.session_id)) == st.session_id
    assert "-" in st.session_id


def test_load_session_rejects_malformed_id(tmp_path: Path):
    """A bare 32-char hex id (uuid4().hex, no dashes) parses in Python but the Claude CLI rejects it,
    failing every resume identically. load_session must return None for it so the daemon mints a fresh
    valid session instead of looping the broken id forever (the lost-night bug)."""
    from infra.atomic_io import write_json_atomic
    p = tmp_path / "sess.json"
    write_json_atomic(p, {"session_id": "f58c10be730e40e880c667de470d98ba", "started_at": 1.0})
    assert load_session(p) is None
    # a canonical dashed UUID loads fine
    write_json_atomic(p, {"session_id": "a1b35488-abfa-4688-a969-0928898189cd", "started_at": 1.0})
    assert load_session(p) is not None


def test_each_start_is_a_new_session_id(tmp_path: Path):
    p = tmp_path / "sess.json"
    a = start_session(p, now=0.0)
    b = start_session(p, now=0.0)
    assert a.session_id != b.session_id                  # a reset is a genuinely fresh session


def test_succession_fires_at_lead_before_reset(tmp_path: Path):
    st = start_session(tmp_path / "s.json", now=0.0)
    just_before = DEFAULT_RESET_INTERVAL_S - DEFAULT_SUCCESSION_LEAD_S
    assert not due_for_succession(st, now=just_before - 1)
    assert due_for_succession(st, now=just_before)       # exactly `lead` before the wipe
    assert not due_for_reset(st, now=just_before)        # ...but not yet time to wipe


def test_reset_fires_at_full_interval(tmp_path: Path):
    st = start_session(tmp_path / "s.json", now=0.0)
    assert not due_for_reset(st, now=DEFAULT_RESET_INTERVAL_S - 1)
    assert due_for_reset(st, now=DEFAULT_RESET_INTERVAL_S)


def test_compose_is_core_only_without_extra():
    assert compose_handoff_prompt("") == HANDOFF_PROMPT_CORE
    assert compose_handoff_prompt("   ") == HANDOFF_PROMPT_CORE


def test_compose_keeps_core_first_then_extra():
    out = compose_handoff_prompt("Always note the git SHA.")
    assert out.startswith(HANDOFF_PROMPT_CORE)           # the immutable floor leads, always
    assert "Always note the git SHA." in out


def test_extra_round_trip_and_length_cap(tmp_path: Path):
    p = tmp_path / "extra.md"
    assert load_handoff_extra(p) == ""                   # absent -> empty, never crashes
    save_handoff_extra(p, "x" * 50000, max_len=100)
    assert len(load_handoff_extra(p)) == 100             # runaway revision is capped
