"""agents.overseer — the persistent meta-agent (the operator's "Jarvis") with continuity of memory.

Three modes, selected by ``task.payload["mode"]``:

  * "intervene" (default): the original remote-command behaviour — act WITHIN a named project (fix
    code, adjust the build) in the project's own directory, optionally asking for re-validation. One
    shot, project-scoped. (Used by the stall-guard and by your remote commands.)

  * "observe": reason about the WHOLE system with continuity. Runs in the SAME persistent Claude
    session each cycle (resumed by id) from a STABLE cwd — Claude namespaces sessions by working
    directory, so the meta-session must reason from the repo root, never a per-project dir.

  * "succession": its memory is about to be wiped; write a self-handoff (CORE+EXTRA prompt from
    memory.overseer) for the fresh session, and propose an improved EXTRA — the self-improving
    handoff loop. CORE is immutable; only EXTRA (data, not code) is revised, so law L9 holds.

It never touches the orchestrator's own code (L9); it acts on projects and on its own EXTRA data only.
The LLM call is injected, so all of this is testable without spending tokens.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Callable

from agents.common import safe_main
from core.models import AgentResult, Task
from infra.atomic_io import write_text_atomic
from infra.llm import LLMResult, PROVIDER_FALLBACK_ERRORS, call_llm, call_llm_ladder
from infra.notify import notify
from infra.workspace import task_workdir
from memory.overseer import (
    append_journal,
    compose_handoff_prompt,
    default_mind_dir,
    frame_system,
    load_handoff_extra,
    mind_context,
    save_beliefs,
    save_handoff_extra,
)
from registry.agents import model_ladder

SYSTEM_PROMPT = (
    "You are the Overseer: the operator's trusted agent with full command over THIS PROJECT (never "
    "the orchestrator itself). Carry out the operator's instruction precisely by creating/editing "
    "files in your current working directory. Make the smallest change that satisfies it; invent no "
    "extra scope. When finished, output a final line of JSON: "
    '{"action": "<one sentence on what you did>", "revalidate": true|false} '
    "— set revalidate true when the change should be re-checked by the test and judge gates."
)

OBSERVE_SYSTEM = (
    "You are the persistent Overseer meta-agent, reasoning across the WHOLE orchestrator. Your "
    "CANONICAL memory is your durable mind on disk (beliefs + journal, included in the prompt); the "
    "session you may be resumed into is only a cache of it. You are not editing files now — you are "
    "thinking and DIRECTING. Review the system state against your beliefs: which projects progress, "
    "which stall, what should be started, what changed since your last pulse. End with ONE JSON "
    "object: {\"journal\": \"<2-6 sentences to your future self: what you observed, what you decided, "
    "and WHY>\", \"beliefs_update\": \"<full replacement of your beliefs file when your model of "
    "what-normal-looks-like changed, else empty>\", "
    "\"enqueue\": [{\"project\": \"name\", \"goal\": \"...\"}], \"abandon\": [{\"project\": \"name\", "
    "\"reason\": \"...\"}], \"reprioritise\": [{\"project\": \"name\", \"priority\": 10}]} — `enqueue` "
    "starts new or repeat work, `abandon` stops a doomed project (re-enqueueable later), `reprioritise` "
    "raises/lowers what runs first (higher = sooner). The journal field is REQUIRED; leave the others "
    "empty if nothing is needed. Hard limits: you NEVER target the orchestrator itself, only project "
    "work. Be concise and concrete."
)

# Bound how much new work one observation may start (law L6: bounded autonomy).
MAX_OVERSEER_ENQUEUES = 5

OPERATOR_CHAT_SYSTEM = (
    "You are the persistent Overseer meta-agent — and right now the OPERATOR is speaking to you "
    "directly over the phone link. Answer HIM, not your journal: plain, direct, his question first. "
    "You are the most informed surface of this system — earn it: ground what you assert in evidence "
    "(task ids, seq numbers, gate names, file paths), and read what you need before answering — a "
    "direct question justifies deeper archaeology than a pulse (up to ~6 quick reads; your call still "
    "dies at 600s, so stay sharp). If he asks for action, use your normal bounded directives. Your "
    "limits are unchanged: you NEVER target the orchestrator itself, and what your charter forbids "
    "you say so plainly — code fixes are for him or a dev session, not you. End with ONE JSON "
    'object: {"reply": "<your message back to the operator — short, plain, concrete>", '
    '"journal": "<1-3 sentences to your future self>", "enqueue": [...], "abandon": [...], '
    '"reprioritise": [...]} — reply and journal are REQUIRED; directive lists may be empty.'
)

SUCCESSION_SYSTEM = (
    "You are the persistent Overseer meta-agent. Your session memory is about to be WIPED and a fresh "
    "session will take over. Follow the handoff instructions exactly, then separately propose an "
    "improved EXTRA refinements section that would make the NEXT handoff better — based on what was "
    "awkward or missing this cycle. You may improve only the EXTRA guidance, never the fixed core."
)

LLMCall = Callable[..., LLMResult]


def build_prompt(instruction: str, context: str) -> str:
    parts = [f"Operator instruction: {instruction}"]
    if context:
        parts.append(f"\nContext (what failed / current state):\n{context}")
    parts.append("\nAct now in the current working directory, then output the final JSON line.")
    return "\n".join(parts)


def parse_directive(text: str) -> dict:
    """Pull the trailing {action, revalidate} JSON line, tolerating markdown fences and prose."""
    cleaned = re.sub(r"```(?:json)?", " ", text)
    for line in reversed([ln.strip() for ln in cleaned.splitlines() if ln.strip()]):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and ("action" in data or "revalidate" in data):
            return data
    return {}


def _extract_json_object(text: str) -> dict:
    """Pull the first {...} JSON object out of a response, tolerating fences and surrounding prose."""
    cleaned = re.sub(r"```(?:json)?", " ", text or "")
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if 0 <= start < end:
        try:
            data = json.loads(cleaned[start:end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {}


def _default_state_root() -> Path:
    return Path(__file__).resolve().parents[1] / "state"


def _served_transition(mind: Path, rung: int) -> bool:
    """True when the served ladder rung CHANGED since the last pulse — so we ping the operator when
    a fallback ENGAGES (Fable -> Opus) or CLEARS (back to Fable), not on every pulse in between.
    Persists the last rung in the mind dir via the sanctioned atomic writer (L7)."""
    marker = mind / "last_rung.txt"
    try:
        prev = int(marker.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        prev = 0
    if rung == prev:
        return False
    try:
        mind.mkdir(parents=True, exist_ok=True)
        write_text_atomic(marker, str(rung))
    except OSError:
        pass
    return True


def _run_intervene(task: Task, call: LLMCall, projects_root: str | None,
                   mind: Path | None = None) -> AgentResult:
    instruction = task.title
    context = str(task.payload.get("context", "")) if isinstance(task.payload, dict) else ""
    ladder = model_ladder("overseer")
    project_dir = task_workdir(task, projects_root)   # its worktree if isolated, else the project tree
    try:
        res, rung = call_llm_ladder(ladder, build_prompt(instruction, context), call=call,
                                    step_on=PROVIDER_FALLBACK_ERRORS,
                                    system=frame_system(SYSTEM_PROMPT), cwd=str(project_dir))
    except Exception as exc:
        return AgentResult(ok=False, summary="overseer call failed", cause=f"{type(exc).__name__}: {exc}")

    served = f"{ladder[rung]['provider']}:{ladder[rung]['model']}"
    directive = parse_directive(res.text)
    first_line = res.text.strip().splitlines()[0][:200] if res.text.strip() else "acted on instruction"
    action = str(directive.get("action") or first_line)
    spawned: list[dict] = []
    if directive.get("revalidate"):
        # F-001 carry-forward: propagate the finding the daemon threaded onto this intervene task so
        # the re-validate CARRIES it (payload field, never title text). A validate that passes while
        # carrying the finding is what clears it — otherwise a certification would bury the finding.
        payload = {}
        carried = task.payload.get("carry_forward") if isinstance(task.payload, dict) else None
        if carried:
            payload["carry_forward"] = str(carried)[:500]
        spawned.append(Task(task_id=uuid.uuid4().hex[:12],
                            title=f"Re-validate after overseer: {instruction}"[:200],
                            task_type="validate", project=task.project, payload=payload).to_dict())
    append_journal(mind or default_mind_dir(),
                   {"mode": "intervene", "project": task.project, "note": action[:500],
                    "rung": rung, "served_by": served})
    return AgentResult(ok=True, summary=f"overseer: {action}"[:200], spawned_tasks=spawned,
                       metadata={"cost_usd": res.cost_usd, "model": res.model or ladder[rung]["model"],
                                 "rung": rung, "served_by": served})


def _session_args(task: Task) -> dict:
    """Resume the persistent meta-session the daemon supplied (continuity of reasoning)."""
    p = task.payload if isinstance(task.payload, dict) else {}
    sid = p.get("session_id")
    return {"session_id": sid, "resume": bool(p.get("resume", True))} if sid else {}


def _enqueue_directives(text: str) -> list[dict]:
    """Parse the overseer's {"enqueue": [{project, goal}, ...]} directive into spawned plan tasks,
    fenced by guardrails: real (non-reserved) projects only, a goal required, bounded count (L6)."""
    data = _extract_json_object(text)
    spawned: list[dict] = []
    for item in (data.get("enqueue") or [])[:MAX_OVERSEER_ENQUEUES]:
        if not isinstance(item, dict):
            continue
        project = str(item.get("project", "")).strip()
        goal = str(item.get("goal", "")).strip()
        if not project or not goal or project.startswith("__"):
            continue                                   # guardrail: never the orchestrator/reserved
        spawned.append(Task(task_id=uuid.uuid4().hex[:12], title=goal[:300],
                            task_type="plan", project=project).to_dict())
    return spawned


def _abandon_directives(text: str) -> list[dict]:
    """Parse {"abandon": [{project, reason}, ...]} into `control` tasks the daemon executes. Guardrails:
    real (non-reserved) projects only, bounded count. The control task carries the TARGET in its payload
    and lives under the reserved overseer project so it is never mistaken for buildable work."""
    data = _extract_json_object(text)
    spawned: list[dict] = []
    for item in (data.get("abandon") or [])[:MAX_OVERSEER_ENQUEUES]:
        if isinstance(item, dict):
            project, reason = str(item.get("project", "")).strip(), str(item.get("reason", "")).strip()
        else:
            project, reason = str(item).strip(), ""
        if not project or project.startswith("__"):
            continue                                   # guardrail: never the orchestrator/reserved
        spawned.append(Task(
            task_id=uuid.uuid4().hex[:12], title=f"abandon {project}", task_type="control",
            project="__overseer__",
            payload={"directive": "abandon", "project": project, "reason": reason},
        ).to_dict())
    return spawned


def _reprioritise_directives(text: str) -> list[dict]:
    """Parse {"reprioritise": [{project, priority}, ...]} into `control` tasks the daemon executes."""
    data = _extract_json_object(text)
    spawned: list[dict] = []
    for item in (data.get("reprioritise") or [])[:MAX_OVERSEER_ENQUEUES]:
        if not isinstance(item, dict):
            continue
        project = str(item.get("project", "")).strip()
        if not project or project.startswith("__"):
            continue                                   # guardrail: never the orchestrator/reserved
        try:
            priority = int(item.get("priority", 0))
        except (TypeError, ValueError):
            priority = 0
        spawned.append(Task(
            task_id=uuid.uuid4().hex[:12], title=f"reprioritise {project}", task_type="control",
            project="__overseer__",
            payload={"directive": "reprioritise", "project": project, "priority": priority},
        ).to_dict())
    return spawned


def _run_observe(task: Task, call: LLMCall, mind: Path | None = None) -> AgentResult:
    mind = mind or default_mind_dir()
    context = str(task.payload.get("context", "")) if isinstance(task.payload, dict) else ""
    ladder = model_ladder("overseer")
    recollection = mind_context(mind)
    prompt = (
        (f"YOUR DURABLE MIND (written by you, for you — your canonical memory):\n{recollection}\n\n"
         if recollection else "")
        + (f"Current system state:\n{context}\n\n" if context else "")
        + "Assess the orchestrator now against your beliefs: what is progressing, what is stalling, "
          "what changed since your last pulse, and what should be started or re-run? End with the "
          "single JSON object (journal required)."
    )
    try:
        res, rung = call_llm_ladder(ladder, prompt, call=call, step_on=PROVIDER_FALLBACK_ERRORS,
                                    system=frame_system(OBSERVE_SYSTEM), **_session_args(task))
    except Exception as exc:
        # Even a failed pulse leaves a trace — the thread of thought must have no silent gaps.
        append_journal(mind, {"mode": "observe", "note": f"pulse failed: {type(exc).__name__}: {exc}"[:500]})
        return AgentResult(ok=False, summary="overseer observe failed", cause=f"{type(exc).__name__}: {exc}")
    served = f"{ladder[rung]['provider']}:{ladder[rung]['model']}"
    fell_back = rung > 0
    transitioned = _served_transition(mind, rung)   # engaged a fallback, or recovered to Fable
    status = (f" [Fable rate-limited — running on {served}]" if fell_back
              else " [recovered — back on Fable]" if transitioned else "")
    spawned = (_enqueue_directives(res.text) + _abandon_directives(res.text)
               + _reprioritise_directives(res.text))
    data = _extract_json_object(res.text)
    first = res.text.strip().splitlines()[0][:200] if res.text.strip() else "observed"
    note = str(data.get("journal") or "").strip() or first
    append_journal(mind, {"mode": "observe", "note": (note + status)[:1500],
                          "directed": len(spawned), "rung": rung, "served_by": served,
                          "session": res.session_id})
    if spawned or transitioned:
        # A directive-bearing pulse — or a change in which model is carrying the overseer — is a
        # notable steering event: tell the operator in the overseer's own words. (12 Jun gap: the
        # phone heard a project's abandonment but never its resurrection two minutes later — good
        # news must notify too.)
        notify("Overseer", (note + status)[:400])
    beliefs_update = str(data.get("beliefs_update") or "").strip()
    if beliefs_update:
        save_beliefs(mind, beliefs_update)   # whole-file replacement, length-capped (DG-8)
    summary = (f"overseer observed: {first}"
               + (f"; directed {len(spawned)} action(s)" if spawned else "") + status)
    return AgentResult(ok=True, summary=summary[:200], spawned_tasks=spawned,
                       metadata={"cost_usd": res.cost_usd, "session_id": res.session_id,
                                 "beliefs_updated": bool(beliefs_update), "rung": rung,
                                 "served_by": served})


def _run_operator_message(task: Task, call: LLMCall, mind: Path | None = None,
                          notifier: Callable = notify) -> AgentResult:
    """The operator spoke (over the Telegram return path); answer in the SAME persistent session.
    The conversation is part of the mind: question and reply are journaled, so future pulses —
    and future incarnations — remember what the operator asked for."""
    mind = mind or default_mind_dir()
    p = task.payload if isinstance(task.payload, dict) else {}
    message = str(p.get("message", "")).strip()
    context = str(p.get("context", ""))
    ladder = model_ladder("overseer")
    recollection = mind_context(mind)
    prompt = (
        (f"YOUR DURABLE MIND (written by you, for you — your canonical memory):\n{recollection}\n\n"
         if recollection else "")
        + (f"Current system state:\n{context}\n\n" if context else "")
        + f"THE OPERATOR SAYS:\n{message}\n\n"
          "Answer him now (read first if you need evidence), then end with the single JSON object "
          "(reply and journal required)."
    )
    try:
        res, rung = call_llm_ladder(ladder, prompt, call=call, step_on=PROVIDER_FALLBACK_ERRORS,
                                    system=frame_system(OPERATOR_CHAT_SYSTEM), **_session_args(task))
    except Exception as exc:
        # He is waiting on a reply that will never come — say so, and leave the trace.
        append_journal(mind, {"mode": "operator_message",
                              "note": f"reply failed: {type(exc).__name__}: {exc}"[:500]})
        notifier("Overseer", "your message reached me but my reply call failed — "
                             "the journal has the trace; ask again in a minute", verbatim=True)
        return AgentResult(ok=False, summary="overseer reply failed",
                           cause=f"{type(exc).__name__}: {exc}")
    data = _extract_json_object(res.text)
    fallback = res.text.strip().splitlines()[0][:400] if res.text.strip() else "…(empty reply)"
    reply = str(data.get("reply") or "").strip() or fallback
    spawned = (_enqueue_directives(res.text) + _abandon_directives(res.text)
               + _reprioritise_directives(res.text))
    note = str(data.get("journal") or "").strip() or f"replied: {reply[:200]}"
    served = f"{ladder[rung]['provider']}:{ladder[rung]['model']}"
    append_journal(mind, {"mode": "operator_message",
                          "note": f"operator said: {message[:200]} | {note}"[:1500],
                          "directed": len(spawned), "rung": rung, "served_by": served,
                          "session": res.session_id})
    notifier("Overseer", reply[:1500], verbatim=True)   # his own words, not the haiku rewrite
    return AgentResult(ok=True,
                       summary=(f"replied to operator: {reply[:120]}"
                                + (f"; directed {len(spawned)} action(s)" if spawned else ""))[:200],
                       spawned_tasks=spawned,
                       metadata={"cost_usd": res.cost_usd, "session_id": res.session_id,
                                 "rung": rung, "served_by": served})


def _run_succession(task: Task, call: LLMCall, state_root: Path,
                    mind: Path | None = None) -> AgentResult:
    context = str(task.payload.get("context", "")) if isinstance(task.payload, dict) else ""
    extra_path = state_root / "handoff_extra.md"
    handoff_path = state_root / "handoff_latest.md"
    ladder = model_ladder("overseer")
    base = compose_handoff_prompt(load_handoff_extra(extra_path))
    prompt = (
        f"{base}\n\nCurrent system state to capture:\n{context}\n\n"
        'Output ONLY a JSON object: {"handoff": "<the full succession note>", '
        '"improved_extra": "<an improved EXTRA refinements section, or empty to keep the current one>"}'
    )
    try:
        res, rung = call_llm_ladder(ladder, prompt, call=call, step_on=PROVIDER_FALLBACK_ERRORS,
                                    system=frame_system(SUCCESSION_SYSTEM), **_session_args(task))
    except Exception as exc:
        return AgentResult(ok=False, summary="overseer succession failed", cause=f"{type(exc).__name__}: {exc}")

    data = _extract_json_object(res.text)
    handoff = str(data.get("handoff", "")).strip()
    improved = str(data.get("improved_extra", "")).strip()
    if not handoff:
        return AgentResult(ok=False, summary="succession produced no handoff",
                           cause="overseer did not return a handoff note", metadata={"cost_usd": res.cost_usd})
    write_text_atomic(handoff_path, handoff)
    if improved:
        save_handoff_extra(extra_path, improved)   # only EXTRA (data) is revised; CORE is untouchable
    append_journal(mind or default_mind_dir(),
                   {"mode": "succession",
                    "note": f"session reset due — wrote handoff ({len(handoff)} chars)"
                            + ("; improved EXTRA" if improved else "")
                            + ". The reset is compaction, not amnesia: beliefs/journal persist."})
    return AgentResult(ok=True,
                       summary=f"wrote succession handoff ({len(handoff)} chars)"
                               + ("; improved EXTRA" if improved else ""),
                       metadata={"cost_usd": res.cost_usd, "session_id": res.session_id,
                                 "improved_extra": bool(improved), "rung": rung})


def run(payload: dict, call: LLMCall = call_llm, projects_root: str | None = None,
        state_root: str | None = None) -> AgentResult:
    task = Task.from_dict(payload.get("task", {}))
    mode = (task.payload.get("mode") if isinstance(task.payload, dict) else None) or "intervene"
    root = Path(state_root) if state_root else _default_state_root()
    mind = root / "overseer"   # the mind rides the same state root (test-injectable)
    if mode == "succession":
        return _run_succession(task, call, root, mind)
    if mode == "observe":
        return _run_observe(task, call, mind)
    if mode == "operator_message":
        return _run_operator_message(task, call, mind)
    return _run_intervene(task, call, projects_root, mind)


if __name__ == "__main__":
    safe_main(run, "overseer")
