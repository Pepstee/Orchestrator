"""Unit: the claude output parser, against the real CLI JSON shape."""
from __future__ import annotations

from infra.llm import _parse_claude_output, _parse_codex_output

# The shape `claude -p --output-format json` actually emits (trimmed).
CLAUDE_JSON = (
    '{"type":"result","subtype":"success","is_error":false,'
    '"result":"Hello there","total_cost_usd":0.012,'
    '"modelUsage":{"claude-sonnet-4-6":{"inputTokens":10}}}'
)


def test_parse_extracts_text_cost_and_model():
    r = _parse_claude_output(CLAUDE_JSON)
    assert r.text == "Hello there"
    assert abs(r.cost_usd - 0.012) < 1e-9
    assert r.model == "claude-sonnet-4-6"


def test_parse_missing_cost_defaults_zero():
    r = _parse_claude_output('{"result":"x"}')
    assert r.text == "x"
    assert r.cost_usd == 0.0


# Real `codex exec --json` output shape (captured 2026-06-01).
CODEX_JSONL = "\n".join([
    '{"type":"thread.started","thread_id":"019e84b3"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"hello"}}',
    '{"type":"turn.completed","usage":{"input_tokens":25859,"output_tokens":5}}',
])


def test_parse_codex_output_extracts_message():
    r = _parse_codex_output(CODEX_JSONL)
    assert r.text == "hello"
    assert r.model == "codex"
    assert r.cost_usd == 0.0   # subscription-covered: tokens, not dollars


def test_parse_codex_picks_last_agent_message_skipping_reasoning():
    lines = "\n".join([
        '2026-06-01T19:40:43Z ERROR codex_core: harmless log line on stdout',
        '{"type":"item.completed","item":{"type":"agent_message","text":"first"}}',
        '{"type":"item.completed","item":{"type":"reasoning","text":"thinking"}}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"final"}}',
    ])
    assert _parse_codex_output(lines).text == "final"
