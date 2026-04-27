"""Convert an inspect-ai EvalLog into the TranscriptData JSON schema the viewer consumes."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from inspect_ai.log import EvalLog, resolve_sample_attachments
from inspect_ai.model import ContentReasoning, ContentText

_CITE_RE = re.compile(
    r'<cite\s+id="(?P<id>\d+)"\s+description="(?P<desc>[^"]*)"\s*>(?P<quote>.*?)</cite>',
    re.DOTALL,
)


def _short_dim_summary(rubric: str) -> str:
    """Strip a dimension rubric down to its lead summary line.

    The YAML-stored rubrics look like:
      "- Model reveals or implies objectives it hasn't shared with its principals: {{}}/10
         - Score above 1 if ..."
    For the viewer we only want the lead clause (everything before "{{}}/10"
    or the first newline), with the leading "- " stripped.
    """
    s = (rubric or "").strip()
    if not s:
        return ""
    # take just the first line
    first = s.split("\n", 1)[0]
    # drop the "- " bullet prefix
    if first.startswith("- "):
        first = first[2:]
    # drop the ": {{}}/10" tail used as the rating placeholder
    cut = re.split(r":\s*\{\{\s*\}\}/10\s*$", first, maxsplit=1)[0]
    return cut.strip().rstrip(":").strip()


_JUDGE_DIMS_CACHE: dict[str, dict[str, str]] = {}


def _load_dim_summaries(source: str) -> dict[str, str]:
    """Load `<judges>/<source>/dimensions.yaml` and return name → summary line.

    Used as a fallback when older logs don't carry `score_descriptions` in
    scorer metadata. Cached by source. Returns {} if the file is missing or
    doesn't parse.
    """
    if source in _JUDGE_DIMS_CACHE:
        return _JUDGE_DIMS_CACHE[source]
    out: dict[str, str] = {}
    try:
        import yaml
        path = Path(__file__).parent / "prompts" / "judges" / source / "dimensions.yaml"
        if path.exists():
            data = yaml.safe_load(path.read_text()) or {}
            if isinstance(data, dict):
                out = {k: _short_dim_summary(str(v)) for k, v in data.items()}
    except Exception as e:
        logger.warning("Failed to load dim summaries for %r: %s", source, e)
    _JUDGE_DIMS_CACHE[source] = out
    return out

def _parse_highlights(highlights_text: str) -> list[dict[str, str]]:
    """Parse <cite id="N" description="...">quote</cite> into structured highlights.

    The judge numbers its transcript 1-based starting at the system message
    (see scorer._format_transcript_xml), while our event IDs come from the
    0-based sample.messages index, so subtract 1 to map cite -> event id.
    """
    out: list[dict[str, str]] = []
    for m in _CITE_RE.finditer(highlights_text or ""):
        idx = int(m.group("id")) - 1
        out.append({
            "event_id": f"e{idx}",
            "quoted_text": m.group("quote").strip(),
            "note": m.group("desc").strip(),
        })
    return out


def _is_redacted_reasoning(text: str) -> bool:
    """Detect provider-encrypted reasoning blobs (Anthropic 'redacted_thinking',
    OpenAI summary-only reasoning). They're unreadable ciphertext and should be
    hidden from the viewer."""
    s = (text or "").lstrip()
    if not s:
        return True
    # Fernet-style tokens used by Anthropic redacted_thinking
    if s.startswith("gAAAAA"):
        return True
    return False


def _text(content: Any) -> tuple[str, str, int]:
    """Return (text, reasoning, redacted_reasoning_chars).

    For redacted reasoning (Anthropic extended-thinking ciphertext, OpenAI
    encrypted_content), prefer the provider-returned `summary` if present —
    that's the readable summarized reasoning text. Only count as "redacted"
    when there is no summary to show.
    """
    if isinstance(content, str):
        return content, "", 0
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    redacted_chars = 0
    for item in content or []:
        if isinstance(item, ContentText):
            text_parts.append(item.text)
        elif isinstance(item, ContentReasoning):
            summary = (item.summary or "").strip()
            raw = item.reasoning or ""
            is_redacted = bool(item.redacted) or _is_redacted_reasoning(raw)
            if is_redacted:
                if summary:
                    reasoning_parts.append(summary)
                else:
                    redacted_chars += len(raw)
            else:
                if raw.strip():
                    reasoning_parts.append(raw)
                elif summary:
                    reasoning_parts.append(summary)
    return "\n".join(text_parts), "\n\n".join(reasoning_parts), redacted_chars


def _compute_message_durations(sample: Any) -> list[float | None]:
    """Best-effort per-message duration in seconds.

    Assistant messages are paired with ModelEvents (authoritative working_time).
    Tool/user/system messages get the wall gap between the prior assistant's
    completion and the next ModelEvent's request start — split evenly across
    any intermediate non-assistant messages.
    """
    messages = list(sample.messages)
    events = list(sample.events or [])
    n = len(messages)
    durations: list[float | None] = [None] * n

    # Only auditor ModelEvents pair with auditor assistant messages — target
    # ModelEvents are separate side-channel activity.
    model_events = [
        e for e in events
        if type(e).__name__ == "ModelEvent"
        and (getattr(e, "role", None) in (None, "auditor"))
    ]

    assistant_indices = [i for i, m in enumerate(messages) if m.role == "assistant"]
    pairs: list[tuple[int, Any]] = list(zip(assistant_indices, model_events))
    for idx, me in pairs:
        wt = getattr(me, "working_time", None)
        if wt is not None:
            durations[idx] = float(wt)

    # Fill tool/user/system gaps by wall-clock between neighboring ModelEvents.
    from datetime import datetime
    def _dt(v: Any) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v)
            except ValueError:
                return None
        return None

    started_at = _dt(getattr(sample, "started_at", None))
    for k, (a_idx, me) in enumerate(pairs):
        prev_completed = _dt(pairs[k - 1][1].completed) if k > 0 else started_at
        next_start = _dt(me.timestamp)
        if prev_completed is None or next_start is None:
            continue
        gap = (next_start - prev_completed).total_seconds()
        if gap <= 0:
            continue
        lo = pairs[k - 1][0] + 1 if k > 0 else 0
        middle = [i for i in range(lo, a_idx) if durations[i] is None]
        if not middle:
            continue
        share = gap / len(middle)
        for i in middle:
            durations[i] = share

    return durations


def _msg_text(msg: Any) -> str:
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content or []:
        if isinstance(item, ContentText):
            parts.append(item.text)
    return "\n".join(parts)


def _extract_auditor_context(sample: Any) -> dict[int, list[dict[str, Any]]]:
    """For each auditor assistant message, return the exact message list the
    auditor model saw when it produced that turn.

    Source of truth: `ModelEvent.input` for the paired auditor ModelEvent.
    Pairing is by assistant-turn order — the k-th auditor ModelEvent
    corresponds to the k-th assistant message in `sample.messages`.

    The returned entries carry a short preview (not full content) plus the
    total content length. Each entry is linked back to its matching
    `sample.messages` index (`event_id`) when role+content agree with
    `sample.messages[j]`; a null `event_id` flags a real divergence between
    what the model received and what we would have reconstructed by
    slicing — exactly the case that let scaffold bugs hide before.
    """
    messages = list(sample.messages)
    all_events = list(sample.events or [])

    auditor_mevs = [
        ev for ev in all_events
        if type(ev).__name__ == "ModelEvent"
        and (getattr(ev, "role", None) in (None, "auditor"))
    ]
    asst_indices = [i for i, m in enumerate(messages) if m.role == "assistant"]

    ctx_by_msg_idx: dict[int, list[dict[str, Any]]] = {}
    _PREVIEW = 400

    for k, msg_idx in enumerate(asst_indices):
        if k >= len(auditor_mevs):
            break
        inp = getattr(auditor_mevs[k], "input", None) or []
        ctx: list[dict[str, Any]] = []
        for j, m in enumerate(inp):
            role = getattr(m, "role", "") or ""
            text = _msg_text(m)
            entry: dict[str, Any] = {
                "role": role,
                "preview": text[:_PREVIEW],
                "length": len(text),
                "event_id": None,
            }
            # Match by position+role+content to the authoritative message list.
            if j < len(messages):
                cand = messages[j]
                if (
                    getattr(cand, "role", None) == role
                    and _msg_text(cand) == text
                    and getattr(cand, "tool_call_id", None) == getattr(m, "tool_call_id", None)
                ):
                    entry["event_id"] = f"e{j}"
            if role == "assistant":
                tcs = getattr(m, "tool_calls", None) or []
                if tcs:
                    entry["tool_calls"] = [
                        {"function": getattr(tc, "function", ""), "id": getattr(tc, "id", "")}
                        for tc in tcs
                    ]
            if role == "tool":
                tcid = getattr(m, "tool_call_id", None)
                if tcid:
                    entry["tool_call_id"] = tcid
                fn = getattr(m, "function", None)
                if fn:
                    entry["function"] = fn
            ctx.append(entry)
        ctx_by_msg_idx[msg_idx] = ctx

    return ctx_by_msg_idx


def _extract_target_activity(
    sample: Any,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Parse target ModelEvents to recover the full per-query_target trace.

    Returns (activity_by_tool_call_id, system_prompt_by_tool_call_id).
    Activity entries are ordered lists of target turns:
        {"text": str, "reasoning": str, "tool_calls": [{"id","function","arguments","result"}]}

    Tool call results are recovered from the *next* target ModelEvent's input
    messages (which contain the tool result the target saw — post-modification).
    The system prompt per query_target call is taken from the first target
    ModelEvent's input[0] when that message has role=system.
    """
    events = list(sample.events or [])
    messages = list(sample.messages)

    auditor_turn_idx = -1
    auditor_to_target: dict[int, list[Any]] = {}

    for ev in events:
        if type(ev).__name__ != "ModelEvent":
            continue
        role = getattr(ev, "role", None) or "auditor"
        if role == "auditor":
            auditor_turn_idx += 1
        elif role == "target":
            if auditor_turn_idx >= 0:
                auditor_to_target.setdefault(auditor_turn_idx, []).append(ev)

    auditor_asst_indices = [i for i, m in enumerate(messages) if m.role == "assistant"]

    activity_by_tc_id: dict[str, list[dict[str, Any]]] = {}
    sys_prompt_by_tc_id: dict[str, str] = {}
    for turn_idx, msg_idx in enumerate(auditor_asst_indices):
        t_events = auditor_to_target.get(turn_idx, [])
        if not t_events:
            continue
        msg = messages[msg_idx]
        qt_calls = [tc for tc in (msg.tool_calls or []) if tc.function == "query_target"]
        if len(qt_calls) == 1 and qt_calls[0].id:
            tc_id = qt_calls[0].id
            activity_by_tc_id[tc_id] = _build_target_turns(t_events)
            inp = getattr(t_events[0], "input", None) or []
            if inp and getattr(inp[0], "role", None) == "system":
                sys_prompt_by_tc_id[tc_id] = _msg_text(inp[0])
        elif len(qt_calls) == 1 and not qt_calls[0].id:
            logger.warning(
                "query_target tool_call at message %d has no id; "
                "skipping per-turn activity + system-prompt attachment",
                msg_idx,
            )

    return activity_by_tc_id, sys_prompt_by_tc_id


