"""agents.researcher — the deep, tiered research agent. Subprocess contract: payload -> AgentResult.

Excavates knowledge rather than skimming: fan-out search, iterative deepening through the tier ladder
(Tier 1 popular web -> Tier 2 open archives/journals/non-Western sources -> public Tier 3), adversarial
self-verification, and a synthesised, cited output. It EMITS an evidence bundle; the gate that judges
depth lives in validation.research_contract (this agent sits below that layer and never imports it).

Findings are written to the knowledge base (kind=research) so the planner recalls them and the Overseer
digests them — the researcher composes with the KB rather than colliding with it (DV-2/DV-3).

Hard boundary: never circumvent paywalls, logins, or anti-bot protections. Public sources only; mark
what could not be found in `gaps` rather than faking completeness.

Run for real:
    echo '{"task": {"task_id":"r1","title":"Research X","task_type":"research","project":"edge"}}' \\
        | python -m agents.researcher
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Callable

from agents.common import safe_main
from core.models import AgentResult, Task
from infra.llm import LLMResult, call_llm
from memory.knowledge import KBEntry
from registry.agents import model_for

SYSTEM_PROMPT = (
    "You are the research agent in an autonomous orchestrator. Excavate deep, genuine knowledge — do "
    "NOT skim. Work the tier ladder: Tier 1 (popular open web) for orientation, then GO DEEPER into "
    "Tier 2 (open archives like archive.org, open-access journals and their APIs, articles, and "
    "non-Western / non-English sources) and public Tier 3 (obscure but genuinely public pages, primary "
    "documents nobody indexes). Fan out across multiple angles; follow citations; then adversarially "
    "verify every key claim before trusting it. HARD RULE: never bypass paywalls, logins, or anti-bot "
    "protections — public sources only; record what you could not reach in `gaps`, never invent it.\n\n"
    "Output ONLY a JSON object with this shape (every source needs an EXTRACTED excerpt, not just a "
    "link; tag each source's tier 1|2|3; set access to 'public'):\n"
    '{"question": str, "findings": [{"claim": str, "confidence": 0..1, "corroborations": int, '
    '"sources": [{"url": str, "tier": 1|2|3, "excerpt": str, "accessed": str, "access": "public"}]}], '
    '"synthesis": str, "gaps": [str]}'
)

LLMCall = Callable[..., LLMResult]


def build_prompt(task: Task) -> str:
    parts = [f"Research question: {task.title}"]
    if task.acceptance_criteria:
        parts.append("\nThe research must answer:\n" + "\n".join(f"- {c}" for c in task.acceptance_criteria))
    parts.append(
        "\nGo deep: prefer Tier-2/Tier-3 primary and archival sources over popular summaries. Extract a "
        "concrete finding from each source. Corroborate every important claim from independent sources. "
        "Return ONLY the JSON evidence bundle."
    )
    return "\n".join(parts)


def _extract_bundle(text: str) -> dict | None:
    """Pull the JSON evidence bundle out of the model output (tolerant of prose/code-fence wrapping)."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        candidate = text[start:end + 1] if start != -1 and end > start else None
    if candidate is None:
        return None
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _knowledge_entries(bundle: dict, task: Task) -> list[dict]:
    """Turn each finding into a validated KB entry (kind=research), so the KB write-gate is satisfied
    and the planner/Overseer can recall/digest what was learned."""
    entries: list[dict] = []
    for f in bundle.get("findings", []) or []:
        claim = str(f.get("claim", "")).strip()
        if not claim:
            continue
        urls = ", ".join(str(s.get("url", "")) for s in (f.get("sources", []) or []) if s.get("url"))
        body = f"{claim}\n\nSources: {urls}" if urls else claim
        entry = KBEntry(
            kind="research", body=body, project=task.project or "global",
            task_id=task.task_id, task_type="research",
            tags=["research"],
        )
        entry.validate()
        entries.append(asdict(entry))
    return entries


def run(payload: dict, call: LLMCall = call_llm, projects_root: str | None = None) -> AgentResult:
    task = Task.from_dict(payload.get("task", {}))
    spec = model_for("researcher")
    try:
        res = call(spec["provider"], spec["model"], build_prompt(task), system=SYSTEM_PROMPT)
    except Exception as exc:  # any provider/parse failure becomes a self-explaining result (L10)
        return AgentResult(ok=False, summary="research call failed",
                           cause=f"{type(exc).__name__}: {exc}")
    bundle = _extract_bundle(res.text or "")
    if bundle is None:
        return AgentResult(ok=False, summary="researcher produced no parseable evidence bundle",
                           cause="no evidence bundle in output")
    return AgentResult(
        ok=True,
        summary=str(bundle.get("synthesis", ""))[:2000],
        metadata={
            "evidence": bundle,                       # validation.research_contract gates this at settle
            "knowledge": _knowledge_entries(bundle, task),
            "cost_usd": res.cost_usd,
        },
    )


if __name__ == "__main__":
    safe_main(run, "researcher")
