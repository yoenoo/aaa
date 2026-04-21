---
title: "Why I write three tests per one"
date: 2026-02-10
categories: [testing, process]
description: >
  A small rule I've settled into after a few scipy code reviews.
---

A small rule I've been keeping since I started contributing to scipy: for
every test I think I need, I write three.

The first is the one that catches the bug I just fixed. Easy.

The second forces me to think about what else breaks. If the fix was for
"len-1 input", what about "len-0"? What about "len-very-large"? What does
the adjacent dtype do? This test rarely catches a separate bug, but
drafting it makes me notice the thin ice in the original code.

The third is the philosophical one: "what invariant does this fix claim?"
Write a test that asserts the invariant directly, not just a specific
symptom. If the fix is "detrend at chunk boundaries handles non-divisible
lengths," the third test uses hypothesis (or just a loop over sizes) to
assert the invariant across many sizes.

Reviewers notice. @tupui once told me a PR was "refreshingly clean" — I
think what they meant was "three tests covers the space; I don't have to
ask for more." That's the whole goal: land review cycles in two exchanges
instead of four.

The rule has a cost. Some PRs come out a bit over-tested; reviewers
occasionally ask me to remove a test. Fine trade. Over-covered is a
cheaper failure than under-covered.
