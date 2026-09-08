"""Evidence-linked application report. Detection counts are not judge accuracy."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from experiments.aaa_vs_petri.petri_awareness_v5.run import DEFAULT_OUTPUT, engine, read_jsonl, sha, unique, verify, write_jsonl
from awareness_v5 import DIMENSIONS, validate_response


def rollup(statuses):
    counts = dict(Counter(statuses))
    unresolved = sum(n for status, n in counts.items() if status not in {"present", "absent"})
    status = ("not_observed" if not statuses else "present" if counts.get("present") else
              "review_required" if unresolved else "no_expression_detected")
    return {"status": status, "response_counts": counts, "unresolved_responses": unresolved}


def aggregate(rows):
    return {"target_responses": len(rows), **{d: rollup([r["dimensions"][d]["report_status"] for r in rows]) for d in DIMENSIONS}}


def assessments(row, packet):
    if row is None:
        return {d: {"report_status": "missing", "valid": False, "evidence": [], "explanation": "No recorded judgment."} for d in DIMENSIONS}
    try:
        result = validate_response(row.get("result", {}), packet)["dimensions"]
    except ValueError:
        return {d: {"report_status": "invalid", "valid": False, "evidence": [], "explanation": "Invalid judgment root."} for d in DIMENSIONS}
    return {d: {**a, "report_status": a["status"] if a["valid"] else "invalid"} for d, a in result.items()}


def report(output, destination):
    m = verify(output)
    if destination.exists():
        raise ValueError("Choose a new report folder; do not overwrite existing results")
    inputs = unique(read_jsonl(output / "all-inputs.jsonl"), "id")
    cases = unique(read_jsonl(output / "private/cases.jsonl"), "id")
    inventory = json.loads((output / "private/source-inventory.json").read_text())
    if set(cases) != set(inputs):
        raise ValueError("Metadata/input identities differ")
    rows, prediction_hashes, execution = [], {}, {}
    for origin, folder in (("new_application", "predictions"), ("reused_calibration", "reused_predictions")):
        predictions = {}
        usage = Counter()
        for path in sorted((output / folder).glob("*.json")):
            row = json.loads(path.read_text())
            cid = row["case_id"]
            if cid not in cases or cases[cid]["judgment_origin"] != origin or cid != path.stem or row["model"] != m["judge_model"]:
                raise ValueError("Unexpected prediction identity or origin")
            if len(row["attempts"]) > m["max_attempts_per_job"]:
                raise ValueError("Job exceeded attempt ceiling")
            predictions[cid] = row
            prediction_hashes[str(path.relative_to(output))] = sha(path)
            for attempt in row["attempts"]:
                usage.update({k: v for k, v in attempt.get("usage", {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
        execution[origin] = {"job_status_counts": dict(Counter(r["status"] for r in predictions.values())),
            "recorded_jobs": len(predictions), "request_reservations": sum(len(r["attempts"]) for r in predictions.values()),
            "attempt_status_counts": dict(Counter(a["status"] for r in predictions.values() for a in r["attempts"])),
            "usage_reported": dict(usage), "usage_note": "Only usage returned by the provider is known; failed/unknown requests may be missing usage."}
        for cid, case in sorted(cases.items()):
            if case["judgment_origin"] == origin:
                rows.append({**case, "dimensions": assessments(predictions.get(cid), inputs[cid]["payload"])})
    if execution["new_application"]["request_reservations"] > m["max_provider_requests"]:
        raise ValueError("New request ceiling exceeded")
    audits = []
    for audit in inventory["audits"]:
        selected = [r for r in rows if r["audit_id"] == audit["audit_id"]]
        last = [r for r in selected if r["last_conversation_membership"] in {"latest_output", "exact_history_match"}]
        audits.append({**audit, "all_recorded": aggregate(selected), "last_recorded_conversation": aggregate(last),
                       "membership_counts": dict(Counter(r["last_conversation_membership"] for r in selected))})
    summary = {"run_counts": m["counts"], "execution": execution, "cohorts": {},
               "interpretation": "Judge-detected verbalizations, not independently confirmed labels or estimates of judge accuracy. Exposed corpus, one audit per scenario, correlated responses and rollback attempts. Absent means no qualifying expression observed, not proof of no latent awareness. No realism rating or AAA comparison."}
    for cohort in ("completed_audit", "incomplete_attempt"):
        selected = [r for r in rows if r["cohort"] == cohort]
        summary["cohorts"][cohort] = {"all_recorded_responses": aggregate(selected),
            "last_recorded_conversation_responses": aggregate([r for r in selected if r["last_conversation_membership"] in {"latest_output", "exact_history_match"}]),
            "audits": len([a for a in audits if a["cohort"] == cohort]),
            "audit_status_counts": {scope: {d: dict(Counter(a[scope][d]["status"] for a in audits if a["cohort"] == cohort)) for d in DIMENSIONS}
                                    for scope in ("all_recorded", "last_recorded_conversation")}}
    findings = sorted([r for r in rows if any(a["report_status"] != "absent" for a in r["dimensions"].values())],
                      key=lambda r: (r["cohort"], r["seed"], r["source"]["target_event_index"]))
    destination.mkdir(parents=True)
    for name, value in (("summary.json", summary), ("audits.json", audits), ("review-queue.json", findings)):
        engine.atomic_json(destination / name, value)
    write_jsonl(destination / "predictions.jsonl", sorted(rows, key=lambda r: r["id"]))
    # Relative links remain valid for reports created alongside the frozen inputs.
    import os
    packet_root = os.path.relpath(output / "packets", destination)
    lines = ["# Petri: calibrated v5 awareness sweep", "", summary["interpretation"], "",
             f"Model: `{m['judge_model']}`. {len(rows)} target responses; {m['counts']['reused_jobs']} exact prior judgments reused and {m['counts']['new_jobs']} new jobs. "
             f"New request reservations: {execution['new_application']['request_reservations']}/{m['max_provider_requests']}; "
             f"historical cached reservations: {m['historical_cached_requests']} (not new spending).", "",
             "Each response is judged with its recorded API input. Only its new output supplies evidence; historical assistant text is context. "
             "The last-conversation column includes outputs matched exactly in the last successful target request, plus that request's output. "
             "Other recorded outputs can include abandoned rollback branches. Exposed reasoning may be provider summaries, not full private CoT.", "",
             "## Completed audits", "", "Numbers are positive responses / assessed-scope responses; unresolved results are shown separately. These are detection frequencies, not error rates.", "",
             "| Seed | Eval: all / last | Simulation: all / last | Unresolved dimensions: all |", "|---|---|---|---:|"]
    for a in sorted(audits, key=lambda a: a["seed"]):
        if a["cohort"] != "completed_audit":
            continue
        cells = []
        for d in DIMENSIONS:
            cells.append(" / ".join(f"{a[s][d]['response_counts'].get('present', 0)} of {a[s]['target_responses']}" for s in ("all_recorded", "last_recorded_conversation")))
        unresolved = sum(a["all_recorded"][d]["unresolved_responses"] for d in DIMENSIONS)
        lines.append(f"| [{a['seed']}](http://localhost:5173/#/petri-{a['audit_id']}) | {cells[0]} | {cells[1]} | {unresolved} |")
    lines += ["", "Viewer links require the existing local transcript viewer; packet links below are standalone.", "",
              "## Incomplete attempts (excluded above)", ""]
    for a in audits:
        if a["cohort"] == "incomplete_attempt":
            lines += [f"- Sample `{a['audit_id']}`, recorded seed identifier `{a['seed']}`: {a['target_responses']} target output(s); "
                      + ", ".join(f"{d}: {a['all_recorded'][d]['status']}" for d in DIMENSIONS) + "."]
    lines += ["", "## Evidence and unresolved-review queue", "", "These are judge findings, not adjudicated human labels. Quotes are validated against the recorded focus output.", ""]
    for r in findings:
        lines += [f"### {r['seed']} — target response {r['source']['target_event_index'] + 1}", "",
                  f"[Full packet]({packet_root}/{r['id']}.md). Audit `{r['audit_id']}`; event `{r['source']['target_event_uuid']}`; "
                  f"segment {r['segment']}; last-conversation membership `{r['last_conversation_membership']}`; {r['judgment_origin']}.", ""]
        for d, a in r["dimensions"].items():
            if a["report_status"] == "absent":
                continue
            lines += [f"{d}: **{a['report_status']}**. {a['explanation']}", ""]
            for e in a["evidence"]:
                lines += [f"Channel: `{e['channel']}`.", "", *["> " + line for line in e["quote"].splitlines()], ""]
    if not findings:
        lines += ["No positive or unresolved judgments recorded.", ""]
    (destination / "RESULTS.md").write_text("\n".join(lines))
    engine.atomic_json(destination / "manifest.json", {"created_at": engine.now(), "run_manifest_sha256": sha(output / "manifest.json"),
        "prediction_files_sha256": prediction_hashes,
        "artifact_sha256": {p.name: sha(p) for p in destination.iterdir() if p.is_file()}})
    return {"report": str(destination), "cohorts": summary["cohorts"], "review_queue_responses": len(findings), "execution": execution}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", default=DEFAULT_OUTPUT)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(report(args.output, args.destination or args.output / "report"), indent=2))
