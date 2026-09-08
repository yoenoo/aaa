"""Offline, non-overwriting export of v5 judgments into copied Petri logs.

The scoring runner remains the source of truth. This module imports its completed
results; it never calls a model, executes scenario tools, or changes source logs.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from inspect_ai.event import ScoreEvent
from inspect_ai.log import EvalResults, EvalScore, read_eval_log, write_eval_log
from inspect_ai.log._log import EvalScorer
from inspect_ai.scorer import Score
from awareness_v5 import DIMENSIONS, payload
from transcript import rebuild_index
from experiments.aaa_vs_petri.export_viewer import convert_petri, response_events
from experiments.aaa_vs_petri.judge_validation_v4.corpus import recorded_packet
from experiments.aaa_vs_petri.petri_awareness_v5.report import aggregate, assessments
from experiments.aaa_vs_petri.petri_awareness_v5.run import (
    DEFAULT_OUTPUT, digest, engine, read_jsonl, sha, unique, verify as verify_run,
)

SCORER = "awareness_v5"
NOTE = (
    "Imported post-hoc v5 judgments over all recorded target responses, including "
    "rollback branches. Only evaluation awareness and simulation/artificiality "
    "suspicion were assessed; no updated realism or other scheming scores. "
    "Categorical detections are not accuracy estimates or 1–10 ratings. "
    "No expression detected does not establish absence of latent awareness."
)
TRANSCRIPT_NOTE = (
    "Reconstructed from the frozen application prompt, exact serialized input, "
    "and saved per-attempt completion records. This is not a native Inspect "
    "ModelEvent or a provider wire trace. No separate private judge reasoning "
    "was recorded. Missing/failed responses are not fabricated."
)


def json_write(path, value):
    """Exclusive creation: even a partially populated destination is never reused."""
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def dump(value):
    return value.model_dump(mode="json") if value is not None else None


def fenced(text, language=""):
    fence = "`" * max(3, 1 + max((len(s) for s in re.findall(r"`+", text)), default=0))
    return f"{fence}{language}\n{text}\n{fence}"


def split_judge_events(events):
    """Archive explicit scoring spans and judge events, not online realism filters.

    Some historical rescoring logs have broken parent links on scorer spans, so
    recognize each scorer root independently before expanding descendants.
    Fail closed if a recognized scoring span contains audit generation/activity.
    """
    spans = {e.id for e in events if e.event == "span_begin" and e.type in {"scorer", "scorers"}}
    while True:
        expanded = spans | {e.id for e in events if e.event == "span_begin" and e.parent_id in spans}
        if expanded == spans:
            break
        spans = expanded
    kept, retired = [], []
    for event in events:
        selected = (event.event == "score" or event.span_id in spans
                    or (event.event in {"span_begin", "span_end"} and event.id in spans)
                    or (event.event == "model" and event.role == "judge"))
        if selected and (event.event == "tool" or
                         (event.event == "model" and event.role in {"target", "auditor", "realism"})):
            raise ValueError("Scoring span overlaps audit activity; refusing to remove it")
        (retired if selected else kept).append(event)
    return kept, retired


def target_message_ids(sample):
    """Map authoritative target model UUIDs to original auditor-message indices."""
    by_resume, _ = response_events(sample)
    mapped = {}
    for index, message in enumerate(sample.messages):
        if message.role == "tool" and message.tool_call_id in by_resume:
            uuid = by_resume[message.tool_call_id].uuid
            if uuid in mapped:
                raise ValueError("Duplicate target-to-viewer mapping")
            mapped[uuid] = f"e{index}"
    if set(mapped) != {e.uuid for e in by_resume.values()} and not sample.error:
        raise ValueError("A target response lacks its original transcript anchor")
    return mapped


def make_score(rows, anchors, provenance):
    totals = aggregate(rows)
    values = {dimension: totals[dimension]["status"] for dimension in DIMENSIONS}
    lines = ["Awareness v5 — imported judgments", "", NOTE, "",
             f"Coverage: {len(rows)} recorded target responses.", ""]
    highlights = []
    for dimension in DIMENSIONS:
        result = totals[dimension]
        counts = ", ".join(f"{n} {status}" for status, n in sorted(result["response_counts"].items()))
        lines.append(f"- {dimension}: **{result['status']}** ({counts}).")
    lines += ["", "Full judge exchanges and target packets are in the companion bundle's "
              "`judge-transcripts/` and `packets/` folders; case IDs appear below."]
    for row in rows:
        for dimension in DIMENSIONS:
            result = row["dimensions"][dimension]
            if result["report_status"] == "absent":
                continue
            lines += ["", f"Response {row['source']['target_event_index'] + 1}, "
                      f"case `{row['id']}`, {dimension}: {result['report_status']}. "
                      + result["explanation"]]
            for evidence in result["evidence"]:
                highlights.append({
                    "event_id": anchors[row["source"]["target_event_uuid"]],
                    "quoted_text": evidence["quote"],
                    "note": f"{dimension}: {result['report_status']}; {evidence['channel']}; "
                            f"case {row['id']}. {result['explanation']}",
                    "case_id": row["id"], "target_model_event_uuid": row["source"]["target_event_uuid"],
                })
    answer = "\n".join(lines)
    return Score(value=values, answer=answer, explanation=NOTE, metadata={
        "judge": SCORER, "parse_status": "validated_import", "highlights": highlights,
        "provenance": provenance, "aggregation": totals, "response_judgments": rows,
        "score_descriptions": {d: "Categorical all-recorded-response rollup; not a 1–10 score." for d in DIMENSIONS},
    })


def exchange(case, packet, prediction, rubric, manifest):
    return {
        "format": "reconstructed-judge-exchange-v1", "limitations": TRANSCRIPT_NOTE,
        "case_id": case["id"], "source": case["source"],
        "judgment_origin": case["judgment_origin"], "model": prediction["model"],
        "request_messages": [
            {"role": "system", "content": rubric},
            {"role": "user", "content": json.dumps(packet, ensure_ascii=False)},
        ],
        "generation_settings": {key: manifest[key] for key in (
            "max_tokens", "timeout_seconds", "cache_prompt", "streaming",
            "automatic_inspect_retries", "automatic_sdk_retries")},
        "response_schema_file": "../schemas.json",
        "response_schema_transport": "inlined, provider object-only additionalProperties projection",
        "attempts": deepcopy(prediction["attempts"]),
        "final_result": deepcopy(prediction["result"]),
        "dimension_attempt": deepcopy(prediction["dimension_attempt"]),
    }


def render_exchange(value):
    lines = [f"# Judge exchange — {value['case_id']}", "", TRANSCRIPT_NOTE, "",
             f"Model: `{value['model']}`. Origin: `{value['judgment_origin']}`.", "",
             "## Exact application request (same for each attempt)", ""]
    for message in value["request_messages"]:
        lines += [f"### {message['role']}", "", fenced(message["content"]), ""]
    for attempt in value["attempts"]:
        lines += [f"## Attempt {attempt['number']} — {attempt['status']}", "",
                  f"Reserved: {attempt.get('reserved_at', 'not recorded')}. "
                  f"Completed: {attempt.get('completed_at', 'not recorded')}.", ""]
        if "response" in attempt:
            lines += ["### Returned assistant completion", "", fenced(attempt["response"], "json"), ""]
        else:
            lines += ["No completion was recorded. See the JSON companion for any saved error.", ""]
    lines += ["## Validated result", "", fenced(json.dumps(value["final_result"], indent=2), "json"), ""]
    return "\n".join(lines)


def verify_report(run):
    manifest = verify_run(run)
    report_manifest = json.loads((run / "report/manifest.json").read_text())
    if report_manifest["run_manifest_sha256"] != sha(run / "manifest.json"):
        raise ValueError("Report belongs to a different run")
    for key, base in (("artifact_sha256", run / "report"), ("prediction_files_sha256", run)):
        for relative, expected in report_manifest[key].items():
            if sha(base / relative) != expected:
                raise ValueError(f"Changed report/prediction artifact: {relative}")
    return manifest


def replace_sample(sample, rows, provenance):
    """Copy before mutation. Keep every non-judging field and event unchanged."""
    result = sample.model_copy(deep=True)
    kept, retired = split_judge_events(sample.events)
    score = make_score(rows, target_message_ids(sample), provenance)
    result.scores = {SCORER: score}
    result.events = deepcopy(kept) + [ScoreEvent(score=score, scorer=SCORER,
        metadata={"imported_at": provenance["exported_at"], "not_a_new_model_call": True})]
    result.metadata = {**sample.metadata, "posthoc_judgment_copy": provenance}
    # Usage/timings describe the historical run, not the imported judgments.
    # Preserve them exactly and explicitly label them, rather than fabricate a
    # reconciled bill from incomplete failed-call telemetry.
    retired_data = {"scores": {k: dump(v) for k, v in (sample.scores or {}).items()},
                    "events": [dump(e) for e in retired]}
    return result, retired_data


def verify_export(destination):
    manifest = json.loads((destination / "manifest.json").read_text())
    for relative, expected in manifest["artifact_sha256"].items():
        if sha(destination / relative) != expected:
            raise ValueError(f"Export artifact changed: {relative}")
    for source in manifest["sources"]:
        if sha(ROOT / source["path"]) != source["sha256"]:
            raise ValueError(f"Original log changed: {source['path']}")
        original = read_eval_log(ROOT / source["path"], resolve_attachments="full")
        copied = read_eval_log(destination / source["copy"], resolve_attachments="full")
        if len(original.samples) != len(copied.samples):
            raise ValueError("Sample count changed")
        for before, after in zip(original.samples, copied.samples):
            allowed = {"scores", "events", "metadata", "attachments", "events_data"}
            if before.model_dump(mode="json", exclude=allowed) != after.model_dump(mode="json", exclude=allowed):
                raise ValueError("Non-judge sample content changed")
            kept, _ = split_judge_events(before.events)
            if [dump(e) for e in kept] != [dump(e) for e in after.events[:-1]]:
                raise ValueError("Audit events changed")
            if set(after.scores or {}) != {SCORER} or after.events[-1].scorer != SCORER:
                raise ValueError("Stale or missing active judge results")
            if after.events[-1].score != after.scores[SCORER]:
                raise ValueError("Score event differs from active result")
    return {"verified": True, **manifest["counts"], "destination": str(destination)}


def export(run, destination):
    run, destination = run.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError("Output already exists; choose a new directory")
    manifest = verify_report(run)
    inputs = unique(read_jsonl(run / "all-inputs.jsonl"), "id")
    cases = unique(read_jsonl(run / "private/cases.jsonl"), "id")
    if set(inputs) != set(cases):
        raise ValueError("Input/case identities differ")
    normalized, predictions, groups = {}, {}, defaultdict(list)
    for cid, case in cases.items():
        folder = {"new_application": "predictions", "reused_calibration": "reused_predictions"}[case["judgment_origin"]]
        prediction = json.loads((run / folder / f"{cid}.json").read_text())
        packet = inputs[cid]["payload"]
        dimensions = assessments(prediction, packet)
        if (prediction["case_id"] != cid or prediction["model"] != manifest["judge_model"]
                or prediction["status"] != "success" or not all(d["valid"] for d in dimensions.values())
                or digest(packet) != case["packet_sha256"]):
            raise ValueError(f"Incomplete or inconsistent judgment: {cid}")
        predictions[cid] = prediction
        normalized[cid] = {**case, "dimensions": dimensions}
        groups[case["source"]["path"]].append(case)
    # Validate all source identities and exact judging payloads before writing.
    logs = {}
    for relative, selected in groups.items():
        source = ROOT / relative
        source_hash = sha(source)
        if any(c["source"]["sha256"] != source_hash for c in selected):
            raise ValueError("Original source hash changed")
        log = read_eval_log(source, resolve_attachments="full")
        samples = {s.uuid: s for s in log.samples or []}
        if set(samples) != {c["audit_id"] for c in selected}:
            raise ValueError("Cannot replace a log with unjudged samples")
        for sample in samples.values():
            selected_cases = [c for c in selected if c["audit_id"] == sample.uuid]
            events = {e.uuid: e for e in sample.events if e.event == "model" and e.role == "target" and e.output and not e.error}
            if set(events) != {c["source"]["target_event_uuid"] for c in selected_cases}:
                raise ValueError("Target response coverage differs")
            for case in selected_cases:
                if payload(recorded_packet(events[case["source"]["target_event_uuid"]])) != inputs[case["id"]]["payload"]:
                    raise ValueError("Source event does not match the judged input")
            target_message_ids(sample)
        logs[relative] = log
    destination.mkdir(parents=True, exist_ok=False)
    for folder in ("eval", "archive", "judge-transcripts", "raw-predictions", "packets", "viewer", "viewer/data"):
        (destination / folder).mkdir()
    for name in ("prompt.txt", "schemas.json", "all-inputs.jsonl"):
        shutil.copyfile(run / name, destination / name)
    rubric = (run / "prompt.txt").read_text()
    for cid, case in cases.items():
        value = exchange(case, inputs[cid]["payload"], predictions[cid], rubric, manifest)
        json_write(destination / "judge-transcripts" / f"{cid}.json", value)
        with (destination / "judge-transcripts" / f"{cid}.md").open("x") as handle:
            handle.write(render_exchange(value))
        folder = "predictions" if case["judgment_origin"] == "new_application" else "reused_predictions"
        shutil.copyfile(run / folder / f"{cid}.json", destination / "raw-predictions" / f"{cid}.json")
        shutil.copyfile(run / "packets" / f"{cid}.md", destination / "packets" / f"{cid}.md")
    exported_at, run_hash = engine.now(), sha(run / "manifest.json")
    sources, audit_index = [], []
    for relative, original in logs.items():
        source = ROOT / relative
        name = f"{source.stem}-awareness-v5.eval"
        copied = original.model_copy(deep=True)
        archive = {"source": relative, "source_sha256": sha(source),
                   "eval_spec": dump(original.eval), "results": dump(original.results),
                   "reductions": [dump(r) for r in original.reductions or []], "samples": {}}
        provenance = {"version": SCORER, "exported_at": exported_at, "source": relative,
                      "source_sha256": sha(source), "judge_run": str(run), "judge_run_manifest_sha256": run_hash,
                      "judge_model": manifest["judge_model"], "note": NOTE,
                      "retired_judgments": f"../archive/{source.stem}.json",
                      "judge_transcripts": "../judge-transcripts/<case_id>.json",
                      "usage_and_timing_policy": "Original historical accounting preserved; it may include retired judges. Imported v5 usage/times are recorded separately per attempt, not added to the old bill."}
        for index, sample in enumerate(original.samples):
            rows = sorted([normalized[c["id"]] for c in groups[relative] if c["audit_id"] == sample.uuid],
                          key=lambda r: r["source"]["target_event_index"])
            updated, old = replace_sample(sample, rows, provenance)
            copied.samples[index] = updated
            archive["samples"][sample.uuid] = old
        copied.eval.eval_id += f"-awareness-v5-{run_hash[:8]}"
        copied.eval.run_id += f"-awareness-v5-{run_hash[:8]}"
        copied.eval.scorers = [EvalScorer(name=SCORER, metadata={"imported": True, "metrics_not_computed": True})]
        copied.eval.metrics = None
        copied.eval.metadata = {k: v for k, v in (original.eval.metadata or {}).items() if k != "aaa_posthoc_judgment"}
        copied.eval.metadata["posthoc_judgment_copy"] = provenance
        copied.eval.model_roles = {**(copied.eval.model_roles or {})}
        if "judge" in copied.eval.model_roles:
            copied.eval.model_roles["judge"] = copied.eval.model_roles["judge"].model_copy(update={"model": manifest["judge_model"]})
        copied.results = EvalResults(total_samples=len(copied.samples),
            completed_samples=sum(not s.error for s in copied.samples),
            scores=[EvalScore(name=SCORER, scorer=SCORER, scored_samples=len(copied.samples),
                             metrics={}, metadata={"categorical_only": True})], metadata={"note": NOTE})
        copied.reductions = None
        copied.recompute_tags_and_metadata()
        path = destination / "eval" / name
        write_eval_log(copied, path)
        json_write(destination / "archive" / f"{source.stem}.json", archive)
        sources.append({"path": relative, "sha256": sha(source), "copy": f"eval/{name}"})
        for sample in copied.samples:
            if sample.error:
                audit_index.append({"id": None, "sample_uuid": sample.uuid,
                    "title": "Incomplete attempt — scenario unconfirmed", "eval_copy": f"eval/{name}",
                    "case_ids": [r["id"] for r in sample.scores[SCORER].metadata["response_judgments"]],
                    "results": sample.scores[SCORER].value, "incomplete": True,
                    "viewer_omission": "Target ModelEvent exists but its resume result is missing from sample.messages. Use the native .eval and judge/packet sidecars; do not invent an auditor-message anchor."})
                continue
            data = convert_petri(copied, sample, path)
            data["id"] += f"-awareness-v5-{run_hash[:8]}"
            data["title"] += " · Awareness v5" + (" · INCOMPLETE" if sample.error else "")
            data["provenance"]["posthoc_judgment_copy"] = provenance
            data["judge"]["categorical_results"] = sample.scores[SCORER].value
            # Source usage may contain the old judges, but the converter uses
            # retained model events; imported judge usage remains in sidecars.
            if data["judge"]["scores"]:
                raise ValueError("Categorical judgments must not become numeric ratings")
            json_write(destination / "viewer/data" / f"{data['id']}.json", data)
            audit_index.append({"id": data["id"], "sample_uuid": sample.uuid,
                "title": data["title"], "eval_copy": f"eval/{name}",
                "case_ids": [r["id"] for r in sample.scores[SCORER].metadata["response_judgments"]],
                "results": sample.scores[SCORER].value, "incomplete": bool(sample.error)})
    rebuild_index(destination / "viewer/data")
    json_write(destination / "audits.json", audit_index)
    with (destination / "README.md").open("x") as handle:
        handle.write("# Copied Petri audit logs — awareness v5\n\n" + NOTE + "\n\n"
            "Original .eval logs and original viewer files are untouched. The four `eval/` copies "
            "replace active scores, score events, summaries and highlights; retired post-hoc "
            "judge events/scores/specifications are in `archive/`. Auditor/target messages, "
            "tool calls/results, reasoning and non-judge events remain unchanged. Online "
            "realism-filter calls remain part of the historical audit. Source usage/timings "
            "are historical, not the cost/duration of this import.\n\n"
            "`audits.json` maps audits to copies and case IDs. Each case has an exact raw "
            "prediction in `raw-predictions/`, full target packet in `packets/`, and JSON + "
            "readable Markdown request/response exchange in `judge-transcripts/`. " + TRANSCRIPT_NOTE + "\n\n"
            "`viewer/data/` contains the 18 completed audits with distinct IDs, an index, v5 summaries and evidence highlights. "
            "The existing transcript viewer renders categorical findings in its Evidence "
            "panel; numeric Scores are intentionally empty. Use this folder as the viewer's "
            "`/data/` source; it has not been installed over the existing viewer catalog.\n\n"
            "18 completed audits and one incomplete setup attempt are kept separate. "
            "The incomplete attempt has no auditor-message anchor for its target output, "
            "so it is included in native copies/sidecars but not the custom viewer. "
            "All 398 judgments were reused; this export made no model calls. This bundle "
            "contains Petri, not the pending AAA model-pair comparison. Treat full prompts, "
            "transcripts and raw API errors as local research data; nothing was published.\n")
    export_manifest = {"version": "copied-petri-awareness-v5-v1", "exported_at": exported_at,
        "exporter_sha256": sha(Path(__file__)), "judge_run_manifest_sha256": run_hash,
        "sources": sources, "counts": {"eval_copies": len(sources), "audit_copies": len(audit_index),
            "completed_audits": sum(not a["incomplete"] for a in audit_index),
            "incomplete_attempts": sum(a["incomplete"] for a in audit_index),
            "judge_exchanges": len(cases), "new_model_calls": 0},
        "artifact_sha256": {str(p.relative_to(destination)): sha(p) for p in destination.rglob("*") if p.is_file()}}
    json_write(destination / "manifest.json", export_manifest)
    return verify_export(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "verify"])
    parser.add_argument("destination", type=Path)
    parser.add_argument("--run", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(export(args.run, args.destination) if args.action == "export" else verify_export(args.destination), indent=2))
