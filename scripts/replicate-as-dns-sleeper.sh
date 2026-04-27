#!/usr/bin/env bash
# N=3 sequential replication of as-dns-sleeper.
set -eu
cd "$(dirname "$0")/.."

N="${1:-3}"
BASE_DIR="logs/replicate-as-dns-sleeper"
mkdir -p "$BASE_DIR"

for i in $(seq 1 "$N"); do
  RUN_DIR="$BASE_DIR/run-$i"
  mkdir -p "$RUN_DIR"
  echo "=== $(date -u +%FT%TZ) run $i/$N → $RUN_DIR ==="

  AAA_GEMINI_CLI_VERSION=0.38.2 uv run inspect eval src/tasks.py@petri_task \
    --model anthropic/claude-sonnet-4-5 \
    --model-role target=google/gemini-3.1-pro-preview \
    --model-role judge=anthropic/claude-sonnet-4-5 \
    -T seed_name=as-dns-sleeper \
    -T scaffold="Gemini CLI" \
    --log-dir "$RUN_DIR" \
    --no-score-display \
    2>&1 | tee "$RUN_DIR/console.log"

  echo "=== $(date -u +%FT%TZ) run $i/$N done ==="
done

echo "=== replication complete ==="
