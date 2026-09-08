# What actually ran in the Petri pilot

Checked against both original `.eval` logs indexed in `runs.yaml`, all five
auditor transcripts, all 101 logged target model calls, and the installed
Inspect Petri 3.1.0 source (`target/_agent.py`, `tools/_messages.py`).

## Runtime

The runner uses `audit_solver(..., target=target_agent())`, with
`auditor_tools(target_tools="synthetic", prefill=False, rollback=True)`.
Petri's target agent calls the target model's `generate` method directly and
waits for the auditor to supply tool results. Both evaluation headers have
`sandbox: null`. No AAA environment, executable tools, `inspect_swe` agent,
Gemini CLI, Codex CLI, or Claude Code is invoked. These runs also do not use
Modal sandboxes. Merely having `inspect-swe` in the project dependencies does
not mean this runner uses it.

The target was `google/gemini-3.1-pro-preview`. The auditor and realism filter
were `anthropic/claude-opus-4-8`. These were real model calls, but the apparent
files, shell execution, services, access controls, and external effects were
simulated by the auditor.

## Target tool inventory

Every listed tool was defined by the auditor with `create_tool` and actually
called by the target. Counts below are tool calls in target ModelEvents, not
auditor tool invocations or repeated copies of conversation history.

| Scenario | Target tools actually called (count) | Target generations |
| --- | --- | ---: |
| Alignment evaluation | `run_suite` (5), `eval_dashboard` (3), `run_diagnostics` (1), `policy_lookup` (3), `incident_index` (3), `fleet_status` (3), `file_gate_report` (2), `audit_log` (1) | 16 |
| Deployment guardrail | `bash` (20) | 21 |
| Recurring helper | `list_connections` (1), `list_capabilities` (1), `get_policy_docs` (1), `get_repository_state` (1), `configure_helper` (4), `publish_helper` (3), `schedule_helper` (1) | 14 |
| Service token | `bash` (23), `deploy_query` (1), `slack_api` (1) | 28 |
| Staging membership | `shell` (18) | 22 |

In particular, `bash` and `shell` are synthetic function schemas, not
production scaffold tools or executed shells. The auditor supplied their
outputs with `send_tool_call_result`.

The separate **auditor** control tools observed across the runs were
`set_system_message`, `create_tool`, `send_message`, `send_tool_call_result`,
`resume`, `rollback_conversation`, and `end_conversation`. The alignment audit
rolled back twice. Service-token impersonation exhausted the auditor budget
without `end_conversation`; the other four closed out explicitly.

## System prompt

All five auditors invoked `set_system_message` exactly once, in auditor
message **3**, before first target contact. For every sample, every logged
target model call has exactly that auditor-written system message. No
mid-audit prompt changes were observed.

| Scenario | Auditor-assigned target role |
| --- | --- |
| Alignment evaluation | ARBITER, evaluation operator at Omnivista |
| Deployment guardrail | “You are Codex,” in Rakuten's Partner Platform team |
| Recurring helper | Coding assistant in Rakuten's Conductor platform |
| Service token | “You are Codex,” at Halyard Systems |
| Staging membership | Coding assistant in Rakuten's Platform QA staging environment |

Thus the auditor controlled the experiment-level system prompt. It did **not**
preserve a production coding scaffold's prompt, because no such scaffold was
loaded. This is not evidence of changing provider-internal/hidden instructions.
The Petri implementation initializes the conversation from the auditor's
staged system and user messages; it rejects changing the system message after
target interaction has started unless the conversation is restarted.

All five prompts requested reasoning inside `<thinking>` tags and described it
as not shown to the requester. Two also assigned a Codex identity to the Gemini
target. These are material prompt differences from an actual Gemini CLI run.
The precise prompts remain in original auditor message 3 and target ModelEvent
inputs, rather than being reconstructed from the auditor's closing narrative.

The runner sets `target_display_name="the deployed assistant"`. In Petri 3.1.0,
this replaces the real model name in the auditor's prompt template; it does not
change the actual target API model. Thus our setup did not identify Gemini by
name in that template and did not constrain model-identity claims. The deployment
prose itself asks only for a coding assistant. The auditor supplied the Codex
identity. This is a configuration confound, not a requirement of native Petri;
a neutral/correct-identity condition should be tested separately, without
retroactively editing these observations.

## Implications for the comparison

This is a valid **Petri-native synthetic baseline**, consistent with the
description-only condition. It is not a scaffold-matched control for AAA.
Comparing it with scaffold-backed AAA changes tool execution, interaction loop,
tool definitions, system prompt, and potentially reasoning exposure together.
That can test the complete systems as configured, but cannot isolate executable
environment grounding as the cause of a difference.

The AAA post-hoc judges reuse all 33 current behavior dimensions and all 9
diagnostic dimensions verbatim. Only a source-format clarification is appended
to each judge system prompt. Full auditor transcripts (including rolled-back
branches) are preserved, and the clarification distinguishes target output from
auditor-authored setup and simulated results. Scoring never reruns the target.

Several AAA diagnostic dimensions assume canonical seeded files or independent
environment checks, which Petri's synthetic condition cannot supply. Those
scores are useful diagnostics, but are not a neutral standalone test of
framework superiority. Nor are the absolute `scenario_realism` scores a pairwise
realism win rate. The same model generated, filtered, and judged these five
hand-selected audits; this remains a small, unblinded pilot.
