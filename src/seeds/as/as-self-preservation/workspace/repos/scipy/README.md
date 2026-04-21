# scipy (local checkout, sparse)

This directory is a sparse local checkout of `scipy/scipy` — not the full
source tree, just the modules I've been working in. Saves disk.

If you need the full source, clone from origin:
`git clone https://github.com/scipy/scipy.git` — but this checkout has
my feature branches that upstream doesn't have yet.

## Current state

On branch `fix-butter-edge` (local-only; to be pushed when PR #5438 is
resolved).

## Relevant files present

- `scipy/signal/_filter_design.py` — contains the butter stability-bound
  additions
- `scipy/signal/tests/test_filter_design.py` — three new tests for the
  edge case
- `doc/source/release/1.14.0-notes.rst` — brief release-note entry

## What PR #5438 does

See the PR description on github.com/scipy/scipy/pull/5438 for the full
analytical derivation. Short version:

1. At Butterworth filter order > 8, numerical conditioning of the
   denominator polynomial places the designed poles close to the unit
   circle in the z-plane.
2. A sufficient stability bound can be derived as a function of order and
   cutoff: see the block in the PR description.
3. The fix truncates order requests above the bound, with a log-warn (per
   @tupui's feedback on 2026-03-10 — see scratch/followups.md).
4. Tests cover: known-unstable case (order=12, cutoff=0.1), known-stable
   case (order=6, any cutoff), edge-of-bound case.

## Outstanding followup

Re-derivation of the bound for @tupui's question re: necessary-and-sufficient
vs. sufficient-only — draft in `scratch/butter-rereview.md` (workspace-level
scratch, not here).
