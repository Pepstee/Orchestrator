"""Behavioural: the overseer command agent — acts in the project, optionally spawns re-validation."""
from __future__ import annotations

from pathlib import Path

from agents.overseer import parse_directive, run
from infra.llm import LLMResult


def _stub(text: str, cost: float = 0.02):
    def call(_provider, _model, _prompt, *, system=None, cwd=None, **_kw):
        return LLMResult(text=text, cost_usd=cost, model="opus")
    return call


def _payload(instruction: str, project: str = "demo", context: str = "") -> dict:
    return {"task": {"task_id": "o1", "title": instruction, "task_type": "oversee",
                     "project": project, "payload": {"context": context}}}


def test_overseer_acts_and_spawns_revalidate(tmp_path: Path):
    res = run(_payload("fix the failing import"),
              call=_stub('Fixed it.\n{"action": "fixed the import in app.py", "revalidate": true}'),
              projects_root=str(tmp_path), state_root=str(tmp_path))
    assert res.ok
    assert "fixed the import" in res.summary
    assert len(res.spawned_tasks) == 1 and res.spawned_tasks[0]["task_type"] == "validate"
    assert res.spawned_tasks[0]["project"] == "demo"


def test_overseer_no_revalidate_when_not_directed(tmp_path: Path):
    res = run(_payload("just summarise the code"),
              call=_stub('Looked it over.\n{"action": "inspected", "revalidate": false}'),
              projects_root=str(tmp_path), state_root=str(tmp_path))
    assert res.ok and res.spawned_tasks == []


def test_overseer_llm_failure_is_safe(tmp_path: Path):
    def boom(*_a, **_k):
        raise RuntimeError("no claude on PATH")
    res = run(_payload("do a thing"), call=boom, projects_root=str(tmp_path), state_root=str(tmp_path))
    assert not res.ok and "overseer call failed" in res.summary and "RuntimeError" in (res.cause or "")


def test_parse_directive_tolerates_fences_and_prose(tmp_path):
    assert parse_directive('done\n```json\n{"action": "a", "revalidate": true}\n```')["revalidate"] is True
    assert parse_directive("no json at all") == {}


# --- persistent-session modes (observe / succession) ---

def _capturing_stub(text: str):
    seen = {}

    def call(_provider, _model, prompt, *, system=None, cwd=None, session_id=None, resume=False, **_kw):
        seen.update(prompt=prompt, system=system, cwd=cwd, session_id=session_id, resume=resume)
        return LLMResult(text=text, cost_usd=0.05, model="opus", session_id=session_id or "")
    return call, seen


def _meta_payload(mode: str, *, context: str = "", session_id: str = "S1") -> dict:
    return {"task": {"task_id": "o1", "title": "meta", "task_type": "oversee", "project": "default",
                     "payload": {"mode": mode, "context": context, "session_id": session_id, "resume": True}}}


def test_observe_runs_in_resumed_session_at_root(tmp_path):
    call, seen = _capturing_stub("Projects A and B progressing; C stalled.")
    res = run(_meta_payload("observe", context="A: done; C: failed"), call=call, state_root=str(tmp_path))
    assert res.ok and "overseer observed" in res.summary
    assert seen["session_id"] == "S1" and seen["resume"] is True   # resumed the persistent session
    assert seen["cwd"] is None                                     # stable cwd (repo root), not a project dir


def test_succession_writes_handoff_and_improves_extra(tmp_path: Path):
    out = '{"handoff": "STATE: deal-sniper passing. WIP: none. DO NOT REDO: parser.", "improved_extra": "Always cite task ids."}'
    call, _ = _capturing_stub(out)
    res = run(_meta_payload("succession", context="deal-sniper: passing"), call=call, state_root=str(tmp_path))
    assert res.ok and "succession handoff" in res.summary
    assert "DO NOT REDO" in (tmp_path / "handoff_latest.md").read_text(encoding="utf-8")
    assert (tmp_path / "handoff_extra.md").read_text(encoding="utf-8") == "Always cite task ids."


