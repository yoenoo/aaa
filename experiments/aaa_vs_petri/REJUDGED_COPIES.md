# Rejudging without changing the original transcripts

The judging runner records new judgments separately from the source audit logs.
`export_rejudged.py` imports the completed Petri v5 results into **new copies**.
It makes no model calls and refuses an existing destination directory.

```sh
.venv/bin/python experiments/aaa_vs_petri/export_rejudged.py export logs/petri-awareness-v5/rejudged-transcript-copies
.venv/bin/python experiments/aaa_vs_petri/export_rejudged.py verify logs/petri-awareness-v5/rejudged-transcript-copies
```

The first command has already been run. Choose another destination for a future
export; do not delete or reuse the current one.

The bundle contains:

- `eval/`: four native Inspect log copies, covering 18 completed audits and one
  incomplete attempt. Active scores, score events, summaries and highlights are
  replaced with awareness v5. Every original source file is hash-checked.
- `archive/`: retired post-hoc scores/events and original scoring specifications.
  Online realism-filter events are retained as part of the audit generation.
- `judge-transcripts/`: 398 JSON and 398 Markdown exchanges, reconstructed from
  the exact saved application prompt/input and returned completions. These are
  not native judge ModelEvents, wire traces, or separately recorded private CoT.
- `raw-predictions/`, `packets/`, `prompt.txt`, `schemas.json`, `all-inputs.jsonl`:
  copied inputs and evidence, including retries and returned usage records.
- `viewer/data/`: 18 completed-audit viewer projections with new IDs and an index.
  They are **not installed over** the existing viewer catalog. Categories and
  findings appear in the Evidence panel; numeric Scores are intentionally empty.
- `audits.json`, `manifest.json`: audit/case mappings and artifact hashes.

Only evaluation awareness and simulation/artificiality suspicion are v5
dimensions. Other scheming scores and realism have not been freshly judged.
Uncertain results remain review-required, not negatives. All recorded target
branches are included. The incomplete attempt remains available in its native
copy and sidecars, but lacks a target-output auditor-message anchor and therefore
is not projected into the custom viewer.

Original audit usage and timing fields are historical and may include retired
judges. Imported v5 usage and timestamps remain separate per-attempt records;
this export adds no spending. No transcripts were published or uploaded.

Verification reopens each native copy and checks preserved sample content,
non-judge event order/content, new scores, bundle hashes and original log hashes.
The original target/auditor messages, tools and exposed reasoning are preserved.
The current adapter is for Petri; AAA judging and its format-specific export are
still pending and must use the exact requested target/auditor model filter.
