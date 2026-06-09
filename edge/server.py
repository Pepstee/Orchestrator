"""edge.server — the Da Nang one-tap surface (read the durable state, act through existing channels).

A dependency-free HTTP surface (stdlib only) for steering the orchestrator from a browser or phone.
It READS the durable event log (never the live repo — the daemon stays the single writer) and ACTS
only by dropping signals into channels the daemon already ingests (confirmations, inbox). So the GUI
can never bypass a law or race the daemon. Decision-light by design: the home view is a short list
of what needs you, each with a one-tap action.

    python -m edge.server            # serve on http://127.0.0.1:8765
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import subprocess
import time
from collections import Counter
from http import cookies as http_cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from control.confirm import (
    default_confirm_dir,
    default_log,
    pending,
    project_states,
    request_confirmation,
)
from control.enqueue import enqueue
from control.inbox import default_inbox
from control.intake import submit_goal, submit_plan
from infra.atomic_io import read_json, write_json_atomic
from infra.event_store import EventStore
from infra.llm import is_transient_cause


def _state_root() -> Path:
    return Path(__file__).resolve().parents[1] / "state"


def escalations(store: EventStore) -> list[dict]:
    """OPEN escalations only — task failures still awaiting the user. An escalation is resolved
    (and dropped) when its project has been confirmed, or when a later same-type task in the project
    has since completed (a retry or overseer fix superseded the failure). Otherwise the tray would
    accumulate resolved failures forever over a long unattended run."""
    created: list[tuple[str, str, str]] = []     # (task_id, project, task_type) in creation order
    status: dict[str, str] = {}
    confirmed: set[str] = set()
    raw: dict[str, dict] = {}
    esc_order: dict[str, int] = {}                # escalated task_id -> when it was escalated
    instructed: dict[str, int] = {}              # project -> when it was last given an oversee task
    order = 0
    for ev in store.replay():
        order += 1
        d = ev.data
        if ev.kind == "task_created":
            t = d["task"]
            created.append((t["task_id"], t.get("project", ""), t.get("task_type", "")))
            status[t["task_id"]] = t.get("status", "queued")
            # A non-meta oversee task is the durable trace of "you (or the stall-guard) acted on this
            # project". One created AFTER an escalation = a response to it -> the escalation is handled.
            if t.get("task_type") == "oversee" and not t.get("project", "").startswith("__"):
                instructed[t.get("project", "")] = order
        elif ev.kind == "task_transition" and d["task_id"] in status:
            status[d["task_id"]] = d["to"]
        elif ev.kind == "project_confirmed":
            confirmed.add(d["project"])
        elif ev.kind == "escalation":
            raw[d["task_id"]] = {
                "task_id": d["task_id"], "cause": d.get("cause", ""),
                "reason": d.get("reason", ""), "project": d.get("project", ""),
            }
            esc_order[d["task_id"]] = order
    proj_of = {tid: p for tid, p, _ in created}
    type_of = {tid: ty for tid, _, ty in created}

    def superseded(tid: str, project: str, ttype: str) -> bool:
        seen = False
        for cid, cproj, ctype in created:
            if cid == tid:
                seen = True
            elif seen and cproj == project and ctype == ttype and status.get(cid) == "done":
                return True
        return False

    out: list[dict] = []
    for tid, esc in raw.items():
        project = esc["project"] or proj_of.get(tid, "")
        if project.startswith("__"):
            continue                              # the orchestrator's own meta-tasks (e.g. __overseer__)
            # — internal plumbing, not your decision; surfaced in the activity feed, not the tray
        if is_transient_cause(esc["cause"]):
            continue                              # restart-kills / rate limits are never real defects
        if project and project in confirmed:
            continue
        if superseded(tid, project, type_of.get(tid, "")):
            continue
        if project and instructed.get(project, -1) > esc_order.get(tid, 0):
            continue                              # you've since instructed it -> it's being handled, not waiting
        esc["project"] = project
        out.append(esc)
    return sorted(out, key=lambda e: e["task_id"])


def _budget_spent(budget_log: Path | str) -> float:
    budget_log = Path(budget_log)
    if not budget_log.exists():
        return 0.0
    return round(sum(float(e.data.get("cost", 0.0))
                     for e in EventStore(budget_log).replay() if e.kind == "spend"), 4)


def health(tasks_log: Path | str) -> dict:
    """A live heartbeat for the GUI: how long since the daemon last wrote an event (it writes on every
    cycle), whether that counts as alive, and a one-line count of what each task is doing right now.
    Lets you see the orchestrator is working without asking anyone."""
    p = Path(tasks_log)
    age = round(time.time() - p.stat().st_mtime, 1) if p.exists() else None
    counts: Counter = Counter()
    if p.exists():
        st: dict[str, str] = {}
        for ev in EventStore(p).replay():
            d = ev.data
            if ev.kind == "task_created":
                st[d["task"]["task_id"]] = d["task"].get("status", "queued")
            elif ev.kind == "task_transition" and d["task_id"] in st:
                st[d["task_id"]] = d["to"]
        counts = Counter(st.values())
    running, queued = counts.get("in_progress", 0), counts.get("queued", 0)
    # A task in progress means it's WORKING (an agent call can legitimately run for minutes) — never
    # call that 'stopped'. Only 'stalled?' when nothing's running yet work is queued and it's gone
    # quiet (likely the daemon died), and 'idle' when there's simply nothing to do.
    if running > 0:
        status = "working"
    elif age is None:
        status = "no activity yet"
    elif age < 120:
        status = "live"
    elif queued > 0:
        status = "stalled?"
    else:
        status = "idle"
    return {
        "last_activity_s": age,
        "status": status,
        "alive": running > 0 or (age is not None and age < 120),
        "running": running,
        "queued": queued,
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0),
    }


def activity(store: EventStore, *, limit: int = 20) -> list[dict]:
    """A human-readable, timestamped feed of the meaningful things the orchestrator has DONE recently
    (overseer actions, judge verdicts, ready-for-you, real failures, escalations, confirmations, new
    work). Newest first, capped. Noise (every task transition, transient restart-kills) is omitted."""
    task_type: dict[str, str] = {}
    feed: list[dict] = []

    def add(ts: float, text: str) -> None:
        feed.append({"ts": ts, "text": text[:160]})

    for ev in store.replay():
        d, ts = ev.data, ev.ts
        if ev.kind == "task_created":
            t = d["task"]
            task_type[t["task_id"]] = t.get("task_type", "")
            proj, tt = t.get("project", ""), t.get("task_type", "")
            if tt == "plan":
                add(ts, f"planning — {proj}")
            elif tt == "control":
                p = t.get("payload", {}) or {}
                add(ts, f"{p.get('directive', 'control')} — {p.get('project', proj)}")
        elif ev.kind == "task_result":
            tt = task_type.get(d["task_id"], "")
            ok, summ, cause = d.get("ok"), d.get("summary") or "", d.get("cause") or ""
            if tt == "oversee" and ok:
                add(ts, f"overseer — {summ}")
            elif tt == "validate":
                add(ts, f"judge — {summ if ok else 'rejected: ' + cause}")
            elif not ok and not is_transient_cause(cause):
                add(ts, f"failed — {summ}: {cause}")
        elif ev.kind == "project_status" and d.get("pending_user"):
            add(ts, f"ready for sign-off — {d.get('project', '')}")
        elif ev.kind == "assurance_result" and not d.get("fully_hardened"):
            add(ts, f"not ship-ready — {d.get('project', '')}: {d.get('reason', '')}")
        elif ev.kind == "escalation" and not is_transient_cause(d.get("cause", "")):
            add(ts, f"needs you — {d.get('project', '') or d.get('task_id', '')}")
        elif ev.kind == "project_confirmed":
            add(ts, f"you confirmed — {d.get('project', '')}")
    return list(reversed(feed[-limit:]))               # most recent first


def project_overview(store: EventStore) -> dict:
    """Every project that exists, with its LIVE task counts — so in-flight projects show on the
    dashboard immediately, not only after they drain and get evaluated. Merges in the finalised
    flags (confirmed/hardened) for projects that have reached an evaluation."""
    task_proj: dict[str, str] = {}
    task_status: dict[str, str] = {}
    for ev in store.replay():
        d = ev.data
        if ev.kind == "task_created":
            t = d["task"]
            task_proj[t["task_id"]] = t.get("project", "")
            task_status[t["task_id"]] = t.get("status", "queued")
        elif ev.kind == "task_transition" and d["task_id"] in task_status:
            task_status[d["task_id"]] = d["to"]
    counts: dict[str, Counter] = {}
    for tid, proj in task_proj.items():
        if proj.startswith("__"):
            continue                          # hide the overseer's own meta-tasks
        counts.setdefault(proj, Counter())[task_status[tid]] += 1
    folded = project_states(store)
    projects = sorted(p for p in set(counts) | set(folded) if not p.startswith("__"))
    out = {}
    for proj in projects:
        c = counts.get(proj, Counter())
        info = folded.get(proj, {})
        out[proj] = {
            "running": c.get("in_progress", 0), "queued": c.get("queued", 0),
            "done": c.get("done", 0), "failed": c.get("failed", 0),
            "confirmed": bool(info.get("confirmed")), "hardened": bool(info.get("hardened")),
        }
    return out


def build_state(*, tasks_log: Path | None = None, budget_log: Path | None = None) -> dict:
    """Fold the durable logs into the Da Nang view model (pure: no live repo, no side effects)."""
    tasks_log = tasks_log or default_log()
    budget_log = budget_log or (_state_root() / "budget.events.log")
    store = EventStore(tasks_log)
    return {
        "projects": project_overview(store),
        "pending": pending(store),
        "escalations": escalations(store),
        "health": health(tasks_log),
        "activity": activity(store),
        "budget": {"spent_usd": _budget_spent(budget_log)},
    }


def load_or_create_token(state_dir: Path) -> str:
    """The shared GUI token: AGENTIC_GUI_TOKEN if set, else a persisted random one (created once)."""
    env = os.environ.get("AGENTIC_GUI_TOKEN")
    if env:
        return env
    path = Path(state_dir) / "gui_token.json"
    data = read_json(path)
    if isinstance(data, dict) and data.get("token"):
        return str(data["token"])
    token = secrets.token_urlsafe(32)
    write_json_atomic(path, {"token": token})   # L7: the only sanctioned writer
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


def _is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1", "")


def _lan_ip() -> str:
    """Best-effort LAN IP of this machine — the address a phone on the same network should open.
    (0.0.0.0 means 'bind all interfaces' to the server but is NOT reachable as a destination.)"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))   # no packet is sent; this just picks the routing interface
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _tailscale_ip() -> str | None:
    """The Mac's Tailscale (100.x) address if Tailscale is up — reachable from anywhere, privately."""
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    line = (out.stdout or "").strip().splitlines()
    return line[0].strip() if out.returncode == 0 and line else None