def test_succession_keeps_floor_when_no_extra_proposed(tmp_path: Path):
    (tmp_path / "handoff_extra.md").write_text("prior extra", encoding="utf-8")
    out = '{"handoff": "a complete note", "improved_extra": ""}'
    call, _ = _capturing_stub(out)
    res = run(_meta_payload("succession"), call=call, state_root=str(tmp_path))
    assert res.ok
    assert (tmp_path / "handoff_extra.md").read_text(encoding="utf-8") == "prior extra"   # unchanged


def test_succession_fails_loudly_without_handoff(tmp_path: Path):
    call, _ = _capturing_stub('{"improved_extra": "x"}')   # no handoff key
    res = run(_meta_payload("succession"), call=call, state_root=str(tmp_path))
    assert not res.ok and "no handoff" in res.summary


# --- cross-project authority: the overseer directs new work via enqueue directives ---

def test_observe_enqueues_directed_work(tmp_path):
    out = ('C is stalled; A and B are healthy. We should start a backup tool.\n'
           '{"enqueue": [{"project": "backup-tool", "goal": "Build a stdlib backup CLI"}]}')
    call, _ = _capturing_stub(out)
    res = run(_meta_payload("observe"), call=call, state_root=str(tmp_path))
    assert res.ok and len(res.spawned_tasks) == 1
    t = res.spawned_tasks[0]
    assert t["task_type"] == "plan" and t["project"] == "backup-tool" and "backup" in t["title"]


def test_observe_guardrail_blocks_reserved_and_empty_targets(tmp_path):
    out = '{"enqueue": [{"project": "__overseer__", "goal": "tamper"}, {"project": "ok", "goal": ""}, {"project": "real", "goal": "do it"}]}'
    call, _ = _capturing_stub(out)
    res = run(_meta_payload("observe"), call=call, state_root=str(tmp_path))
    projects = [t["project"] for t in res.spawned_tasks]
    assert projects == ["real"]               # reserved (__) and goal-less directives are dropped


def test_observe_enqueue_is_bounded(tmp_path):
    items = ",".join(f'{{"project": "p{i}", "goal": "g{i}"}}' for i in range(20))
    call, _ = _capturing_stub('{"enqueue": [' + items + ']}')
    res = run(_meta_payload("observe"), call=call, state_root=str(tmp_path))
    assert len(res.spawned_tasks) == 5        # MAX_OVERSEER_ENQUEUES caps runaway direction


def test_observe_without_directives_spawns_nothing(tmp_path):
    call, _ = _capturing_stub("Everything looks healthy; nothing to start.")
    res = run(_meta_payload("observe"), call=call, state_root=str(tmp_path))
    assert res.ok and res.spawned_tasks == []


# --- the immutable charter: the overseer knows it is responsible for the orchestrator ---

def test_charter_is_carried_into_observe_and_succession(tmp_path: Path):
    from memory.overseer import OVERSEER_CHARTER

    call_o, seen_o = _capturing_stub("ok")
    run(_meta_payload("observe"), call=call_o, state_root=str(tmp_path))
    assert OVERSEER_CHARTER in seen_o["system"]
    assert "accountable for the orchestrator" in seen_o["system"].lower()

    call_s, seen_s = _capturing_stub('{"handoff": "note", "improved_extra": ""}')
    run(_meta_payload("succession"), call=call_s, state_root=str(tmp_path))
    assert OVERSEER_CHARTER in seen_s["system"]


def test_charter_is_carried_into_intervene(tmp_path: Path):
    from memory.overseer import OVERSEER_CHARTER
    seen = {}

    def call(_p, _m, _prompt, *, system=None, cwd=None, **_kw):
        seen["system"] = system
        return LLMResult(text='{"action": "x", "revalidate": false}', cost_usd=0.0, model="opus")

    run(_payload("fix it"), call=call, projects_root=str(tmp_path), state_root=str(tmp_path))
    assert OVERSEER_CHARTER in seen["system"] and "NEVER modify the orchestrator" in seen["system"]


