#!/usr/bin/env bash
# run_forever.sh — keep the orchestrator alive unattended for as long as you like.
#
# The daemon never resurrects itself (law L8). This external supervisor does: if the daemon ever
# exits — crash, transient error, even after a reboot if you launch this at startup — it relaunches
# it. The daemon replays its durable log on boot, so a relaunch RESUMES (it never re-runs finished
# work). A deliberate stop is honoured: create a file named STOP in this directory and it stays down
# (a stop you chose stays stopped; a crash does not).
#
#   start:   nohup bash run_forever.sh > supervisor.log 2>&1 &
#   stop:    touch STOP        (then, to fully quit: pkill -f control.daemon)
#   resume:  rm STOP && nohup bash run_forever.sh > supervisor.log 2>&1 &
cd "$(dirname "$0")" || exit 1

# Singleton: only ONE supervisor at a time. Re-running this script while one is alive just exits,
# so accidental double-launches can't spawn duelling relaunch loops.
LOCK="state/supervisor.lock"
mkdir -p state
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "[supervisor] already running (pid $(cat "$LOCK")) — exiting."
  exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# Judge runs on the REGISTRY default (openai/codex — cross-provider anti-collusion, D4).
# Override only for a provider outage: AGENTIC_JUDGE="claude:opus" ./run_forever.sh
export AGENTIC_BUDGET_USD="${AGENTIC_BUDGET_USD:-1000000}"
export AGENTIC_MAX_WORKERS="${AGENTIC_MAX_WORKERS:-20}"
PY="${PYTHON:-python3}"

while [ ! -f STOP ]; do
  echo "[supervisor] $(date '+%F %T') launching daemon (workers=$AGENTIC_MAX_WORKERS, judge=${AGENTIC_JUDGE:-registry default})"
  "$PY" -m control.daemon
  code=$?
  [ -f STOP ] && break
  if [ "$code" -eq 3 ]; then
    # BG-1 boot self-test refused dispatch (SystemExit 3). This is DETERMINISTIC — a law-linked
    # check is red — so relaunching can never fix it; looping just re-runs the suite forever
    # (the 8 Jul crash-loop: planning/16 missing, ~30s per futile relaunch). Same doctrine as
    # the 401 fail-fast: a deterministic refusal stays down until the operator fixes the cause.
    echo "[supervisor] $(date '+%F %T') daemon refused to boot (BG-1 self-test, exit 3) — writing STOP and staying down; fix the red check, then rm STOP and relaunch."
    echo "BG-1 boot self-test failed at $(date '+%F %T') — see the daemon's notification / run the run-gates skill for the red check" > STOP
    break
  fi
  echo "[supervisor] $(date '+%F %T') daemon exited ($code) — relaunching in 5s (touch STOP to stop)"
  sleep 5
done
echo "[supervisor] $(date '+%F %T') STOP present — staying down."
