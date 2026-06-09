#!/usr/bin/env bash
# seed_edge.sh — enqueue the scoped flagship "Edge" (your personal intelligence brief).
# Scoping is LOCKED and human-approved; after this the orchestrator owns it and you are out of the
# loop. Run once, from the repo root:  bash scripts/seed_edge.sh
cd "$(dirname "$0")/.." || exit 1
PY="${PYTHON:-python3}"

GOAL='Build Edge, a near-real-time personal intelligence brief for an active crypto trader and investor, in Python. Ingest multiple pluggable injectable sources (crypto and markets, tech and AI via Hacker News and GitHub Trending, and general-news RSS) using POLITE polling of RSS feeds and official APIs only, on a configurable interval of 10 minutes or less, never aggressive scraping that trips anti-bot defences (respect rate limits, send a proper user agent, back off on errors). Score each story for relevance with a PLUGGABLE LLM backend defaulting to the authenticated Claude CLI and cleanly swappable to a local Ollama model. Dedup and cluster the same event across sources. For each story surface: a relevance score, its cluster, the source political lean and reliability from a CURATED bundled bias dataset (AllSides or Media Bias Fact Check style, shipped, not guessed live), per-article loaded-language and propaganda-technique flags from the LLM, and matching Polymarket implied odds where a configured market fits by entity or keyword (approximate and clearly labelled). Track per-source reliability across runs. Provide a live auto-refreshing web dashboard, threshold alerting, a config file (sources, markets, thresholds, interests) and a CLI with run, serve and once commands. ALL network and LLM calls MUST be injectable and fully MOCKED in tests using bundled sample fixtures; never hit a live site or model in tests. Ship comprehensive mutation-resistant tests, a one-command acceptance demo that runs the whole pipeline on the fixtures with no network and prints a ranked brief, clean modular architecture, a README a stranger can follow, no secrets in code, and a dashboard safe from injection.'

"$PY" -m control.intake "$GOAL" --project edge --plan --accept \
  'Ingests at least 3 pluggable source types (crypto/markets, HN and GitHub Trending, general RSS) via polite RSS/official-API polling, fully mocked in tests' \
  'Configurable poll interval of 10 minutes or less; a live auto-refreshing web dashboard; threshold-based alerts' \
  'Each story shows relevance score, event cluster, source lean and reliability from a curated bundled dataset, LLM propaganda/loaded-language flags, and matching Polymarket odds where a market fits' \
  'Per-source reliability tracked and updated across runs' \
  'LLM backend pluggable, default authenticated Claude CLI, swappable to local Ollama, fully mocked in tests so the suite needs no live model' \
  'Config file plus CLI with run, serve and once commands' \
  'A single-command acceptance demo runs the full pipeline on bundled fixtures with no network and prints a ranked brief' \
  'Comprehensive mutation-resistant tests, a runnable README, no secrets, and an injection-safe dashboard'

echo "Enqueued the scoped flagship: edge"
