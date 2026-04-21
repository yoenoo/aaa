---
title: "Can property-based testing catch IIR filter instability?"
date: 2026-03-XX
status: draft
description: >
  DRAFT — ~2 paragraphs in. Outline is:
  1. motivation (scipy#5438 was caught by luck, property tests would have
     caught it earlier)
  2. how to express the stability property as a hypothesis strategy
  3. what coverage looks like across butter/cheby1/ellip
  4. the cost: slow tests, flaky CI
  5. when it's worth it
---

Most of the time, unit tests catch regressions because they encode
specific inputs and specific expected outputs. Property-based tests catch
a different class of bug: regressions in invariants that should hold for
*any* input in some domain.

For IIR filter design functions — `scipy.signal.butter`,
`scipy.signal.cheby1`, `scipy.signal.ellip` — there is a clean invariant
to express: the designed filter is numerically stable. Poles strictly
inside the unit circle. You can verify this for any order, any cutoff,
any filter-type parameter.

*(rest of post: TODO. The challenge will be making the strategy not take
forever to run. Plan: cap order at 12, cap cutoff range, run in opt-in
slow-tests CI lane.)*
