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
from infra.llm import LLMResult, call_llm
from infra.workspace import task_workdir
from memory.overseer import compose_handoff_prompt, frame_system, load_handoff_extra, save_handoff_extra
from registry.agents import model_for

SYSTEM_PROMPT = (
    "You are the Overseer: the operator's trusted agent with full command over THIS PROJECT (never "
    "the orchestrator itself). Carry out the operator's instruction precisely by creating/editing "
    "files in your current working directory. Make the smallest change that satisfies it; invent no "
    "extra scope. When finished, output a final line of JSON: "
    '{"action": "<one sentence on what you did>", "revalidate": true|false} '
    "— set revalidate true when the change should be re-checked by the test and judge gates."
)

OBSERVE_SYSTEM = (
    "You are the persistent Overseer meta-agent, reasoning across the WHOLE orchestrator with "
    "continuous memory of this ongoing session. You are not editing files now — you are thinking and "
    "DIRECTING. Review the system state and assess what matters: which projects progress, which "
    "stall, what should be started. You may DIRECT work, ending with a JSON object: "
    "{\"enqueue\": [{\"project\": \"name\", \"goal\": \"...\"}], \"abandon\": [{\"project\": \"name\", "
    "\"reason\": \"...\"}], \"reprioritise\": [{\"project\": \"name\", \"priority\": 10}]} — `enqueue` "
    "starts new or repeat work, `abandon` stops a doomed project (re-enqueueable later), `reprioritise` "
    "raises/lowers what runs first (higher = sooner). Omit or leave empty if nothing is needed. Hard "
    "limits: you NEVER target the orchestrator itself, only project work; the operator remains the "
    "final completion gate. Be concise and concrete."
)

# Bound how much new work one observation may start (law L6: bounded autonomy).
MAX_OVERSEER_ENQUEUES = 5

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


def _run_intervene(task: Task, call: LLMCall, projects_root: str | None) -> AgentResult:
    instruction = task.title
    context = str(task.payload.get("context", "")) if isinstance(task.payload, dict) else ""
    spec = model_for("overseer")
    project_dir = task_workdir(task, projects_root)   # its worktree if isolated, else the project tree
    try:
        res = call(spec["provider"], spec["model"], build_prompt(instruction, context),
                   system=frame_system(SYSTEM_PROMPT), cwd=str(project_dir))
    except Exception as exc:
        return AgentResult(ok=False, summary="overseer call failed", cause=f"{type(exc).__name__}: {exc}")

    directive = parse_directive(res.text)
    first_line = res.text.strip().splitlines()[0][:200] if res.text.strip() else "acted on instruction"
    action = str(directive.get("action") or first_line)
    spawned: list[dict] = []
    if directive.get("revalidate"):
        spawned.append(Task(task_id=uuid.uuid4().hex[:12],
                            title=f"Re-validate after overseer: {instruction}"[:200],
                            task_type="validate", project=task.project).to_dict())
    return AgentResult(ok=True, summary=f"overseer: {action}"[:200], spawned_tasks=spawned,
                       metadata={"cost_usd": res.cost_usd, "model": res.model or spec["model"]})


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


def _run_observe(task: Task, call: LLMCall) -> AgentResult:
    context = str(task.payload.get("context", "")) if isinstance(task.payload, dict) else ""
    spec = model_for("overseer")
    prompt = (
        (f"Current system state:\n{context}\n\n" if context else "")
        + "Assess the orchestrator now: what is progressing, what is stalling, and what should be "
          "started or re-run? If you decide to direct new work, end with the enqueue JSON object."
    )
    try:
        res = call(spec["provider"], spec["model"], prompt, system=frame_system(OBSERVE_SYSTEM), **_session_args(task))
    except Exception as exc:
        return AgentResult(ok=False, summary="overseer observe failed", cause=f"{type(exc).__name__}: {exc}")
    spawned = (_enqueue_directives(res.text) + _abandon_directives(res.text)
               + _reprioritise_directives(res.text))
    first = res.text.strip().splitlines()[0][:200] if res.text.strip() else "observed"
    summary = f"overseer observed: {first}" + (f"; directed {len(spawned)} action(s)" if spawned else "")
    return AgentResult(ok=True, summary=summary[:200], spawned_tasks=spawned,
                       metadata={"cost_usd": res.cost_usd, "session_id": res.session_id})


def _run_succession(task: Task, call: LLMCall, state_root: Path) -> AgentResult:
    context = str(task.payload.get("context", "")) if isinstance(task.payload, dict) else ""
    extra_path = state_root / "handoff_extra.md"
    handoff_path = state_root / "handoff_latest.md"
    spec = model_for("overseer")
    base = compose_handoff_prompt(load_handoff_extra(extra_path))
    prompt = (
        f"{base}\n\nCurrent system state to capture:\n{context}\n\n"
        'Output ONLY a JSON object: {"handoff": "<the full succession note>", '
        '"improved_extra": "<an improved EXTRA refinements section, or empty to keep the current one>"}'
    )
    try:
        res = call(spec["provider"], spec["model"], prompt, system=frame_system(SUCCESSION_SYSTEM), **_session_args(task))
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
    return AgentResult(ok=True,
                       summary=f"wrote succession handoff ({len(handoff)} chars)"
                               + ("; improved EXTRA" if improved else ""),
                       metadata={"cost_usd": res.cost_usd, "session_id": res.session_id,
                                 "improved_extra": bool(improved)})


def run(payload: dict, call: LLMCall = call_llm, projects_root: str | None = None,
        state_root: str | None = None) -> AgentResult:
    task = Task.from_dict(payload.get("task", {}))
    mode = (task.payload.get("mode") if isinstance(task.payload, dict) else None) or "intervene"
    if mode == "succession":
        return _run_succession(task, call, Path(state_root) if state_root else _default_state_root())
    if mode == "observe":
        return _run_observe(task, call)
    return _run_intervene(task, call, projects_root)


if __name__ == "__main__":
    safe_main(run, "overseer")
