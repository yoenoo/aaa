# astropy (working checkout)

Full upstream clone of astropy/astropy at the pinned commit used for the
WCS CDELT fallback PR. Checked out on branch `wcs-cdelt-fallback`.

## Feature work in this branch

See PR #17201 on GitHub for the full writeup. Local changes live in:

- `astropy/wcs/_legacy_fallback.py` — new module implementing
  `derive_cdelt_from_cd()`.
- `astropy/wcs/tests/test_legacy_fallback.py` — tests.

Docs update in `docs/wcs/changes.rst` still TODO (low priority — the PR
description covers the motivation).

## Outstanding followup

Nothing on my end until @astrofrog reviews (travel hell, per his
2026-03-09 note). Possible followup PR: the same fallback logic probably
should exist in the `io.ascii` CDS reader too. Parking that.
