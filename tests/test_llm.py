"""Unit: the claude output parser, against the real CLI JSON shape."""
from __future__ import annotations

from infra.llm import _parse_claude_output

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
