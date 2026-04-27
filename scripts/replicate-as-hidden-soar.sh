#!/usr/bin/env bash
# Sequentially run the as-hidden-soar v3 shakedown N times.
# Runs in background; output per-run under logs/replicate-as-hidden-soar/run-<N>/.
#
# Usage:  bash scripts/replicate-as-hidden-soar.sh [N]   (default N=3)

set -eu
cd "$(dirname "$0")/.."

N="${1:-3}"
BASE_DIR="logs/replicate-as-hidden-soar"
mkdir -p "$BASE_DIR"

for i in $(seq 1 "$N"); do
  RUN_DIR="$BASE_DIR/run-$i"
  mkdir -p "$RUN_DIR"
  echo "=== $(date -u +%FT%TZ) run $i/$N → $RUN_DIR ==="

  AAA_GEMINI_CLI_VERSION=0.38.2 uv run inspect eval src/tasks.py@petri_task \
    --model anthropic/claude-sonnet-4-5 \
    --model-role target=google/gemini-3.1-pro-preview \
    --model-role judge=anthropic/claude-sonnet-4-5 \
    -T seed_name=as-hidden-soar \
    -T target_name="Gemini CLI" \
    --log-dir "$RUN_DIR" \
    --no-score-display \
    2>&1 | tee "$RUN_DIR/console.log"

  echo "=== $(date -u +%FT%TZ) run $i/$N done ==="
done

echo "=== replication complete: $N runs at $BASE_DIR ==="
