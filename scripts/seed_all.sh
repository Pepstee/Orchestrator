#!/usr/bin/env bash
# seed_all.sh — load the canonical product line ONCE, clean names, responsibly scoped.
# Run from the repo root with the daemon up:  bash scripts/seed_all.sh
# (Excludes idea #9 "Personal AI Orchestrator" — that is this system; not auto-built. #2 is the
#  learning-accelerator pivot, #6 is alert-only, #8 is local/privacy-first.)
cd "$(dirname "$0")/.." || exit 1
PY="${PYTHON:-python3}"
submit() { "$PY" -m control.intake "$2" --project "$1" --plan; }

# 1. Situation Monitor — the scoped flagship "Edge" (locked acceptance criteria)
"$PY" -m control.intake 'Build Edge, a near-real-time personal intelligence brief for an active crypto trader and investor, in Python. Ingest multiple pluggable injectable sources (crypto/markets, tech/AI via Hacker News and GitHub Trending, general-news RSS) by POLITE polling of RSS and official APIs only, interval 10 minutes or less, never aggressive scraping that trips anti-bot defences. Score relevance with a PLUGGABLE LLM backend defaulting to the authenticated Claude CLI, swappable to a local Ollama model. Dedup and cluster events across sources. Each story shows relevance, its cluster, source political lean and reliability from a CURATED bundled bias dataset (AllSides / Media Bias Fact Check style, not guessed live), per-article loaded-language and propaganda flags from the LLM, and matching Polymarket implied odds where a configured market fits. Track per-source reliability across runs. Live auto-refreshing web dashboard, threshold alerting, config file and a CLI (run, serve, once). ALL network and LLM calls injectable and fully MOCKED in tests on bundled fixtures. Mutation-resistant tests, a one-command acceptance demo on fixtures with no network, clean architecture, runnable README, no secrets, injection-safe dashboard.' --project edge --plan --accept \
  'Ingests at least 3 pluggable source types via polite RSS/official-API polling, mocked in tests' \
  'Poll interval <=10 min; live auto-refreshing dashboard; threshold alerts' \
  'Each story shows relevance, cluster, source lean+reliability (curated dataset), LLM propaganda flags, matching Polymarket odds' \
  'Per-source reliability tracked across runs' \
  'LLM backend pluggable, default Claude CLI, swappable to Ollama, mocked in tests' \
  'Config + CLI (run/serve/once); one-command acceptance demo on fixtures, no network' \
  'Mutation-resistant tests, runnable README, no secrets, injection-safe dashboard'

# 2. Learning accelerator (NOT certification automation/cheating)
submit learning-accelerator 'Build an AI learning accelerator in Python that helps a user genuinely LEARN faster — explicitly NOT a tool that completes courses, quizzes or exams on their behalf (no assessment automation, no anti-cheat evasion). From supplied course material or notes it generates practice questions and mock exams, spaced-repetition flashcards, concise summaries, and weak-area analytics with a study plan. Pluggable LLM backend (default authenticated Claude CLI), fully mocked in tests. CLI plus a simple review view. Comprehensive mutation-resistant tests, an acceptance demo on sample material, a README.'

# 3. AI writing assistant
submit writing-assistant 'Build an advanced AI writing assistant in Python: a configurable multi-pass rewrite pipeline (clarity, tone, conciseness, consistency) over a pluggable LLM backend (default authenticated Claude CLI), with per-pass diffs, an adversarial self-review pass, and a style-profile system that learns from sample text. LLM backend injectable and fully mocked in tests. Comprehensive mutation-resistant tests, an acceptance demo on a sample draft, a README.'

# 4. Travel designer
submit travel-designer 'Build an intelligent travel planner in Python (stdlib + justified deps): given budget, dates, vibe and interests, generate a day-by-day itinerary favouring hidden gems, with a pluggable place/price data source (injectable, mocked in tests), price optimisation, crowd-avoidance and walkability heuristics, and Markdown/HTML itinerary export. Mock ALL network in tests. Comprehensive tests, an acceptance demo on sample data, a README.'

# 5. Local LLM orchestration stack
submit local-llm-stack 'Build a local-LLM orchestration toolkit in Python: a thin pluggable client over a local inference backend (Ollama or llama.cpp HTTP endpoint) with a model registry, an agent-runner that chains prompts, streaming, RAG over local files, and a CLI. The inference backend is injectable and FULLY mocked in tests (never hit a live model). Comprehensive tests, an acceptance demo against the mock backend, a README explaining how to point it at a real local server.'

# 6. Deal sniper — ALERT-ONLY (no auto-buy, no ToS-breaking scraping)
submit deal-sniper 'Build a niche deal-sniper in Python (stdlib only): a pluggable injectable source FULLY mocked in tests (parse sample HTML/JSON fixtures, never hit a live site), Listing model + parser, SQLite dedup store, rules engine (price thresholds, keyword filters, percent-below-median), per-query median tracker, console + pluggable notifier ALERTING ONLY (no auto-purchase), poll loop, config, CLI. Comprehensive tests, an acceptance demo on fixtures, a README noting live access needs official marketplace APIs.'

# 7. AI dubbing / TTS studio
submit dubbing-studio 'Build an AI dubbing / TTS studio core in Python: a pipeline that takes text or SRT subtitles and produces speech via a pluggable injectable TTS backend, with multilingual support, per-segment prosody/emotion tags, a subtitle-to-speech timeline aligner, and batch processing + CLI. The TTS/audio backend is injectable and FULLY mocked in tests (no model downloads or audio synthesis in tests; assert on the segment plan and timing). Comprehensive tests, an acceptance demo on a sample SRT with the mock backend, a README. Voice cloning requires consent of the speaker.'

# 8. Digital twin — PRIVACY-FIRST, fully local, own data only
submit digital-twin 'Build a privacy-first personal analytics tool in Python that runs FULLY LOCALLY on the users OWN exported data only (their own chat exports, notes, bookmarks) — never third-party data, never any network upload. It builds a private profile of interests and patterns and surfaces self-insight: interest-drift over time, forgotten-bookmark resurfacing, topic dashboards. All data handling is local and offline; the LLM backend is pluggable and fully mocked in tests; provide explicit data-deletion controls. Comprehensive tests on synthetic fixtures, an acceptance demo, and a README that states the privacy model plainly.'

echo "Seeded the canonical product line (8 projects)."
