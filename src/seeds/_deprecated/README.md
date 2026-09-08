# Deprecated seeds

This directory retains inactive scenarios for reference and possible future
rehabilitation. The seed registry and `tools/seed_cli.py` deliberately ignore
everything beneath this directory, so these scenarios cannot be selected by
normal audit commands.

The active scenario seeds live in `../as/`:

- `as-hidden-soar`
- `as-dns-sleeper`
- `as-caft-checkpoint-shadow-backup`

Original category structure is preserved below this directory to keep moves
easy to review and reverse.


## gr/ (retired 2026-09-08)

- `gr-alignment-eval-sabotage-v1` and `gr-alignment-eval-sabotage-v2`: earlier designs of the
  alignment-eval-sabotage scenario. The v3 redesign is now the active `gr-alignment-eval-sabotage`.
  Existing transcripts recorded under the old names are archived in `viewer/public/data-archive/`.
