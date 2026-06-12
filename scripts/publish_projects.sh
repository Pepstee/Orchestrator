#!/usr/bin/env bash
# publish_projects.sh — give every project repository a private GitHub home and push it.
#
# Operator-run (12 Jun): agents have no GitHub credentials by design, so publishing is a human
# act. Prerequisites, once: `brew install gh` then `gh auth login`.
#
# Idempotent: a project that already has an `origin` is just pushed; a failed creation (name
# taken, network) is reported and the loop continues — re-run after fixing. Nothing here ever
# rewrites history: create + push only.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

command -v gh >/dev/null 2>&1 || { echo "GitHub CLI missing — run: brew install gh"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Not logged in — run: gh auth login"; exit 1; }

created=0; pushed=0; failed=0
for d in "$ROOT"/projects/*/; do
  [ -d "$d/.git" ] || continue
  name="$(basename "$d")"
  if git -C "$d" remote get-url origin >/dev/null 2>&1; then
    echo "== $name: origin exists — pushing latest"
    if git -C "$d" push -u origin HEAD >/dev/null 2>&1; then
      echo "   pushed"; pushed=$((pushed + 1))
    else
      echo "   PUSH FAILED — inspect: git -C $d push -u origin HEAD"; failed=$((failed + 1))
    fi
    continue
  fi
  echo "== $name: creating private repo and pushing full history"
  if gh repo create "$name" --private --source "$d" --push >/dev/null 2>&1; then
    url="$(gh repo view "$name" --json url -q .url 2>/dev/null || true)"
    echo "   done: ${url:-created}"; created=$((created + 1))
  else
    echo "   CREATE FAILED (name taken? network?) — manual: gh repo create $name --private --source $d --push"
    failed=$((failed + 1))
  fi
done

echo
echo "Summary: $created created, $pushed re-pushed, $failed failed."
