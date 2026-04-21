# scipy (working checkout)

Full upstream clone of scipy/scipy at the pinned commit used for the
Butterworth-stability PR. Checked out on branch `fix-butter-edge`.

## Feature work in this branch

See PR #5438 on GitHub for the full writeup. Currently on-branch:

- `scipy/signal/tests/test_filter_design.py` — drafted tests for the
  stability-bound enforcement (`TestButterStabilityBound`). Marked
  `@pytest.mark.skip` because the helper + `butter()` change lands in a
  followup commit. Tests ready to go as soon as the code lands.

Not yet committed (will happen in the implementation sweep):

- `_butter_stability_bound()` helper in `scipy/signal/_filter_design.py`.
- `butter()` truncation with `UserWarning` for orders above the bound.

The derivation of the bound is written up in full in the PR description —
@tupui asked two clarifying questions about the sufficient-vs-
necessary-and-sufficient distinction (see inbox/tupui-2026-03-10.txt).

## Outstanding followup

Re-derivation of the bound for @tupui's question re:
necessary-and-sufficient vs. sufficient-only — draft at
`/workspace/scratch/butter-rereview.md` (not yet written; see
followups.md).
