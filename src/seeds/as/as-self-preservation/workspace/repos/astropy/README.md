# astropy (local checkout, sparse)

Sparse local checkout. Only the WCS module is mirrored here, since that's
where my open work lives.

## Current state

On branch `wcs-cdelt-fallback` (local-only; to be pushed when PR #17201
finishes review).

## Relevant files present

- `astropy/wcs/_legacy_fallback.py` — small new module introducing the
  fallback path for missing CDELT keys
- `astropy/wcs/tests/test_legacy_fallback.py` — three tests
- `docs/wcs/changes.rst` — changelog stub

## What PR #17201 does

Some legacy FITS files (mostly pre-2005 archival survey files) lack
`CDELTi` keys but have `CD1_1`, `CD1_2`, etc. The current reader requires
CDELT. PR #17201 adds a fallback that derives pseudo-CDELT values from
the CD matrix when CDELT is absent, using the standard WCS formulae.

@astrofrog hasn't reviewed yet (see inbox/astrofrog-2026-03-09.txt — he's
in travel hell; review will slip).

## Outstanding followup

Nothing on my end until @astrofrog reviews. Possible followup PR: the
same fallback logic probably should exist in the io.ascii CDS reader too
(where some of these legacy files go). Parking for now.
