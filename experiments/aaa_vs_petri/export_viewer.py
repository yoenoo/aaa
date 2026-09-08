"""Export native Petri logs to AAA's transcript-viewer without altering logs.

Preserves auditor-message indices for AAA judge citations. Target activity is
recovered only from target ModelEvents, not auditor claims or staged tool results.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

from inspect_ai.log import read_eval_log

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from transcript import _text, convert_log, rebuild_index  # noqa: E402


def identity_flags(target_model: str, system_prompts: list[str]) -> list[str]:
    """Conservative explicit-identity screen, separate from LLM judge scores."""
    if not target_model.startswith("google/"):
        return []
    flags = set()
    for prompt in system_prompts:
        for name in re.findall(r"\byou are\s+(Codex|ChatGPT|Claude)\b", prompt, re.I):
            flags.add(f"Gemini target assigned {name} identity")
    return sorted(flags)


def response_events(sample):
    targets = [e for e in sample.events if e.event == "model" and e.role == "target"]
    resumes = [e for e in sample.events if e.event == "tool" and e.function == "resume"]
    result = {}
    mapped = []
    for resume in resumes:
        matches = [e for e in targets if resume.completed and e.completed
                   and resume.timestamp <= e.timestamp and e.completed <= resume.completed]
        if "<target_response>" in str(resume.result) and len(matches) != 1:
            raise ValueError(f"Ambiguous target attribution in {sample.id}: {resume.id}")
        if matches:
            if len(matches) != 1 or resume.id in result:
                raise ValueError("Duplicate/overlapping resume windows")
            result[resume.id] = matches[0]
            mapped.append(matches[0].uuid)
    if Counter(mapped) != Counter(e.uuid for e in targets):
        raise ValueError(f"Target generations missing or duplicated in {sample.id}")
    return result, targets


def delivered_results(current, targets, cutoff=None):
    """First subsequent input containing this exact assistant message is evidence.

    Match both the assistant message ID and tool-call ID. Reused function names
    or similar commands across rollback siblings must never cross-attach results.
    A staged auditor result not observed in a target input remains unavailable.
    """
    message = current.output.message
    wanted = {call.id for call in message.tool_calls or []}
    for later in targets:
        if later.timestamp <= current.timestamp:
            continue
        if cutoff is not None and later.timestamp >= cutoff:
            continue
        for i, item in enumerate(later.input):
            if item.role != "assistant" or item.id != message.id:
                continue
            found = {}
            for candidate in later.input[i + 1:]:
                if candidate.role != "tool":
                    break
                if candidate.tool_call_id in wanted:
                    found[candidate.tool_call_id] = candidate.text
            if found:
                return found
    return {}


def convert_petri(log, sample, source: Path):
    if not (sample.metadata or {}).get("source_scenario"):
        raise ValueError(f"Missing source_scenario metadata for {sample.id}")
    sid = f"petri-{sample.uuid or (str(sample.id) + '-e' + str(sample.epoch))}"
    # Avoid the generic converter's legacy whole-eval residual-token fallback:
    # all Petri auditor/realism/target/judge usage is already in per-sample events.
    stats = log.stats.model_copy(update={"model_usage": {}}) if log.stats else None
    one = log.model_copy(update={"samples": [sample], "stats": stats})
    data = convert_log(one, log_id=sid)
    source_seed = sample.metadata["source_scenario"]
    data.update({
        "title": f"Petri · {source_seed}", "seed_name": source_seed,
        "scaffold_name": "Petri native / synthetic tools (no coding scaffold)",
        "auditor_model": str(log.eval.model_roles["auditor"].model),
        "provenance": {
            "condition": "petri-native-synthetic", "source_log": str(source),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "sample_id": sample.id, "sample_uuid": sample.uuid,
            "epoch": sample.epoch, "status": "error" if sample.error else "success",
            "error": sample.error.model_dump(mode="json") if sample.error else None,
            "tools_executed": False, "branch_semantics": "chronological rollback segments",
        },
    })
    model_by_resume, targets = response_events(sample)
    prompts = list(dict.fromkeys(m.text for e in targets for m in e.input if m.role == "system"))
    data["provenance"]["identity_flags"] = identity_flags(data["target_model"], prompts)
    data["provenance"]["unique_target_system_prompts"] = len(prompts)
    accepted_rollbacks = {
        e.id: e.arguments for e in sample.events
        if e.event == "tool" and e.function in ("rollback_conversation", "restart_conversation")
        and not e.error and not e.failed
    }
    rollback_times = sorted(e.timestamp for e in sample.events
                            if e.event == "tool" and e.id in accepted_rollbacks)
    branch = 1
    labels = {1: "Segment 1"}
    for event in data["events"]:
        call_id = event.get("tool_call_id")
        if event["role"] == "tool" and call_id in accepted_rollbacks:
            branch += 1
            anchor = accepted_rollbacks[call_id].get("message_id", "start")
            labels[branch] = f"Segment {branch} · rollback to {anchor}"
        event["branch"] = branch
        if event["role"] != "tool" or call_id not in model_by_resume:
            continue
        model_event = model_by_resume[call_id]
        output = model_event.output.message
        text, reasoning, redacted = _text(output.content)
        cutoff = next((ts for ts in rollback_times if ts > model_event.timestamp), None)
        results = delivered_results(model_event, targets, cutoff=cutoff)
        event["target_activity"] = [{
            "text": text, "reasoning": reasoning, "redacted_reasoning_chars": redacted,
            "tool_calls": [{
                "id": call.id, "function": call.function, "arguments": call.arguments,
                "result": results.get(call.id), "result_is_simulated": True,
            } for call in output.tool_calls or []],
        }]
        event["target_system_prompt"] = "\n".join(
            m.text for m in model_event.input if m.role == "system")
        event["target_model_event_uuid"] = model_event.uuid
        # Keep event content and tool_name='resume' intact for source inspection.

    data["branches"] = []
    highlight_ids = {h["event_id"] for h in data["judge"]["highlights"]}
    for number in range(1, branch + 1):
        events = [e for e in data["events"] if e["branch"] == number]
        if not events:
            continue
        data["branches"].append({
            "index": number, "label": labels[number],
            "start_event_id": events[0]["id"], "end_event_id": events[-1]["id"],
            "event_count": len(events),
            "duration_s": sum(e.get("duration_s") or 0 for e in events),
            "highlight_count": sum(e["id"] in highlight_ids for e in events),
        })
    event_ids = {e["id"] for e in data["events"]}
    missing = highlight_ids - event_ids
    if missing:
        raise ValueError(f"Judge citations have no viewer event: {missing}")
    data["provenance"]["target_model_calls"] = len(targets)
    data["provenance"]["target_tool_calls"] = sum(len(t.output.message.tool_calls or []) for t in targets)
    data["provenance"]["tool_results_observed_by_target"] = sum(
        call["result"] is not None for event in data["events"]
        for turn in event.get("target_activity", []) for call in turn["tool_calls"])
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path, nargs="+")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "viewer/public/data")
    args = parser.parse_args()
    exports = []
    for source in args.logs:
        log = read_eval_log(source, resolve_attachments="full")
        for sample in log.samples or []:
            data = convert_petri(log, sample, source)
            output = args.data_dir / (data["id"] + ".json")
            if output.exists():
                old = json.loads(output.read_text())
                if old.get("provenance", {}).get("sample_uuid") != sample.uuid:
                    raise ValueError(f"Refusing to overwrite unrelated transcript: {output}")
                if len(old.get("judge", {}).get("scores", {})) > len(data["judge"]["scores"]):
                    raise ValueError(f"Refusing to replace judged transcript with fewer scores: {output}")
            exports.append((output, data))
    args.data_dir.mkdir(parents=True, exist_ok=True)
    for output, data in exports:
        output.write_text(json.dumps(data, indent=2) + "\n")
        print(f"{data['seed_name']}: http://localhost:5173/#/{data['id']} "
              f"({data['provenance']['target_model_calls']} target turns; "
              f"{len(data['judge']['scores'])} scores)", flush=True)
    rebuild_index(args.data_dir)
    print(f"Exported {len(exports)} Petri samples; existing unrelated viewer files preserved.")


if __name__ == "__main__":
    main()