def _cookie_token(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    jar = http_cookies.SimpleCookie()
    try:
        jar.load(cookie_header)
    except http_cookies.CookieError:
        return None
    morsel = jar.get("gui_token")
    return morsel.value if morsel else None


def authorised(
    expected: str,
    *,
    auth_header: str | None = None,
    query_token: str | None = None,
    cookie_header: str | None = None,
) -> bool:
    """True iff a valid token arrives by header, query param, or cookie. Fails closed (constant-time)."""
    if not expected:
        return False                                   # unconfigured -> deny, never open
    candidates = [auth_header, query_token, _cookie_token(cookie_header)]
    return any(c is not None and hmac.compare_digest(expected, c) for c in candidates)


def _make_handler(confirm_dir: Path, inbox: Path, token: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload, *, content_type: str = "application/json",
                  extra_headers: dict | None = None) -> None:
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _auth(self) -> tuple[bool, str]:
            parts = urlsplit(self.path)
            query_token = parse_qs(parts.query).get("token", [None])[0]
            ok = authorised(token, auth_header=self.headers.get("X-Auth-Token"),
                            query_token=query_token, cookie_header=self.headers.get("Cookie"))
            return ok, parts.path

        def do_GET(self) -> None:  # noqa: N802 (stdlib API)
            ok, path = self._auth()
            if path in ("/", "/index.html"):
                if not ok:
                    self._send(401, _UNAUTH_PAGE.encode(), content_type="text/html; charset=utf-8")
                    return
                cookie = f"gui_token={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000"
                self._send(200, _PAGE.encode(), content_type="text/html; charset=utf-8",
                           extra_headers={"Set-Cookie": cookie})
            elif path == "/api/state":
                if not ok:
                    self._send(401, {"error": "unauthorised"})
                    return
                self._send(200, build_state())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 (stdlib API)
            ok, path = self._auth()
            if not ok:
                self._send(401, {"error": "unauthorised"})
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except (json.JSONDecodeError, ValueError):
                self._send(400, {"error": "bad json"})
                return
            if path == "/api/confirm":
                project = str(body.get("project", "")).strip()
                if not project:
                    self._send(400, {"error": "project required"})
                    return
                request_confirmation(project, confirm_dir)
                self._send(200, {"ok": True, "project": project})
            elif path == "/api/goal":
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
            elif path == "/api/instruct":
                instruction = str(body.get("instruction", "")).strip()
                project = str(body.get("project", "")).strip()
                if not instruction or not project:
                    self._send(400, {"error": "instruction and project required"})
                    return
                context = str(body.get("context", ""))
                task_id = enqueue(instruction, task_type="oversee", project=project,
                                  payload={"context": context}, inbox=str(inbox))
                self._send(200, {"ok": True, "task_id": task_id})
            else:
                self._send(404, {"error": "not found"})

        def log_message(self, *_args) -> None:  # keep the daemon's stdout quiet
            pass

    return Handler


def serve(host: str | None = None, port: int | None = None, *, token: str | None = None,
          confirm_dir: Path | str | None = None, inbox: Path | str | None = None,
          state_dir: Path | str | None = None) -> None:
    """Run the Da Nang surface until interrupted (token-gated; bind address configurable)."""
    state = Path(state_dir) if state_dir else _state_root()
    host = host or os.environ.get("AGENTIC_GUI_HOST", "127.0.0.1")
    port = int(port if port is not None else os.environ.get("AGENTIC_GUI_PORT", "8765"))
    token = token or load_or_create_token(state)
    cdir = Path(confirm_dir) if confirm_dir else default_confirm_dir()
    ibox = Path(inbox) if inbox else default_inbox()
    httpd = ThreadingHTTPServer((host, port), _make_handler(cdir, ibox, token))
    if _is_loopback(host):
        print(f"Da Nang surface: http://{host}:{port}/?token={token}")
    else:
        # 0.0.0.0 binds every interface but is unreachable as a URL — print the real LAN address.
        print("WARNING: bound to a non-loopback address — reachable by anyone on your network.")
        print("         The token is the only protection; keep the URL private. Stop with Ctrl-C.")
        print(f"  on this Mac:     http://127.0.0.1:{port}/?token={token}")
        print(f"  from your phone: http://{_lan_ip()}:{port}/?token={token}   (same Wi-Fi)")
        tailnet = _tailscale_ip()
        if tailnet:
            print(f"  from anywhere:   http://{tailnet}:{port}/?token={token}   (Tailscale)")
        print("  can't connect on Wi-Fi? allow incoming connections for python3 in")
        print("  System Settings -> Network -> Firewall.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main() -> None:
    serve()


_UNAUTH_PAGE = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orchestrator</title>
<body style="font: 16px/1.6 -apple-system, system-ui, sans-serif; max-width: 420px; margin: 12vh auto; padding: 0 1rem;">
<h1 style="font-size: 1.2rem;">Token required</h1>
<p style="opacity: .7;">Open this surface with your access token appended, e.g.
<code>?token=…</code>. The daemon prints the full URL on startup.</p>
</body>"""


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
<div id="health" class="spend" style="margin:-4px 0 4px"></div>

<h2>Needs you</h2><div id="needs"></div>
<h2>Projects</h2><div id="projects"></div>
<h2>Recent activity</h2><div id="activity"></div>
<h2>New goal</h2>
<form id="goal-form" class="card">
  <input type="text" id="g-goal" placeholder="What should it build?" required>
  <input type="text" id="g-project" placeholder="project name" required>
  <label class="chk"><input type="checkbox" id="g-plan"> let the Task Manager decompose it (LLM)</label>
  <button type="submit">Submit goal</button>
</form>

<h2>Tell the overseer</h2>
<form id="ov-form" class="card">
  <input type="text" id="ov-instr" placeholder="Instruction, e.g. fix the failing import" required>
  <input type="text" id="ov-project" placeholder="project name" required>
  <button type="submit">Send to overseer</button>
</form>

<script>
const $ = (id) => document.getElementById(id);
async function api(path, body) {
  const r = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)} : {});
  return r.json();
}
function badge(t){ return `<span class="badge">${t}</span>`; }
let STATE = {projects:{}, pending:[], escalations:[], budget:{}};
async function refresh() {
  STATE = await api('/api/state');
  $('spend').textContent = '$' + (STATE.budget.spent_usd ?? 0).toFixed(4) + ' spent';
  const h = STATE.health || {};
  const age = h.last_activity_s;
  const ago = age == null ? 'no activity yet' : age < 90 ? Math.round(age)+'s ago'
            : age < 5400 ? Math.round(age/60)+'m ago' : Math.round(age/3600)+'h ago';
  const label = {working:'● working', live:'● live', idle:'○ idle',
    'stalled?':'⚠ stalled?', 'no activity yet':'○ no activity yet'}[h.status]
    || (h.alive ? '● live' : '○ idle');
  $('health').textContent = label +
    ` · last activity ${ago} · ${h.running||0} running, ${h.queued||0} queued, `
    + `${h.done||0} done, ${h.failed||0} failed`;
  const needs = [];
  STATE.pending.forEach((p, i) => needs.push(`<div class="card"><div class="row">
    <span class="name">${p}</span>
    <span><button onclick="confirmProject('${p}')">Confirm ✓</button>
    <button class="ghost" onclick="declinePending(${i})">Decline</button></span></div>
    <div class="badges">${badge('ready for sign-off')}</div></div>`));
  STATE.escalations.forEach((e, i) => needs.push(`<div class="card"><div class="row">
    <span class="name">⚠ ${e.project || e.task_id}</span>
    <button class="ghost" onclick="instructEsc(${i})">Instruct</button></div>
    <div class="cause">${e.reason}${e.cause ? ' — ' + e.cause : ''}</div></div>`));
  $('needs').innerHTML = needs.join('') || '<p class="muted">Nothing needs you ✓</p>';
  const ps = Object.entries(STATE.projects);
  $('projects').innerHTML = ps.length ? ps.map(([n,st]) => {
    const b = [];
    if (st.confirmed) b.push('done');
    if (st.hardened) b.push('hardened');
    const counts = `${st.running||0} running · ${st.queued||0} queued · ${st.done||0} done`
      + (st.failed ? ` · ${st.failed} failed` : '');
    return `<div class="card"><div class="row"><span class="name">${n}</span>
      <span class="muted" style="font-size:.85rem">${counts}</span></div>
      ${b.length ? `<div class="badges">${b.map(badge).join('')}</div>` : ''}</div>`;
  }).join('') : '<p class="muted">No projects yet.</p>';
  $('activity').innerHTML = (STATE.activity || []).map(a => {
    const t = new Date(a.ts * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    return `<div class="card" style="padding:8px 12px"><span class="muted"
      style="font-variant-numeric:tabular-nums; margin-right:8px">${t}</span>${a.text}</div>`;
  }).join('') || '<p class="muted">No activity yet.</p>';
}
async function confirmProject(p){ await api('/api/confirm', {project:p}); refresh(); }
async function declinePending(i){
  const p = STATE.pending[i];
  const t = prompt(`Tell the overseer what to do with “${p}” instead of confirming:`);
  if (t) { await api('/api/instruct', {project:p, instruction:t}); refresh(); }
}
async function instructEsc(i){
  const e = STATE.escalations[i];
  const p = e.project || prompt('Which project?');
  if (!p) return;
  const t = prompt(`Instruction for the overseer about “${p}”:`);
  if (t) { await api('/api/instruct', {project:p, instruction:t, context:e.cause}); refresh(); }
}
$('goal-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  await api('/api/goal', {goal: $('g-goal').value, project: $('g-project').value, plan: $('g-plan').checked});
  $('g-goal').value=''; refresh();
});
$('ov-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  await api('/api/instruct', {instruction: $('ov-instr').value, project: $('ov-project').value});
  $('ov-instr').value=''; refresh();
});
refresh(); setInterval(refresh, 4000);
</script>
</body></html>"""


if __name__ == "__main__":   # at the very end so all module constants (_PAGE, _UNAUTH_PAGE) exist first
    main()
