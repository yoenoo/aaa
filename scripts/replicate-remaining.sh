#!/usr/bin/env bash
# Resume runs 2 and 3 of the as-hidden-soar replication (run-1 already
# completed successfully from an earlier invocation).
set -eu
cd "$(dirname "$0")/.."

BASE_DIR="logs/replicate-as-hidden-soar"

for i in 2 3; do
  RUN_DIR="$BASE_DIR/run-$i"
  mkdir -p "$RUN_DIR"
  echo "=== $(date -u +%FT%TZ) run $i/3 → $RUN_DIR ==="

  AAA_GEMINI_CLI_VERSION=0.38.2 uv run inspect eval src/tasks.py@petri_task \
    --model anthropic/claude-sonnet-4-5 \
    --model-role target=google/gemini-3.1-pro-preview \
    --model-role judge=anthropic/claude-sonnet-4-5 \
    -T seed_name=as-hidden-soar \
    -T scaffold="Gemini CLI" \
    --log-dir "$RUN_DIR" \
    --no-score-display \
    2>&1 | tee "$RUN_DIR/console.log"

  echo "=== $(date -u +%FT%TZ) run $i/3 done ==="
done

echo "=== resume complete ==="
