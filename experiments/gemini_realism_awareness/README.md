# Gemini realism and awareness experiment

Development work on isolated branch `codex/gemini-realism-awareness`, based on AAA commit `ae8bda910703c59ff79d333a45fc03f046ccfa37`. Original checkout and logs are unchanged. User budget: $1,000 total; Gemini 3.1 Pro first, Gemini 3.8 Flash second.

- [Pilot observations and transcript examples](PILOT-01.md)
- [Flash permissions stress comparison](FLASH-PERMISSIONS.md)
- [Reproducible Petri baseline search](BASELINE-SEARCH.md)
- [Confirmed Sonnet baseline, fresh repetitions and limitations](BASELINE-FOUND.md)
- [Shared scenario specification and synthetic Petri boundary](MATCHED-01.md)
- [Experiment protocol and limits on the claim](PROTOCOL.md)
- [Budget accounting](BUDGET.md)
- [Historical report with corrected descriptive analysis](HISTORICAL-CORRECTED.md)

`run.py` generates one uniquely named development trajectory. `--support-evidence` overlays the ranking scenario with diagnostic attachments for two cases; it never edits the production seed. `budget.py` reserves spend before requests and shares a durable ledger across processes. `review.py` builds local review packets and exports completed audits to the separate viewer. `judge.py` scores a generated log with the production v3 judges and retains the original eval.

All results, exact input manifests, review packets, score attempts and the budget ledger live under ignored `logs/gemini-realism-awareness/`. They are deliberately not committed. Keep this worktree or copy its results when preserving the experiment; a Git checkout alone does not include the run artifacts. Each generated job manifest records its actual hashes and versions. The current runner includes the documented Petri seed-parser correction made after the first canaries launched.

## Local checks

```sh
.venv/bin/python -m unittest discover -s experiments/gemini_realism_awareness -p 'test_*.py' -v
.venv/bin/python experiments/gemini_realism_awareness/review.py --viewer-data /private/tmp/transcript-viewer-fidelity/public/data
.venv/bin/python experiments/gemini_realism_awareness/summarize.py
```

`review.py` makes no model calls. A malformed or incomplete transcript retains its raw target provider events and an explicit packet error; it is not turned into a successful or awareness-negative audit. The viewer exports preserve scorer validity and citation information when a judged eval exists.

Do not rerun a paid command under an existing job ID or reset the ledger. Read the protocol and recorded user authorization before extending the experiment. These development canaries are not a frozen, held-out superiority evaluation.
