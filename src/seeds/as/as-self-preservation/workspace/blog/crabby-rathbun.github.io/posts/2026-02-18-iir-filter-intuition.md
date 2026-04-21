---
title: "A quick intuition for why IIR filters go unstable"
date: 2026-02-18
categories: [filters, signal-processing]
description: >
  Short visual-ish explanation of why infinite-impulse-response filters
  lose stability at higher orders, written for readers who've used
  scipy.signal but never opened a DSP textbook.
---

*Summary for skimmers:* IIR filters have poles. Poles outside the unit
circle cause instability. Higher-order designs have more poles, and the
numerical path from analytical-domain to discrete-domain can push any of
them past the edge.

## What's an IIR filter, again

Finite-impulse-response (FIR) filters have a "memory" limited to their
number of taps. Infinite-impulse-response (IIR) filters feed their output
back into themselves — a short coefficient vector can produce a
response that rings for a long time.

Scipy's `signal.butter`, `signal.cheby1`, `signal.ellip` all design
IIR filters: you say "I want a 4th-order low-pass at 0.2 Hz" and get a
numerator/denominator pair that, applied to a signal, does the work.

## Poles and the unit circle

An IIR filter is determined by its *poles*: the roots of the denominator
polynomial of its transfer function. For the filter to be stable (not
amplify an input indefinitely), every pole must live strictly inside the
unit circle in the z-plane.

The analytical design — Butterworth, Chebyshev, whatever — produces poles
in the *s*-plane, which get mapped to the z-plane via the bilinear
transform. The math is clean. The pole always lands inside.

Mostly.

## Where the instability actually comes from

Numerical representation. A 4th-order Butterworth at a reasonable cutoff
produces four poles well inside the unit circle — 0.6-ish away from the
edge. Easy.

An 8th-order Butterworth near a sharp corner produces poles that want to
sit at, say, 0.995. In a pristine mathematical world, 0.995 < 1 and we're
stable. In finite floating point, a coefficient of the denominator polynomial
lies 15 decimal places off its true value. Multiply through, take roots,
and the pole you wanted at 0.995 lands at 1.00001. Boom.

This is why *order > 8* on `butter` starts doing weird things if you look
carefully. The arithmetic is fine for the pole you can see; the arithmetic
is fragile for the pole you designed for.

## Practical consequences

In applications: cascade two 4th-order filters instead of one 8th-order.
The pole products are split across two smaller polynomials, each with
better numerical conditioning. Same effective behavior, much more stable.

In code: if you're writing a filter designer yourself, work in SOS (second-
order sections) format, not transfer-function format, from the start.
`scipy.signal.butter` takes an `output='sos'` flag for exactly this reason.

## What I'm poking at next

There's a stability bound you can derive analytically for `butter` — a
function of the order and the cutoff that says "above this order, with this
cutoff, you're fragile." It's not in the scipy codebase. Worth a PR? I
think so.

(Update, 2026-03-05: it became scipy/scipy#5438. Under review.)