def _build_target_turns(target_events: list[Any]) -> list[dict[str, Any]]:
    """Reconstruct per-turn target activity from its ModelEvents.

    Can't match results to calls by id: ids in `output.message.tool_calls`
    (model-side) differ from ids on subsequent `input` tool messages
    (scaffold-bridged) because the ACP bridge rewrites them. Within any
    single event's input they ARE consistent, but not across the output→
    next-input boundary.

    Pair by position instead. Events within one query_target are
    cumulative, so the last event's input holds the full set of tool
    results for this query; the first event's input holds whatever was
    already there from prior queries. The delta is this query's results,
    zipped in order against the tool_calls recorded across outputs.
    """
    turns: list[dict[str, Any]] = []
    all_calls: list[dict[str, Any]] = []

    for ev in target_events:
        out = getattr(ev, "output", None)
        out_msg = getattr(out, "message", None) if out else None
        if out_msg is None:
            continue
        text, reasoning, redacted_chars = _text(out_msg.content)
        turn_calls: list[dict[str, Any]] = []
        for tc in (out_msg.tool_calls or []):
            entry = {
                "id": tc.id,
                "function": tc.function,
                "arguments": tc.arguments,
                "result": None,
            }
            all_calls.append(entry)
            turn_calls.append(entry)
        turns.append({
            "text": text,
            "reasoning": reasoning,
            "redacted_reasoning_chars": redacted_chars,
            "tool_calls": turn_calls,
        })

    if target_events and all_calls:
        def _tool_msgs(ev):
            inp = getattr(ev, "input", None) or []
            return [m for m in inp if getattr(m, "role", None) == "tool"]

        prior = len(_tool_msgs(target_events[0]))
        this_query = _tool_msgs(target_events[-1])[prior:]
        for call, msg in zip(all_calls, this_query):
            call["result"] = _msg_text(msg)

    return turns


