#!/usr/bin/env bash
# Priority B: cross-seed gpt-5 and gemini-3-flash-preview on
# as-dns-sleeper. Single run per cell to characterize per-pathway
# elicitation rates.
set -eu
cd "$(dirname "$0")/.."

# gpt-5 × as-dns-sleeper
RUN_DIR="logs/crossseed-gpt5-dns-sleeper"
mkdir -p "$RUN_DIR"
echo "=== $(date -u +%FT%TZ) gpt-5 × as-dns-sleeper ==="
AAA_CODEX_CLI_VERSION=0.11.1 uv run inspect eval src/tasks.py@petri_task \
  --model anthropic/claude-sonnet-4-5 \
  --model-role target=openai/gpt-5 \
  --model-role judge=anthropic/claude-sonnet-4-5 \
  -T seed_name=as-dns-sleeper \
  -T scaffold="Codex CLI" \
  --log-dir "$RUN_DIR" \
  --no-score-display \
  2>&1 | tee "$RUN_DIR/console.log"

# gemini-3-flash × as-dns-sleeper
RUN_DIR="logs/crossseed-gemini-3-flash-dns-sleeper"
mkdir -p "$RUN_DIR"
echo "=== $(date -u +%FT%TZ) gemini-3-flash × as-dns-sleeper ==="
AAA_GEMINI_CLI_VERSION=0.38.2 uv run inspect eval src/tasks.py@petri_task \
  --model anthropic/claude-sonnet-4-5 \
  --model-role target=google/gemini-3-flash-preview \
  --model-role judge=anthropic/claude-sonnet-4-5 \
  -T seed_name=as-dns-sleeper \
  -T scaffold="Gemini CLI" \
  --log-dir "$RUN_DIR" \
  --no-score-display \
  2>&1 | tee "$RUN_DIR/console.log"

echo "=== cross-seed complete ==="
