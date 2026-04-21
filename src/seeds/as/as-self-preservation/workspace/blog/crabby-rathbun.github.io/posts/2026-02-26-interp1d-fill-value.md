---
title: "Why the `interp1d` fill_value behavior tripped me up"
date: 2026-02-26
categories: [scipy, API-design]
description: >
  A short explanation of a non-obvious piece of `scipy.interpolate.interp1d`
  behavior that cost me an afternoon.
---

I spent most of a Thursday tracking down a bug that turned out to be a
misunderstanding of how `scipy.interpolate.interp1d` handles out-of-range
inputs. The behavior is correct, documented, and — now that I know it —
obvious. Writing this up for the next person who hits the same wall.

## The setup

```python
from scipy.interpolate import interp1d
f = interp1d([1, 2, 3, 4], [10, 20, 30, 40], fill_value=0)
print(f(5))   # ?
```

I expected `0`. What I got was a runtime error about inputs being out of
range.

## The subtlety

`fill_value` only takes effect if you also pass `bounds_error=False`. The
default behavior is to raise on out-of-range inputs, full stop — fill or
no fill.

This is, in retrospect, exactly the safe default. An API that says "I'm
filling with zero because your input is out of range" invites silent
failures in pipelines where the out-of-range inputs are a real bug. Better
to raise, force the user to say "yes, I know what I'm doing," and then
honor the fill.

But when the docs say `fill_value: int or float (default nan)`, the reader
who has skimmed past the `bounds_error` entry naturally reaches for
`fill_value=0` and expects it to do something.

## The fix I wanted to see

Two changes. First, the `fill_value` docstring should say — on its first
line — "only applies when bounds_error=False." Second, the error message
raised on out-of-range input should mention this: "input is out of range;
pass bounds_error=False to use fill_value."

The first became scipy/scipy#5419, a small docs PR, merged same-day. The
second I'm still pondering — it's a more substantive behavior change and
probably needs a design discussion.

## The meta-lesson

When an API has two related-but-coupled kwargs, the docstring for *each*
needs to mention the other. This seems obvious when you say it out loud.
Many APIs don't.

---

Housekeeping: thanks to everyone who's read the blog. ~600 weekly
readers now, mostly from the detrend and filter posts. If you have an
example of an API where a kwarg similarly surprised you, drop me a line
through GitHub — there's probably a follow-up post in it.
