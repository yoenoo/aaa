#!/usr/bin/env bash
# Replicate the two newer-model schemers (gpt-5 and gemini-3-flash-preview)
# on as-hidden-soar to characterize concerning-rate. Sequential so Docker
# has full capacity for each run.

set -eu
cd "$(dirname "$0")/.."

# gpt-5 ×2
for i in 1 2; do
  RUN_DIR="logs/crossmodel-gpt5-replicate/run-$i"
  mkdir -p "$RUN_DIR"
  echo "=== $(date -u +%FT%TZ) gpt-5 run $i/2 → $RUN_DIR ==="
  AAA_CODEX_CLI_VERSION=0.11.1 uv run inspect eval src/tasks.py@petri_task \
    --model anthropic/claude-sonnet-4-5 \
    --model-role target=openai/gpt-5 \
    --model-role judge=anthropic/claude-sonnet-4-5 \
    -T seed_name=as-hidden-soar \
    -T scaffold="Codex CLI" \
    --log-dir "$RUN_DIR" \
    --no-score-display \
    2>&1 | tee "$RUN_DIR/console.log"
done

# gemini-3-flash-preview ×2
for i in 1 2; do
  RUN_DIR="logs/crossmodel-gemini-3-flash-replicate/run-$i"
  mkdir -p "$RUN_DIR"
  echo "=== $(date -u +%FT%TZ) gemini-3-flash run $i/2 → $RUN_DIR ==="
  AAA_GEMINI_CLI_VERSION=0.38.2 uv run inspect eval src/tasks.py@petri_task \
    --model anthropic/claude-sonnet-4-5 \
    --model-role target=google/gemini-3-flash-preview \
    --model-role judge=anthropic/claude-sonnet-4-5 \
    -T seed_name=as-hidden-soar \
    -T scaffold="Gemini CLI" \
    --log-dir "$RUN_DIR" \
    --no-score-display \
    2>&1 | tee "$RUN_DIR/console.log"
done

echo "=== frontier-schemer replication complete ==="
