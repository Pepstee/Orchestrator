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

export AGENTIC_JUDGE="${AGENTIC_JUDGE:-claude:opus}"
export AGENTIC_BUDGET_USD="${AGENTIC_BUDGET_USD:-1000000}"
export AGENTIC_MAX_WORKERS="${AGENTIC_MAX_WORKERS:-20}"
PY="${PYTHON:-python3}"

while [ ! -f STOP ]; do
  echo "[supervisor] $(date '+%F %T') launching daemon (workers=$AGENTIC_MAX_WORKERS, judge=$AGENTIC_JUDGE)"
  "$PY" -m control.daemon
  code=$?
  [ -f STOP ] && break
  echo "[supervisor] $(date '+%F %T') daemon exited ($code) — relaunching in 5s (touch STOP to stop)"
  sleep 5
done
echo "[supervisor] $(date '+%F %T') STOP present — staying down."
