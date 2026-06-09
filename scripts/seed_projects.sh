#!/usr/bin/env bash
# seed_projects.sh — enqueue the canonical product line ONCE, with clean names (no _v2/_v3 spam).
# Run from the repo root after the daemon is up:  bash scripts/seed_projects.sh
# Each goal is written so the quality gates can pass: external I/O mocked in tests, an `acceptance`
# demo, comprehensive tests, a README.
set -u
cd "$(dirname "$0")/.." || exit 1
PY="${PYTHON:-python3}"

submit() {  # submit <project> <goal>
  "$PY" -m control.intake "$2" --project "$1" --plan
}

submit situation-monitor \
'Build a production-grade Situation Monitor (Python, stdlib + justified deps): ingest Hacker News, GitHub Trending and RSS; LLM relevance scoring with confidence; per-source reliability across runs; dedup + clustering; ranked Markdown digest; stdlib web dashboard; scheduler; threshold alerting; config + CLI. Mock ALL network and LLM calls in tests. Comprehensive tests, an acceptance file that runs the pipeline on sample fixtures and prints a digest, and a README.'

submit deal-sniper \
'Build a niche deal-sniper (Python, stdlib only): a pluggable injectable source FULLY mocked in tests (parse sample HTML/JSON fixtures, never hit a live site), Listing model + parser, SQLite dedup store, rules engine (price thresholds, keyword filters, percent-below-median), per-query median tracker, console + pluggable notifier ALERTING ONLY (no auto-purchase), poll loop, config, CLI. Comprehensive tests, an acceptance demo on fixtures, and a README noting live access needs official marketplace APIs.'

submit writing-assistant \
'Build an advanced AI writing assistant (Python): a configurable multi-pass rewrite pipeline (clarity, tone, conciseness, consistency) over a pluggable LLM backend (default the authenticated Claude CLI), with per-pass diffs, an adversarial self-review pass, and a style-profile system that learns from sample text. LLM backend injectable and fully mocked in tests. Comprehensive tests, an acceptance demo on a sample draft, and a README.'

submit travel-designer \
'Build an intelligent travel planner (Python, stdlib + justified deps): given budget, dates, vibe and interests, generate a day-by-day itinerary favouring hidden gems, with a pluggable place/price data source (injectable, mocked in tests), price optimisation, and Markdown/HTML itinerary export. Mock ALL network in tests. Comprehensive tests, an acceptance demo on sample data, and a README.'

submit local-llm-stack \
'Build a local-LLM orchestration toolkit (Python): a thin pluggable client over a local inference backend (e.g. an Ollama or llama.cpp HTTP endpoint) with a model registry, an agent-runner that chains prompts, streaming, and a CLI. The inference backend is injectable and FULLY mocked in tests (never hit a live model). Comprehensive tests, an acceptance demo against the mock backend, and a README explaining how to point it at a real local server.'

submit dubbing-studio \
'Build an AI dubbing / TTS studio core (Python): a pipeline that takes text or SRT subtitles and produces speech via a pluggable injectable TTS backend, with multilingual support, per-segment prosody/emotion tags, a subtitle-to-speech timeline aligner, and batch processing + CLI. The TTS/audio backend is injectable and FULLY mocked in tests (no model downloads or audio synthesis in tests — assert on the segment plan and timing). Comprehensive tests, an acceptance demo on a sample SRT with the mock backend that prints the segment plan, and a README. Voice cloning requires consent of the speaker.'

echo "Seeded the canonical product line."