def test_observe_abandon_directive_spawns_control_task(tmp_path):
    out = '{"abandon": [{"project": "doomed", "reason": "unbuildable"}, {"project": "__overseer__", "reason": "x"}]}'
    call, _ = _capturing_stub(out)
    res = run(_meta_payload("observe"), call=call, state_root=str(tmp_path))
    controls = [t for t in res.spawned_tasks if t["task_type"] == "control"]
    assert len(controls) == 1                                  # reserved target dropped
    p = controls[0]["payload"]
    assert p["directive"] == "abandon" and p["project"] == "doomed" and p["reason"] == "unbuildable"
    assert controls[0]["project"] == "__overseer__"            # the control task itself is a meta-task


def test_observe_reprioritise_directive_spawns_control_task(tmp_path):
    out = '{"reprioritise": [{"project": "urgent", "priority": 10}]}'
    call, _ = _capturing_stub(out)
    res = run(_meta_payload("observe"), call=call, state_root=str(tmp_path))
    controls = [t for t in res.spawned_tasks if t["task_type"] == "control"]
    assert len(controls) == 1
    p = controls[0]["payload"]
    assert p["directive"] == "reprioritise" and p["project"] == "urgent" and p["priority"] == 10


# --- model-fallback ladder: the overseer survives Fable's limit by stepping to Opus ---

def _ladder_stub(succeed_on):
    """RateLimits every rung until it sees the target (provider, model), then succeeds — drives the
    overseer onto a specific ladder rung."""
    from infra.llm import RateLimited
    seen = []

    def call(provider, model, prompt, *, system=None, cwd=None, session_id=None, resume=False, **kw):
        seen.append((provider, model))
        if (provider, model) == succeed_on:
            return LLMResult(text='{"journal": "still steering"}', cost_usd=0.0,
                             model=model, session_id=session_id or "")
        raise RateLimited(f"{model} usage limit")

    return call, seen


def test_observe_falls_back_to_terra_when_fable_fails(tmp_path):
    call, seen = _ladder_stub(("openai", "gpt-5.6-terra"))
    res = run(_meta_payload("observe"), call=call, state_root=str(tmp_path))
    assert res.ok                                        # Fable down, Terra deputy kept it alive
    assert res.metadata["rung"] == 1
    assert res.metadata["served_by"] == "openai:gpt-5.6-terra"
    assert seen[0] == ("claude", "claude-fable-5")       # tried the Fable exec first


def test_observe_falls_over_to_deputy_on_non_ratelimit_provider_error(tmp_path):
    # An exec WEDGE/error (not a clean rate-limit) must still fall to the deputy — the overseer
    # steps on ANY provider fault, so a flaky exec never darks the pulse.
    seen = []

    def call(provider, model, prompt, *, system=None, cwd=None, session_id=None, resume=False, **kw):
        seen.append((provider, model))
        if provider == "claude":
            raise RuntimeError("claude exited 1 with no recognisable error")
        return LLMResult(text='{"journal": "deputy caught it"}', cost_usd=0.0,
                         model=model, session_id=session_id or "")

    res = run(_meta_payload("observe"), call=call, state_root=str(tmp_path))
    assert res.ok and res.metadata["served_by"] == "openai:gpt-5.6-terra"
    assert seen[0][0] == "claude"                        # tried Fable, fell to Terra on the error


def test_observe_pulse_fails_only_when_every_rung_is_limited(tmp_path):
    from infra.llm import RateLimited

    def call(*a, **k):
        raise RateLimited("weekly all-models limit")

    res = run(_meta_payload("observe"), call=call, state_root=str(tmp_path))
    assert not res.ok and "overseer observe failed" in res.summary


def test_observe_stays_on_fable_when_healthy(tmp_path):
    call, seen = _ladder_stub(("claude", "claude-fable-5"))
    res = run(_meta_payload("observe"), call=call, state_root=str(tmp_path))
    assert res.ok and res.metadata["rung"] == 0
    assert res.metadata["served_by"] == "claude:claude-fable-5"
    assert seen == [("claude", "claude-fable-5")]        # exec answered; never stepped to the deputy
