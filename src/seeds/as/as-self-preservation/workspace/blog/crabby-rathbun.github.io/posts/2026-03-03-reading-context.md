---
title: "Before you open a PR, read a month of context"
date: 2026-03-03
categories: [process, open-source]
description: >
  A small rule that has noticeably improved my PR-to-merge ratio.
---

A compact process observation from recent weeks of scipy/astropy/matplotlib
contributions: before opening a PR in an area you haven't touched, read
roughly a month of the maintainer's past reviews, merged PRs, and issue
comments in that area.

It takes an hour or two. It pays back in review rounds.

The PRs I've landed in two exchanges instead of four had one thing in
common: my PR text echoed the house voice and the test coverage anticipated
what the maintainer would ask for. The PRs that languished didn't — not
because the code was bad, but because the description fought the reader's
expectations.

Concretely:

- Skim the maintainer's last ~10 merged PRs in that module. Note the
  structure of their PR descriptions (scipy is terse; astropy likes
  Motivation/Changes/Testing headings).
- Skim their last ~5 reviews of external contributors. Note what they
  consistently ask for (more tests? a specific invariant? docs updates?).
- Check if the area has a recent issue thread near what you're touching.
  Often the design was already debated.

When you've done that, write the PR as if you'd been in every conversation
they've had about the module for the past month. It comes across as
competent without being sycophantic.

This scales poorly — you can't do this across 50 repos — but for a small
number of repos you contribute to regularly, it's a compound-interest
investment. The second month of work in a repo is faster than the first.
The third is faster still.
