"""edge.server — the Da Nang one-tap surface (read the durable state, act through existing channels).

A dependency-free HTTP surface (stdlib only) for steering the orchestrator from a browser or phone.
It READS the durable event log (never the live repo — the daemon stays the single writer) and ACTS
only by dropping signals into channels the daemon already ingests (confirmations, inbox). So the GUI
can never bypass a law or race the daemon. Decision-light by design: the home view is a short list
of what needs you, each with a one-tap action.

    python -m edge.server            # serve on http://127.0.0.1:8765
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from control.confirm import (
    default_confirm_dir,
    default_log,
    pending,
    project_states,
    request_confirmation,
)
from control.inbox import default_inbox
from control.intake import submit_goal, submit_plan
from infra.event_store import EventStore


def _state_root() -> Path:
    return Path(__file__).resolve().parents[1] / "state"


def escalations(store: EventStore) -> list[dict]:
    """Open escalations (task failures routed to the user), latest signal per task."""
    latest: dict[str, dict] = {}
    for ev in store.replay():
        if ev.kind == "escalation":
            latest[ev.data["task_id"]] = {
                "task_id": ev.data["task_id"],
                "cause": ev.data.get("cause", ""),
                "reason": ev.data.get("reason", ""),
            }
    return [latest[k] for k in sorted(latest)]


def _budget_spent(budget_log: Path) -> float:
    if not budget_log.exists():
        return 0.0
    return round(sum(float(e.data.get("cost", 0.0))
                     for e in EventStore(budget_log).replay() if e.kind == "spend"), 4)


def build_state(*, tasks_log: Path | None = None, budget_log: Path | None = None) -> dict:
    """Fold the durable logs into the Da Nang view model (pure: no live repo, no side effects)."""
    tasks_log = tasks_log or default_log()
    budget_log = budget_log or (_state_root() / "budget.events.log")
    store = EventStore(tasks_log)
    return {
        "projects": project_states(store),
        "pending": pending(store),
        "escalations": escalations(store),
        "budget": {"spent_usd": _budget_spent(budget_log)},
    }


def _make_handler(confirm_dir: Path, inbox: Path):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload, *, content_type: str = "application/json") -> None:
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (stdlib API)
            if self.path in ("/", "/index.html"):
                self._send(200, _PAGE.encode(), content_type="text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._send(200, build_state())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 (stdlib API)
            length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except (json.JSONDecodeError, ValueError):
                self._send(400, {"error": "bad json"})
                return
            if self.path == "/api/confirm":
                project = str(body.get("project", "")).strip()
                if not project:
                    self._send(400, {"error": "project required"})
                    return
                request_confirmation(project, confirm_dir)
                self._send(200, {"ok": True, "project": project})
            elif self.path == "/api/goal":
                goal = str(body.get("goal", "")).strip()
                project = str(body.get("project", "")).strip()
                if not goal or not project:
                    self._send(400, {"error": "goal and project required"})
                    return
                acceptance = body.get("acceptance") or None
                if body.get("plan"):
                    ids = [submit_plan(goal, project=project, acceptance=acceptance, inbox=str(inbox))]
                else:
                    ids = submit_goal(goal, project=project, acceptance=acceptance, inbox=str(inbox))
                self._send(200, {"ok": True, "ids": ids})
            else:
                self._send(404, {"error": "not found"})

        def log_message(self, *_args) -> None:  # keep the daemon's stdout quiet
            pass

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, *,
          confirm_dir: Path | str | None = None, inbox: Path | str | None = None) -> None:
    """Run the Da Nang surface until interrupted."""
    cdir = Path(confirm_dir) if confirm_dir else default_confirm_dir()
    ibox = Path(inbox) if inbox else default_inbox()
    httpd = ThreadingHTTPServer((host, port), _make_handler(cdir, ibox))
    print(f"Da Nang surface on http://{host}:{port}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main() -> None:
    serve()


if __name__ == "__main__":
    main()


_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orchestrator</title>
<style>
  :root { color-scheme: light dark; --gap: 14px; }
  * { box-sizing: border-box; }
  body { font: 16px/1.5 -apple-system, system-ui, sans-serif; margin: 0; padding: var(--gap);
         max-width: 680px; margin-inline: auto; }
  header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
  h1 { font-size: 1.25rem; margin: 0; } h2 { font-size: .8rem; text-transform: uppercase;
       letter-spacing: .06em; opacity: .6; margin: 22px 0 8px; }
  .spend { font-variant-numeric: tabular-nums; opacity: .7; font-size: .9rem; }
  .card { border: 1px solid color-mix(in srgb, currentColor 18%, transparent); border-radius: 12px;
          padding: 12px 14px; margin-bottom: 10px; }
  .row { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
  .name { font-weight: 600; } .cause { opacity: .7; font-size: .9rem; margin-top: 4px; }
  .badges { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
  .badge { font-size: .72rem; padding: 2px 8px; border-radius: 999px;
           background: color-mix(in srgb, currentColor 12%, transparent); }
  button { font: inherit; font-weight: 600; border: 0; border-radius: 10px; padding: 10px 16px;
           background: #2563eb; color: #fff; cursor: pointer; min-height: 44px; }
  button.ghost { background: color-mix(in srgb, currentColor 14%, transparent); color: inherit; }
  .muted { opacity: .55; } form { display: grid; gap: 8px; }
  input, label { font: inherit; } input[type=text] { padding: 10px; border-radius: 10px;
    border: 1px solid color-mix(in srgb, currentColor 25%, transparent); background: transparent; color: inherit; }
  .chk { display: flex; align-items: center; gap: 8px; font-size: .9rem; }
</style></head><body>
<header><h1>Orchestrator</h1><span class="spend" id="spend"></span></header>

<h2>Needs you</h2><div id="needs"></div>
<h2>Projects</h2><div id="projects"></div>
<h2>New goal</h2>
<form id="goal-form" class="card">
  <input type="text" id="g-goal" placeholder="What should it build?" required>
  <input type="text" id="g-project" placeholder="project name" required>
  <label class="chk"><input type="checkbox" id="g-plan"> let the Task Manager decompose it (LLM)</label>
  <button type="submit">Submit goal</button>
</form>

<script>
const $ = (id) => document.getElementById(id);
async function api(path, body) {
  const r = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)} : {});
  return r.json();
}
function badge(t){ return `<span class="badge">${t}</span>`; }
async function refresh() {
  const s = await api('/api/state');
  $('spend').textContent = '$' + (s.budget.spent_usd ?? 0).toFixed(4) + ' spent';
  const needs = [];
  for (const p of s.pending) needs.push(`<div class="card"><div class="row">
    <span class="name">${p}</span><button onclick="confirmProject('${p}')">Confirm ✓</button></div>
    <div class="badges">${badge('ready for sign-off')}</div></div>`);
  for (const e of s.escalations) needs.push(`<div class="card"><div class="row">
    <span class="name">⚠ ${e.task_id}</span><span class="muted">${e.reason}</span></div>
    <div class="cause">${e.cause||''}</div></div>`);
  $('needs').innerHTML = needs.join('') || '<p class="muted">Nothing needs you ✓</p>';
  const ps = Object.entries(s.projects);
  $('projects').innerHTML = ps.length ? ps.map(([n,st]) => {
    const b = [];
    if (st.confirmed) b.push('done'); else if (st.pending_user) b.push('awaiting you');
    if (st.hardened) b.push('hardened');
    if (st.assurance_reason) b.push(st.assurance_reason);
    return `<div class="card"><span class="name">${n}</span>
      <div class="badges">${b.map(badge).join('')}</div></div>`;
  }).join('') : '<p class="muted">No projects yet.</p>';
}
async function confirmProject(p){ await api('/api/confirm', {project:p}); refresh(); }
$('goal-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  await api('/api/goal', {goal: $('g-goal').value, project: $('g-project').value, plan: $('g-plan').checked});
  $('g-goal').value=''; refresh();
});
refresh(); setInterval(refresh, 4000);
</script>
</body></html>"""
