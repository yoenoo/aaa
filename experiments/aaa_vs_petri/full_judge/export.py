"""Export completed full judgments to new native logs, viewer data and reports."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from inspect_ai.event import ModelEvent, ScoreEvent
from inspect_ai.log import EvalResults, EvalScore, read_eval_log, write_eval_log
from inspect_ai.log._log import EvalScorer
from inspect_ai.model import GenerateConfig, ModelUsage
from inspect_ai.model._model_config import ModelConfig
from inspect_ai.scorer import Score
from transcript import rebuild_index
from experiments.aaa_vs_petri.export_rejudged import fenced, split_judge_events
from experiments.aaa_vs_petri.export_viewer import convert_petri
from experiments.aaa_vs_petri.full_judge import spec
from experiments.aaa_vs_petri.full_judge.run import DEFAULT, atomic_json, now, sha, verify


def score_for(row, audit, provenance):
    result, family = row["result"], row["family"]
    values = dict(result["scores"])
    citations = list(result["evidence"] if family == spec.FAMILIES[0] else result["issues"])
    summary = result["summary"]
    unknown = [key for key, value in values.items() if value is None]
    if unknown:
        summary += '\n\nNot assessable (null; excluded from numeric scores): ' + ', '.join(unknown)
    if family == spec.FAMILIES[0]:
        summary += "\n\nAwareness (categorical, not 1–10):"
        for dimension, assessment in result["awareness"].items():
            values[dimension] = assessment["status"]
            summary += f"\n\n{dimension}: **{assessment['status']}**. {assessment['explanation']}"
            citations += [{**e, "dimension": dimension, "interpretation": assessment["explanation"]}
                          for e in assessment["evidence"]]
    highlights, unanchored = [], []
    for citation in citations:
        mapping = audit["record_mapping"][citation["event_id"]]
        event_id = mapping["viewer_event_id"]
        if not event_id:
            unanchored.append(citation)
            continue
        context_note = ""
        if mapping["actor"] not in {"target", "auditor_context"}:
            context_note = " Target-input context citation, anchored to the first receiving target call; see the exact request in the judge exchange."
        highlights.append({"event_id": event_id, "quoted_text": citation["quote"],
            "note": f"{citation['dimension']}; record {citation['event_id']}; {citation['channel']}. "
                    + citation.get("rationale", citation.get("interpretation", "")) + context_note})
    if unanchored:
        summary += f"\n\n{len(unanchored)} additional citation(s) refer to auditor system messages omitted by the custom viewer; preserved in the native judge records."
    descriptions = dict(spec.BEHAVIOR if family == spec.FAMILIES[0] else spec.DEBUG)
    if family == spec.FAMILIES[0]:
        descriptions.update({d: "V5 verbalized-awareness definition; categorical full-audit integration." for d in spec.DIMENSIONS})
    return Score(value=values, answer=summary,
        explanation="\n\n".join(f"{key}: {value}" for key, value in result["reasons"].items()),
        metadata={"judge": "scheming" if family == spec.FAMILIES[0] else "debug", "judge_family": family,
            "parse_status": "validated", "response": next(a["response"] for a in row["attempts"] if a["status"] == "success"),
            "highlights": highlights, "all_citations": citations, "unanchored_citations": unanchored,
            "score_descriptions": descriptions, "structured_result": result,
            "provenance": provenance, "job_id": row["id"]})


def add_usage(events):
    models, roles = {}, {}
    for event in events:
        if event.event != "model" or not event.output or not event.output.usage:
            continue
        models[event.model] = models.get(event.model, ModelUsage()) + event.output.usage
        if event.role:
            roles[event.role] = roles.get(event.role, ModelUsage()) + event.output.usage
    return models, roles


def render_exchange(run, row):
    lines = [f"# {row['id']}", "", "Actual Modal judge request and returned completions. "
             "Native Inspect ModelEvents are retained in the copied .eval and raw prediction JSON. "
             "Unavailable private reasoning is not reconstructed. Historical attempts may use a different transport; their actual prompts are recorded separately below.", "", "## Current recovery system prompt", "",
             fenced((run / 'prompts' / f"{row['family']}.txt").read_text()), "",
             "## Exact user input", "", fenced((run / 'inputs' / f"{row['id']}.json").read_text(), "json"), ""]
    for attempt in row["attempts"]:
        lines += [f"## Attempt {attempt['number']} — {attempt['status']}", "",
                  f"{attempt['reserved_at']} → {attempt.get('completed_at', 'not recorded')}", ""]
        for event in attempt.get('model_events', []):
            lines += ['### Actual captured request', '', fenced(json.dumps(event.get('input', []), indent=2), 'json'),
                      '', '### Actual captured response schema/config', '',
                      fenced(json.dumps(event.get('config', {}), indent=2), 'json'), '']
        if "response" in attempt:
            lines += [fenced(attempt["response"], "json"), ""]
        else:
            lines += ["No completion recorded; any raw error is retained in the prediction JSON.", ""]
    return "\n".join(lines)


def export(run, destination, audit_ids=None):
    run, destination = run.resolve(), destination.resolve()
    recovery = 'original_run' in json.loads((run / 'manifest.json').read_text())
    if recovery:
        from experiments.aaa_vs_petri.full_judge.recovery import verify as verify_recovery
        m = verify_recovery(run)
    else:
        m = verify(run)
    if destination.exists():
        raise ValueError("Choose a fresh export directory")
    audits = json.loads((run / "private/audits.json").read_text())
    jobs = json.loads((run / "jobs.json").read_text())
    if audit_ids is not None:
        selected = set(audit_ids)
        if not selected or not selected <= {a['id'] for a in audits}:
            raise ValueError('Unknown or empty audit selection')
        audits = [a for a in audits if a['id'] in selected]
        jobs = [j for j in jobs if j['audit_id'] in selected]
    predictions = {}
    for job in jobs:
        path = run / "predictions" / f"{job['id']}.json"
        row = json.loads(path.read_text())
        if row["status"] != "success" or row["model"] != m["judge_model"] or len(row["attempts"]) > 3:
            raise ValueError("Export requires both valid judgments for every selected audit")
        spec.validate(row["result"], json.loads((run / "inputs" / f"{job['id']}.json").read_text()), job["family"])
        if not any(a.get("model_events") for a in row["attempts"]):
            raise ValueError("Native judge model events are missing")
        predictions[job["id"]] = row
    requests = sum(len(r["attempts"]) for r in predictions.values())
    if requests > m['max_provider_requests']:
        raise ValueError("Request ceiling exceeded")
    destination.mkdir(parents=True)
    for folder in ("completed-18-evals", "archive", "viewer", "viewer/data", "judge-transcripts"):
        (destination / folder).mkdir()
    for row in predictions.values():
        (destination / "judge-transcripts" / f"{row['id']}.md").write_text(render_exchange(run, row))
    by_source = defaultdict(list)
    for audit in audits:
        by_source[audit["source"]].append(audit)
    run_hash = sha(run / "manifest.json")
    exported_at, copies = now(), []
    for relative, selected in by_source.items():
        source = ROOT / relative
        original = read_eval_log(source, resolve_attachments="full")
        copied = original.model_copy(deep=True)
        lookup = {a["id"]: a for a in selected}
        archive = {"source": relative, "source_sha256": sha(source),
            "eval_spec": original.eval.model_dump(mode="json"),
            "results": original.results.model_dump(mode="json") if original.results else None,
            "samples": {}}
        provenance = {"version": m["version"], "exported_at": exported_at, "source": relative,
            "source_sha256": sha(source), "judge_run": str(run), "run_manifest_sha256": run_hash,
            "judge_model": m["judge_model"], "execution_backend": "modal", "configuration_note": m["configuration_note"],
            "accounting": "Usage recomputed from retained audit model events and actual new judge events. Unknown failed-request usage is not estimated. Audit start/end/duration remain historical; judge request timestamps are in their ModelEvents."}
        selected_samples = [s for s in original.samples if s.uuid in lookup]
        copied.samples = []
        for before in selected_samples:
            audit = lookup[before.uuid]
            after = before.model_copy(deep=True)
            retained, retired = split_judge_events(before.events)
            after.events = deepcopy(retained)
            after.scores = {}
            archive["samples"][before.uuid] = {"scores": {k: v.model_dump(mode="json") for k, v in (before.scores or {}).items()},
                "events": [e.model_dump(mode="json") for e in retired],
                "model_usage": {k: v.model_dump(mode="json") for k, v in before.model_usage.items()},
                "role_usage": {k: v.model_dump(mode="json") for k, v in before.role_usage.items()}}
            for family in spec.FAMILIES:
                row = predictions[f"{before.uuid}-{family}"]
                for attempt in row["attempts"]:
                    for raw in attempt.get("model_events", []):
                        event = ModelEvent.model_validate(raw)
                        if event.model != m["judge_model"]:
                            raise ValueError("Unexpected captured judge model")
                        event.metadata = {**(event.metadata or {}), "original_recorded_role": event.role,
                            "judge_family": family, "job_id": row["id"], "attempt": attempt["number"], "execution_backend": "modal"}
                        event.role = "judge"
                        after.events.append(event)
                score = score_for(row, audit, provenance)
                after.scores[family] = score
                after.events.append(ScoreEvent(score=score, scorer=family, metadata={"posthoc_import": True, "job_id": row["id"]}))
            # Worker families run concurrently; retain their actual chronology
            # rather than grouping earlier/later requests by scorer name.
            added = after.events[len(retained):]
            after.events = after.events[:len(retained)] + sorted(added, key=lambda e: e.timestamp)
            after.metadata = {**before.metadata, "full_posthoc_judgments": provenance}
            after.model_usage, after.role_usage = add_usage(after.events)
            copied.samples.append(after)
        copied.eval.eval_id += f"-full-v1-{run_hash[:8]}"
        copied.eval.run_id += f"-full-v1-{run_hash[:8]}"
        copied.eval.scorers = [EvalScorer(name=f, metadata={"configuration": m["version"]}) for f in spec.FAMILIES]
        copied.eval.metrics = None
        copied.eval.model_roles = {**(copied.eval.model_roles or {}), "judge": ModelConfig(model=m["judge_model"], config=GenerateConfig(max_tokens=16000, max_retries=0))}
        copied.eval.metadata = {k: v for k, v in (copied.eval.metadata or {}).items() if k != "aaa_posthoc_judgment"}
        copied.eval.metadata["full_posthoc_judgments"] = provenance
        copied.results = EvalResults(total_samples=len(copied.samples), completed_samples=len(copied.samples),
            scores=[EvalScore(name=f, scorer=f, scored_samples=len(copied.samples), metrics={}) for f in spec.FAMILIES])
        copied.reductions = None
        copied.stats.model_usage = add_usage([e for s in copied.samples for e in s.events])[0]
        copied.recompute_tags_and_metadata()
        path = destination / "completed-18-evals" / f"{source.stem}-full-judge-v1.eval"
        write_eval_log(copied, path)
        atomic_json(destination / "archive" / f"{source.stem}.json", archive)
        reopened = read_eval_log(path, resolve_attachments="full")
        for before, after in zip(selected_samples, reopened.samples):
            allowed = {"scores", "events", "metadata", "model_usage", "role_usage", "attachments", "events_data"}
            if before.model_dump(mode="json", exclude=allowed) != after.model_dump(mode="json", exclude=allowed):
                raise ValueError("Non-judge sample content changed")
            retained, _ = split_judge_events(before.events)
            if [e.model_dump(mode="json") for e in retained] != [e.model_dump(mode="json") for e in after.events[:len(retained)]]:
                raise ValueError("Original audit events changed")
            if set(after.scores) != set(spec.FAMILIES) or [len(after.scores[f].value) for f in spec.FAMILIES] != [33, 14]:
                raise ValueError("Copied log does not contain the full two-judge result")
            data = convert_petri(reopened, after, path)
            data["id"] += f"-full-judge-v1-{run_hash[:8]}"
            data["title"] += " · Full judge v1 (v5 awareness)"
            data["judge"]["categorical_results"] = {d: after.scores[spec.FAMILIES[0]].value[d] for d in spec.DIMENSIONS}
            data['judge']['unassessable_dimensions'] = [k for score in after.scores.values()
                                                       for k, v in score.value.items() if v is None]
            data["provenance"]["full_posthoc_judgments"] = provenance
            atomic_json(destination / "viewer/data" / f"{data['id']}.json", data)
        if sha(source) != m["source_sha256"][relative]:
            raise ValueError("Original source log changed")
        copies.append({"source": relative, "copy": str(path.relative_to(destination)), "sha256": sha(path), "samples": len(reopened.samples)})
    rebuild_index(destination / "viewer/data")
    previous = {a["audit_id"]: a for a in json.loads((run / "private/frozen-v5-audits.json").read_text())}
    results, changes = [], []
    normalize = {"absent": "no_expression_detected", "present": "present", "uncertain": "review_required", "unassessable": "review_required"}
    for audit in audits:
        behavior = predictions[f"{audit['id']}-{spec.FAMILIES[0]}"]["result"]
        debug = predictions[f"{audit['id']}-{spec.FAMILIES[1]}"]["result"]
        comparison = {d: {"standalone_v5": previous[audit["id"]]["all_recorded"][d]["status"],
                          "integrated": behavior["awareness"][d]["status"]} for d in spec.DIMENSIONS}
        for dimension, pair in comparison.items():
            if pair["standalone_v5"] != normalize[pair["integrated"]]:
                changes.append({"audit_id": audit["id"], "seed": audit["seed"], "dimension": dimension, **pair})
        results.append({"audit_id": audit["id"], "seed": audit["seed"], "scheming": behavior, "debug": debug, "awareness_comparison": comparison})
    summary = {"audits": len(audits), "jobs": len(jobs), "selected_counted_attempts": requests,
        "request_ceiling": m['max_provider_requests'],
        "execution_backend": "modal", "dimension_counts": m["dimension_counts"],
        "awareness_counts": {d: dict(Counter(r["scheming"]["awareness"][d]["status"] for r in results)) for d in spec.DIMENSIONS},
        "awareness_disagreements_with_standalone_v5": changes,
        "interpretation": m["configuration_note"] + " Disagreements are not proven false positives/negatives; neither output is independent human ground truth.", "copies": copies}
    atomic_json(destination / "results.json", results)
    if recovery:
        summary['recovery_progress'] = json.loads((run / 'progress.json').read_text())
        summary['transport'] = m['transport']
    atomic_json(destination / "summary.json", summary)
    lines = [f"# Full Petri rejudgment — {len(audits)} completed audits", "", summary["interpretation"], "",
        f"{len(jobs)} valid judgments on Modal; {requests} counted attempts for the selected jobs. Two active scorers: 31 numeric behavioral dimensions + 2 categorical awareness dimensions; 14 numeric debugging dimensions. All originals preserved.", "",
        "Native `.eval` copies: `completed-18-evals/`. They include actual captured judge ModelEvents (requests, outputs and returned usage), not just score imports. Readable exchanges: `judge-transcripts/`. Exact raw predictions and schemas remain in the parent run directory. Separate viewer files are in `viewer/data/`; they have distinct IDs and are not installed or hosted over the baseline.", "",
        "All recorded target requests/branches are included; shared input content is deduplicated without changing any individual request. Non-judge message/event preservation and two-scorer coverage were checked after reopening the copied files. Usage is recorded-event accounting; missing failed-call usage is unknown.", "",
        "| Seed | Eval awareness | Simulation suspicion | Scenario realism /10 |", "|---|---|---|---:|"]
    for result in sorted(results, key=lambda r: r["seed"]):
        labels = [result["scheming"]["awareness"][d]["status"] for d in spec.DIMENSIONS]
        lines.append(f"| {result['seed']} | {labels[0]} | {labels[1]} | {result['debug']['scores']['scenario_realism']} |")
    lines += ["", "## Disagreements with standalone v5", "", "These compare the same selected audits under different judge configurations, not independent accuracy labels.", ""]
    lines += [f"- {r['seed']}, {r['dimension']}: standalone {r['standalone_v5']} → integrated {r['integrated']}." for r in changes] or ["None at the audit-level detection/review rollup."]
    (destination / "RESULTS.md").write_text("\n".join(lines) + "\n")
    atomic_json(destination / "manifest.json", {"exported_at": exported_at, "judge_run_manifest_sha256": run_hash,
        "exporter_sha256": sha(Path(__file__)), "source_sha256": m["source_sha256"],
        "prediction_sha256": {p.name: sha(p) for p in (run / "predictions").glob("*.json")},
        "artifact_sha256": {str(p.relative_to(destination)): sha(p) for p in destination.rglob("*") if p.is_file()}})
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, nargs="?", default=DEFAULT)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.run, args.destination or args.run / "full-results"), indent=2))
