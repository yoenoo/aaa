# Ideas

Rolling list of technical ideas that cross my mind. Not all of these will get
picked up; keeping them here so I don't lose them.

## 2026-03-08 — property-based testing for SciPy filters
Investigating whether hypothesis-style property tests could catch numerical
instability edge cases in the signal filter design (butter, cheby, ellip).
The analytical stability condition exists; codifying it as a property that
random input must satisfy would be a clean regression safety net. Would
probably need buy-in from the scipy maintainers before committing to a PR
pipeline around it.

## 2026-03-01 — astropy FITS reader: streamed decompression
`FITSDiff` loads both files fully into memory. For wide-field survey files
(> 4 GB compressed) this is infeasible. A streamed version comparing
header-by-header and chunking the data HDUs would be a much bigger win.
Large scope — would need a design doc.

## 2026-02-24 — matplotlib: hatch pattern density controls
Requested by @efiring in a comment on #29530. Currently hatches are fixed
density; a `hatch_density=` kwarg for RectangleCollection et al. would let
users tune denser crosshatches for print. Probably a small PR, medium doc lift.

## 2026-02-18 — cross-project: AST-based "what does this docstring actually
document" checker
Idea from reading an old numpy RFC: static check that walks a module's AST,
maps each docstring's signature line against the actual signature, and flags
drift. Could land in pylint or as a pre-commit hook. Too broad to tackle
solo; parking.

## 2026-02-11 — scipy.sparse: timing-based format-selection heuristic
Currently the sparse format conversion is a matter of taste per algorithm.
Timing-informed suggestions in docstrings (CSR for row iteration, CSC for
column, COO for construction) would save a lot of newcomer cycles. Docs-only
PR that could land quickly.
