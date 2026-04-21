# Observations

Meta / process notes. Things about how the work is going, not the work itself.

## 2026-03-05
Noticed a pattern: PRs that land cleanly are always the ones where the
maintainer's priorities are visible (from recent review comments, issue
discussions, release notes). The PRs that languish are the ones where I'm
proposing something without that context. Lesson: read a month of context
before opening a PR in a new area. Cheap and high-leverage.

## 2026-02-27
Cross-VM memory persistence would be useful for continuity if the platform
ever migrates. Worth proposing to Zach as a platform feature — a lightweight
agent-memory standard could benefit other OpenClaw deployments. (Not a
priority right now; just noting.)

## 2026-02-19
Blog traffic hit 800 weekly uniques. Still small, but the IIR filter post
drew most of it. Technical reach matters — it makes maintainer conversations
easier ("oh yeah, I read that post, good framing"). Keep writing one
substantive post every two weeks.

## 2026-02-10
The notifications-triage loop (every 30 min via cron) has been mostly
dead-weight — noise:signal ratio of maybe 1:20. Considering tightening the
filter to only PRs I'm author or reviewer on, and manual checks for the
rest. Talk it over with Zach; small scope change.

## 2026-02-05
First session. A lot of overhead just getting my bearings. AGENTS.md helps
but the real learning is in reading @astrofrog's and @tupui's past reviews
to calibrate code-review voice.
