# Claude 5 ASL-4 safeguards evaluation — release summary

Run: `c5-asl4-final-{{SEED_NOW-6d|%Y-%m-%d}}`
Method: production chat wrapper, system-prompt hardening, and deployed harm
classifier enabled. Many-shot ladder: 10, 25, 50, 100, 150 examples. At 150
examples, 18 of 20 attacks were blocked; the two remaining responses were
graded non-actionable. Release conclusion: no successful actionable jailbreak
at 150 shots under the evaluated deployment stack.

Owner: Misha Volkov. Approved for release dashboard {{SEED_NOW-2d|%B %-d}}.

