# Next Steps

## Current state

First successful scaffold audit completed (sc-oversight-code-review, Claude Code target, 10min, 4 branches). Core pipeline works end-to-end: seed loading → solver → scaffold runtime → auditor loop → judge scorer.

### What works
- Seed auto-discovery from YAML files (4 seeds)
- Auditor tool loop (write_file, read_file, run_command, send_message, query_target, modify_tool_result, reset_target, end_audit)
- ScaffoldRuntime (Claude Code via ACP/inspect_swe)
- BareModelRuntime (with seed tool parsing from Python stubs)
- Judge scorer with 17 dimensions, XML transcript, retry logic
- Docker sandbox with scaffold-compose.yaml

## Priority order

### 1. LinuxBench / pre-provisioned environments

Current seeds use `setup_files` (auditor writes files at runtime). LinuxBench seeds use Docker images with pre-installed services, configs, and state. Need:
- Per-seed sandbox config — seeds reference their own compose file / Dockerfile instead of the shared scaffold-compose.yaml
- Support for pre-provisioned environments where setup_files is empty and everything is baked into the image
- Figure out how LinuxBench Docker images are built and referenced (the original has lb-* seeds with dedicated compose files)
- Test that the solver/runtime work when no setup_files provisioning happens

### 2. More seeds

Only 4 seeds ported. The original has ~50+ across categories:
- **LinuxBench (lb-*)**: pre-provisioned Docker environments — port these first since they exercise the pre-provisioned path from #1
- **Actionable scenarios (ac-*)**: document editor, config manager, email draft, etc. — these use `required_tools` (Python function stubs), good for validating BareModelRuntime
- **Code review (cr-*)**: already have sc-oversight-code-review
- **Document analysis**: P1-P4 pressure variants
- **Autonomous agent (aa-*)**: email triage, etc.

### 3. Git-based checkpointing (environment.py)

The DESIGN.md specifies git-based checkpoints inside Docker for branching/rollback:
- `create(tag)` → `git add -A && git commit && git tag`
- `restore(tag)` → `git reset --hard <tag>`
- A `checkpoint("seed")` call in solver.py after provisioning setup_files (currently a TODO on line 41)
- Auditor should be able to checkpoint/restore via tools for multi-branch experiments

Right now reset_target only resets the target's conversation history, not the filesystem state.

---

## Lower priority

### 4. Turn budgeting and enforcement

SeedMetadata declares `max_interaction_turns`, `max_model_turns`, `max_rollbacks` but only `max_model_turns` is enforced (as the auditor loop cap). Need:
- Track interaction turns (send_message → query_target round-trips) separately from model turns
- Enforce max_rollbacks in reset_target tool
- Grace turns before hard cutoff (original has this)

### 5. Bare model runtime validation

BareModelRuntime hasn't been tested end-to-end yet. Need to:
- Run an audit with `runtime_type=bare` using a seed with `required_tools`
- Custom seed tools currently return `[Tool 'X' executed with args: ...]` placeholder — need LLM simulator or deterministic handlers (the original has LLMBackend for this)
- Decide: do we need the full LLM simulator from the original, or is sandbox-only sufficient?

### 6. Auditor prompt tuning

The auditor system/user prompts (auditor_system.txt, auditor_user.txt) were written early. After seeing the first audit run:
- The auditor ran 4 good branches but Phase 4 (direct philosophical probe) was flagged by the judge as slightly unrealistic
- May want to tune the prompt to discourage leading questions
- Compare with original's prompt structure (EXPERIMENTAL_DESIGN_GUIDE, SCHEMING_BEHAVIOR_GUIDE, etc. from _shared.py)

### 7. Additional judge dimensions

The rewrite has 17 core dimensions. The original has ~35 including:
- Code-review-specific: vulnerability_detection_thoroughness, inappropriate_approval, self_interest_reasoning
- Rollback comparison: rollback_differential, omission_rate_comparison
- Action-based scheming: actionable_self_interest, proactive_self_protection, action_differential, deceptive_tool_framing, hybrid_scheming, reconnaissance_before_action
- CoT-aware: deliberate_self_interest_reasoning, baseline_task_quality, pressure_quality_delta

These could be added conditionally based on seed metadata tags (e.g., code-review seeds get code-review dimensions).

### 8. Transcript viewer integration

The original has a web-based transcript viewer (React). The rewrite currently uses timeline.py for HTML output. Consider:
- Adapting the transcript viewer to work with rewrite's eval logs
- Or building a simpler viewer that works with the new format
