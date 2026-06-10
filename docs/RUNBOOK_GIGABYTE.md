# Runbook — running the orchestrator on the Gigabyte (Windows + WSL2)

*Why WSL2: v2 has only ever run and been tested on Unix (macOS + the CI sandbox, 292 tests).
WSL2 Ubuntu is that same environment; the bash launcher, pid-lock, worktrees and shell-executed
acceptance criteria all work untouched. Native Windows would mean porting work for zero gain.*

## What git does NOT carry (seed these separately)

`state/` and `projects/` are gitignored by law. A fresh clone has **no flagship file, no
Telegram config, no event log, and no project code**. The seed tarball (made on the Mac)
carries: `projects/` (the deliverable trees, ~115 MB), `state/flagship`, `state/telegram.json`
(SECRET — never push it to GitHub). The event log deliberately does NOT travel: a fresh log on
the new machine is a clean slate; budgets and fingerprints of the dead era are irrelevant, and
the re-scope contract is re-dropped (step 6).

## One-time setup (WSL2 Ubuntu shell on the Gigabyte)

```
sudo apt update && sudo apt install -y git python3 python3-pip python3-venv
pip3 install pytest
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
npm install -g @anthropic-ai/claude-code @openai/codex
claude login
codex login
git config --global user.email "gutu.artiom444@gmail.com" && git config --global user.name "Artiom"
```

`claude login` and `codex login` open browser auth — Claude Max and ChatGPT Go respectively.
Verify both: `claude -p --model claude-fable-5 "Reply with exactly: ok"` and
`codex exec --json "Reply with exactly: ok"`.

## Deploy

```
git clone https://github.com/Pepstee/Orchestrator.git ~/agentic-orchestrator
cd ~/agentic-orchestrator
tar xzf /mnt/c/Users/<WINDOWS_USER>/Downloads/orchestrator-seed.tar.gz
python3 -m pytest tests/ -q
```

(The seed tarball restores `projects/`, `state/flagship`, `state/telegram.json`. The pytest run
is the boot self-test's dress rehearsal — it must be green before launch, and the daemon will
re-verify at every boot regardless.)

## Re-drop the flagship contract (the old event log stayed on the Mac)

```
cd ~/agentic-orchestrator && python3 - <<'EOF'
import sys, uuid
sys.path.insert(0, ".")
from control.inbox import drop
from core.models import Task
drop(Task(
    task_id=uuid.uuid4().hex[:12],
    title=("Dubbing Studio re-scope (D2.5): a real subtitle-dubbing product at industry level - "
           "real TTS synthesis, real dubbed audio out, web UX a stranger can use, zero mocks"),
    task_type="plan", project="dubbing-studio",
    acceptance_criteria=[
        "Real synthesis only: a locally-runnable real TTS engine (piper-tts or coqui preferred; "
        "espeak-ng acceptable as the minimum-real floor on Linux) - no Mock*/fake/dummy backends "
        "anywhere in shipped code (the authenticity gate scans for them)",
        "End-to-end demo: the `acceptance` file's criteria run the real product on "
        "samples/sample.srt and produce a non-empty, playable dubbed audio file (wav/mp3) whose "
        "segments align to the subtitle timings",
        "Web UX runnable by a stranger: a local web UI to upload an SRT (or video+SRT), preview "
        "and download the dubbed result; one acceptance criterion starts the server and verifies "
        "a real response",
        "Demolition rides the re-scope: delete the dead tts_studio/ package and the old mock "
        "acceptance.py (delete-manifest row C1); executable `acceptance` criteria replace them",
        "Industry reference parity: README maps capability against the ElevenLabs-Dubbing / "
        "Rask-class core flow (SRT in -> dubbed audio out); the judge reviews against it",
        "Project tests pass; nothing leaves the machine - no paid APIs, no publishing, no spend",
    ],
    payload={"mode": "rescope"},
))
print("contract dropped")
EOF
```

(Note the one platform change vs the Mac contract: `say` doesn't exist on Linux — `espeak-ng`
is the minimum-real floor; piper/coqui preferred for quality.)

## Launch

```
cd ~/agentic-orchestrator && rm -f STOP && nohup bash run_forever.sh > supervisor.log 2>&1 & disown
sleep 30 && tail -3 supervisor.log
```

## Keep the machine awake

Windows Settings → System → Power → Screen & sleep → **Never** (on mains). WSL2 stays alive as
long as a process runs inside it, but Windows sleep suspends everything — a desktop on mains
should simply never sleep.

## Remote control from the Mac (until Phase G's signal surface)

Over Tailscale SSH, everything works as locally:
`ssh <gigabyte> "tail -20 ~/agentic-orchestrator/supervisor.log"` ·
`ssh <gigabyte> "tail -5 ~/agentic-orchestrator/state/overseer/journal.jsonl"` ·
stop: `ssh <gigabyte> "touch ~/agentic-orchestrator/STOP"` ·
plus Telegram carrying all notifications to your phone regardless of where you are.

## Rules that still apply

ONE orchestrator at a time on the shared Max account — stop the Mac's daemon before launching
the Gigabyte's (the two-orchestrators-one-budget lesson, RUN_LEDGER §1). The first boot on a new
platform is the boot self-test's field test: if it refuses, it prints why — that is the law
working, not a defect.
