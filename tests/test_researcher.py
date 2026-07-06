"""Behavioural: the researcher agent parses an evidence bundle and emits KB entries (mocked LLM)."""
from __future__ import annotations

import json
import types

from agents.researcher import run
from validation.research_contract import check


def _fake_call(bundle: dict):
    def call(provider, model, prompt, system=None, **kw):
        return types.SimpleNamespace(text="Here is the research:\n```json\n"
                                     + json.dumps(bundle) + "\n```", cost_usd=0.0, model=model)
    return call


_BUNDLE = {
    "question": "which telegram lib",
    "findings": [
        {"claim": "aiogram is the modern async choice", "confidence": 0.9, "corroborations": 2,
         "sources": [
             {"url": "https://archive.org/x", "tier": 2, "excerpt": "aiogram async"},
             {"url": "https://core.ac.uk/y", "tier": 2, "excerpt": "confirms"},
             {"url": "https://openalex.org/z", "tier": 2, "excerpt": "also confirms"},
             {"url": "https://obscure.example/primary", "tier": 3, "excerpt": "primary usage data"},
         ]},
    ],
    "synthesis": "Use aiogram.",
    "gaps": [],
}


def test_researcher_parses_bundle_and_emits_kb_entries():
    res = run({"task": {"task_id": "r1", "title": "Which telegram lib?", "task_type": "research",
                        "project": "crm"}}, call=_fake_call(_BUNDLE))
    assert res.ok
    assert res.metadata["evidence"]["synthesis"] == "Use aiogram."
    kb = res.metadata["knowledge"]
    assert kb and kb[0]["kind"] == "research" and kb[0]["project"] == "crm" and kb[0]["task_id"] == "r1"
    # the emitted bundle is the same object the gate will judge
    assert check(res.metadata["evidence"]).passed


def test_researcher_fails_when_no_bundle():
    def call(provider, model, prompt, system=None, **kw):
        return types.SimpleNamespace(text="I could not find anything useful.", cost_usd=0.0, model=model)
    res = run({"task": {"task_id": "r2", "title": "x", "task_type": "research"}}, call=call)
    assert not res.ok and res.cause


def test_researcher_survives_provider_error():
    def call(*a, **k):
        raise RuntimeError("boom")
    res = run({"task": {"task_id": "r3", "title": "x", "task_type": "research"}}, call=call)
    assert not res.ok and "boom" in (res.cause or "")