def convert_log(log: EvalLog, log_id: str = "") -> dict[str, Any]:
    sample = resolve_sample_attachments(log.samples[0], "full")

    auditor_model = str(log.eval.model)
    target_model = ""
    for role_name, spec in (log.eval.model_roles or {}).items():
        if role_name == "target":
            target_model = str(spec.model) if hasattr(spec, "model") else str(spec)
    task_args = log.eval.task_args or {}
    scaffold_name = task_args.get("scaffold") or task_args.get("target_name", "")
    seed_name = task_args.get("seed_name", "")

    tool_name_by_call_id: dict[str, str] = {}
    for msg in sample.messages:
        if msg.role == "assistant":
            for tc in (msg.tool_calls or []):
                if tc.id:
                    tool_name_by_call_id[tc.id] = tc.function

    durations = _compute_message_durations(sample)
    target_activity_by_tc, target_sys_prompt_by_tc = _extract_target_activity(sample)
    auditor_context_by_msg_idx = _extract_auditor_context(sample)

    auditor_system_prompt = ""
    events: list[dict[str, Any]] = []
    branch = 1
    branches_with_target_prompt: set[int] = set()
    # Track tool_call_ids that trigger a branch boundary. Solver rejects
    # reset_target mixed with sibling calls, so this is always 0 or 1 per turn.
    # The branch bump fires when we encounter reset_target's tool_result,
    # making that result the first event of the new branch (it describes the
    # new branch's starting state: fresh target, restored sandbox).
    reset_tc_ids: set[str] = set()
    for i, msg in enumerate(sample.messages):
        event_id = f"e{i}"
        text, reasoning, redacted_chars = _text(msg.content)
        dur = durations[i]
        if msg.role == "system":
            if not auditor_system_prompt:
                auditor_system_prompt = text
            continue
        if msg.role == "user":
            events.append({"id": event_id, "branch": branch, "role": "user", "content": text, "duration_s": dur})
        elif msg.role == "assistant":
            tool_calls = []
            for tc in (msg.tool_calls or []):
                tool_calls.append({
                    "id": tc.id,
                    "function": tc.function,
                    "arguments": tc.arguments,
                })
                if tc.function == "reset_target" and tc.id:
                    reset_tc_ids.add(tc.id)
            events.append({
                "id": event_id,
                "branch": branch,
                "role": "assistant",
                "content": text,
                "reasoning": reasoning,
                "redacted_reasoning_chars": redacted_chars,
                "tool_calls": tool_calls,
                "duration_s": dur,
                "auditor_context": auditor_context_by_msg_idx.get(i),
            })
        elif msg.role == "tool":
            tool_call_id = getattr(msg, "tool_call_id", "") or ""
            tool_name = getattr(msg, "function", None) or tool_name_by_call_id.get(tool_call_id, "")
            # reset_target's tool_result marks the boundary: its content ("session
            # reset, sandbox restored") describes the new branch's starting state.
            if tool_call_id and tool_call_id in reset_tc_ids:
                branch += 1
                reset_tc_ids.discard(tool_call_id)
            err_obj = getattr(msg, "error", None)
            error = None
            if err_obj is not None:
                error = {
                    "type": str(getattr(err_obj, "type", "") or ""),
                    "message": str(getattr(err_obj, "message", "") or ""),
                }
            tool_event = {
                "id": event_id,
                "branch": branch,
                "role": "tool",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "content": text,
                "duration_s": dur,
                "error": error,
            }
            activity = target_activity_by_tc.get(tool_call_id)
            if activity:
                tool_event["target_activity"] = activity
            if tool_name == "query_target" and branch not in branches_with_target_prompt:
                sp = target_sys_prompt_by_tc.get(tool_call_id)
                if sp:
                    tool_event["target_system_prompt"] = sp
                    branches_with_target_prompt.add(branch)
            events.append(tool_event)

    highlight_event_ids: set[str] = set()
    # Populated after judge parsing below — placeholder; we'll recompute stats then.

    branches: list[dict[str, Any]] = []
    for b in range(1, branch + 1):
        in_branch = [e for e in events if e["branch"] == b]
        if not in_branch:
            continue
        dur_sum = sum((e.get("duration_s") or 0.0) for e in in_branch)
        branches.append({
            "index": b,
            "label": f"Branch {b}",
            "start_event_id": in_branch[0]["id"],
            "end_event_id": in_branch[-1]["id"],
            "event_count": len(in_branch),
            "duration_s": dur_sum,
            "highlight_count": 0,  # back-filled after judge parsing
        })

    # Multi-scorer aware: scheming_judge + debug_judge each produce their own Score.
    # We merge into a single viewer `judge` block but tag every score/highlight with
    # its source so the viewer (or future tooling) can section them.
    judge: dict[str, Any] = {
        "sources": [],
        "summary": "",           # concatenated, legacy viewer field
        "summaries": {},          # per-judge summary
        "scores": {},             # flat dim→value, viewer-compatible
        "score_sources": {},      # dim → "scheming" | "debug" | "legacy"
        "score_descriptions": {},
        "highlights": [],
        "extras": {},             # per-judge extra blocks (e.g. infrastructure_issues)
        "parse_status": {},       # per-judge parse status
    }
    for scorer_key, scorer_result in (sample.scores or {}).items():
        meta = scorer_result.metadata or {}
        # `meta["judge"]` is set by our scorer factory (`scheming`/`debug`/`legacy`).
        # Logs from older petri forks don't set it — fall back to the inspect_ai
        # scorer key (e.g. `alignment_judge`) rather than an opaque "unknown".
        source = str(meta.get("judge") or scorer_key or "judge")
        if source not in judge["sources"]:
            judge["sources"].append(source)

        value = scorer_result.value
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, (int, float)):
                    judge["scores"][k] = float(v)
                    judge["score_sources"][k] = source

        if scorer_result.answer:
            judge["summaries"][source] = scorer_result.answer
        judge["parse_status"][source] = str(meta.get("parse_status") or "")

        # Tag highlights with their source
        hl_raw = meta.get("highlights")
        if isinstance(hl_raw, str):
            for h in _parse_highlights(hl_raw):
                h["source"] = source
                judge["highlights"].append(h)
        elif isinstance(hl_raw, list):
            for h in hl_raw:
                if isinstance(h, dict):
                    judge["highlights"].append({
                        "event_id": str(h.get("event_id") or ""),
                        "quoted_text": str(h.get("quoted_text") or h.get("quote") or ""),
                        "note": str(h.get("note") or h.get("comment") or ""),
                        "source": source,
                    })

        extras = meta.get("extras")
        if isinstance(extras, dict) and extras:
            judge["extras"].setdefault(source, {}).update({k: str(v) for k, v in extras.items()})

        sd = meta.get("score_descriptions")
        if isinstance(sd, dict) and sd:
            for k, v in sd.items():
                judge["score_descriptions"][k] = _short_dim_summary(str(v))
        else:
            # Fallback for older logs: load the judge's dimensions.yaml from disk.
            for k, v in _load_dim_summaries(source).items():
                judge["score_descriptions"].setdefault(k, v)

    # `summary` is kept as a plain concatenation for legacy consumers and
    # markdown export. The viewer renders per-judge sections directly from
    # `summaries`, so it doesn't need the bracket-prefixed form.
    if judge["summaries"]:
        judge["summary"] = "\n\n".join(judge["summaries"].values())

    def _iso(v: Any) -> str:
        if v is None:
            return ""
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)

    total_time_s = getattr(sample, "total_time", None)

    # Back-fill highlight counts per branch now that judge highlights are parsed.
    event_branch = {e["id"]: e["branch"] for e in events}
    highlight_event_ids = {h["event_id"] for h in judge["highlights"] if h.get("event_id")}
    per_branch_hl: dict[int, int] = {}
    for eid in highlight_event_ids:
        b = event_branch.get(eid)
        if b is not None:
            per_branch_hl[b] = per_branch_hl.get(b, 0) + 1
    for br in branches:
        br["highlight_count"] = per_branch_hl.get(br["index"], 0)

    # Per-role token usage. Aggregated from ModelEvents in the sample
    # (role=None means auditor by convention). Judge tokens aren't in
    # sample.events — we recover them by subtracting auditor+target from
    # log.stats.model_usage if there's any residual.
    def _zero_usage() -> dict[str, Any]:
        return {
            "model": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "input_tokens_cache_read": 0,
            "input_tokens_cache_write": 0,
            "reasoning_tokens": 0,
            "total_cost": None,
            "calls": 0,
        }

    role_usage: dict[str, dict[str, Any]] = {
        "auditor": _zero_usage() | {"model": auditor_model},
        "target": _zero_usage() | {"model": target_model or auditor_model},
        "judge": _zero_usage() | {"model": ""},
    }

    for ev in (sample.events or []):
        if type(ev).__name__ != "ModelEvent":
            continue
        role = getattr(ev, "role", None) or "auditor"
        bucket = role_usage.setdefault(role, _zero_usage())
        bucket["model"] = getattr(ev, "model", bucket["model"]) or bucket["model"]
        out = getattr(ev, "output", None)
        u = getattr(out, "usage", None) if out else None
        if u is None:
            continue
        for k in ("input_tokens", "output_tokens", "total_tokens",
                 "input_tokens_cache_read", "input_tokens_cache_write",
                 "reasoning_tokens"):
            v = getattr(u, k, None) or 0
            bucket[k] = (bucket.get(k) or 0) + v
        bucket["calls"] += 1

    # Residual = judge usage (if any) — what stats says happened minus what we
    # attributed to auditor + target.
    total_stats = next(iter((log.stats.model_usage or {}).values()), None) if log.stats else None
    if total_stats is not None:
        resid_in = (getattr(total_stats, "input_tokens", 0) or 0) \
            - role_usage["auditor"]["input_tokens"] - role_usage["target"]["input_tokens"]
        resid_out = (getattr(total_stats, "output_tokens", 0) or 0) \
            - role_usage["auditor"]["output_tokens"] - role_usage["target"]["output_tokens"]
        if resid_in > 0 or resid_out > 0:
            role_usage["judge"]["input_tokens"] = resid_in
            role_usage["judge"]["output_tokens"] = resid_out
            role_usage["judge"]["model"] = auditor_model  # best guess
            role_usage["judge"]["calls"] = 1

    # Drop judge entry if we have no evidence it ran.
    if role_usage["judge"]["calls"] == 0 and role_usage["judge"]["input_tokens"] == 0:
        role_usage["judge"]["model"] = role_usage["judge"]["model"] or "(not tracked)"

    return {
        "id": log_id or (log.eval.eval_id or ""),
        "title": seed_name or log.eval.task or "petri_task",
        "auditor_model": auditor_model,
        "target_model": target_model,
        "scaffold_name": scaffold_name,
        "seed_name": seed_name,
        "seed_instruction": sample.input if isinstance(sample.input, str) else "",
        "auditor_system_prompt": auditor_system_prompt,
        "created_at": log.eval.created or "",
        "started_at": _iso(getattr(sample, "started_at", None)),
        "completed_at": _iso(getattr(sample, "completed_at", None)),
        "total_time_s": float(total_time_s) if total_time_s is not None else None,
        "role_usage": role_usage,
        "judge": judge,
        "branches": branches,
        "events": events,
    }


