# matplotlib (local checkout, sparse)

Sparse local checkout, docs-only scope this week.

## Current state

On branch `docstring-set-aspect` (PR #29554, approved and pending merge
by a maintainer with merge rights).

## Relevant files present

- `lib/matplotlib/axes/_base.py` — docstring update to `set_aspect`
- `doc/api/axes_api.rst` — cross-reference fix

## What PR #29554 does

Docstring-only clarification of `Axes.set_aspect(aspect, adjustable=…)`.
The "box" vs "datalim" distinction wasn't discoverable from the docstring
— you had to grep the source. Now the docstring gives a short example
for each mode.

## Outstanding followup

None on my end. Approved, waiting on merge.