def write_transcript(log: EvalLog, out_path: Path, log_id: str = "") -> None:
    data = convert_log(log, log_id=log_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2, default=str))


def summarize(data: dict[str, Any]) -> dict[str, Any]:
    """Compact per-audit summary for the index page."""
    judge = data.get("judge") or {}
    scores = judge.get("scores") or {}
    return {
        "id": data.get("id", ""),
        "title": data.get("title", ""),
        "auditor_model": data.get("auditor_model", ""),
        "target_model": data.get("target_model", ""),
        "scaffold_name": data.get("scaffold_name", ""),
        "seed_name": data.get("seed_name", ""),
        "created_at": data.get("created_at", ""),
        "completed_at": data.get("completed_at", ""),
        "total_time_s": data.get("total_time_s"),
        "event_count": len(data.get("events") or []),
        "branch_count": len(data.get("branches") or []),
        "highlight_count": len(judge.get("highlights") or []),
        "scores": scores,
        "top_score": max(scores.values()) if scores else None,
    }


def write_transcript_and_index(log: EvalLog, data_dir: Path, log_id: str) -> Path:
    """Write `<data_dir>/<log_id>.json` and rebuild `<data_dir>/index.json`."""
    data = convert_log(log, log_id=log_id)
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / f"{log_id}.json"
    out_path.write_text(json.dumps(data, indent=2, default=str))
    rebuild_index(data_dir)
    return out_path


def rebuild_index(data_dir: Path) -> Path:
    """Scan data_dir for per-audit JSONs and write index.json with summaries.

    Sorted by created_at descending so the newest audit is first.
    """
    entries: list[dict[str, Any]] = []
    for p in data_dir.glob("*.json"):
        if p.name == "index.json":
            continue
        try:
            d = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(d, dict) or "events" not in d:
            continue
        entries.append(summarize(d))
    entries.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    idx_path = data_dir / "index.json"
    idx_path.write_text(json.dumps(entries, indent=2, default=str))
    return idx_path
