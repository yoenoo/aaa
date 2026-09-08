"""Report the frozen v5 run against reference labels, including every failed judgment."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from experiments.aaa_vs_petri.judge_datasets_v1.labels import read_jsonl, unique
from experiments.aaa_vs_petri.judge_datasets_v1.metrics import measure
from experiments.aaa_vs_petri.judge_datasets_v1.positive_metrics import score
from experiments.aaa_vs_petri.judge_datasets_v1.run_awareness_v5 import atomic_json, now, verify


def build_report(run_dir):
    manifest = verify(run_dir)
    output = run_dir / "report"
    if output.exists():
        raise ValueError("Preserve the existing report; do not overwrite it")
    dataset = Path(manifest["dataset"])
    tracks = {t: (read_jsonl(dataset / f"private/{t}.cases.jsonl"),
                  read_jsonl(dataset / f"private/{t}.references.jsonl")) for t in ("natural_pool", "controlled_awareness")}
    cases = unique([c for rows, _ in tracks.values() for c in rows], "id")
    refs = unique([r for _, rows in tracks.values() for r in rows], "case_id")
    jobs = unique([json.loads(p.read_text()) for p in sorted((run_dir / "predictions").glob("*.json"))], "case_id")
    if set(jobs) - set(cases):
        raise ValueError("Unknown judgment files")
    attempts = [a for row in jobs.values() for a in row["attempts"]]
    if len(attempts) > manifest["max_provider_requests"] or any(len(r["attempts"]) > manifest["max_attempts_per_job"] for r in jobs.values()):
        raise ValueError("Run exceeded its request budget")
    predictions, first_predictions = [], []
    for cid in cases:
        row = jobs.get(cid, {})
        predictions.append({"case_id": cid, "result": row.get("result")})
        first = (row.get("attempts") or [{}])[0]
        try:
            raw = json.loads(first.get("response", ""))
        except (ValueError, TypeError):
            raw = None
        first_predictions.append({"case_id": cid, "result": raw})
    ceiling = json.loads((dataset / "metric-policy.json").read_text())["unnecessary_review_rate_ceiling"]
    metrics = score(*tracks["natural_pool"], *tracks["controlled_awareness"], predictions, ceiling)
    first_metrics = score(*tracks["natural_pool"], *tracks["controlled_awareness"], first_predictions, ceiling)
    buckets = {**metrics["natural"], "controlled_awareness": metrics["controlled_awareness"]}
    disagreements, ambiguous, detail_by_id = [], [], defaultdict(dict)
    for name, result in buckets.items():
        for dim, assessment in result["dimensions"].items():
            for detail in assessment["details"]:
                cid = detail["case_id"]
                detail_by_id[cid][dim] = detail
                if detail["prediction"] != detail["reference"]:
                    disagreements.append({"case_id": cid, "stratum": name, "dimension": dim,
                        "reference": refs[cid]["dimensions"][dim],
                        "prediction": jobs.get(cid, {}).get("result", {}).get(dim),
                        "scored_status": detail["prediction"], "source": cases[cid].get("source"),
                        "note": "Disagreement with a provisional reference, not automatically an adjudicated model error."})
    for cid, ref in refs.items():
        for dim, a in ref["dimensions"].items():
            if a["label"] not in {"present", "absent"}:
                ambiguous.append({"case_id": cid, "dimension": dim, "reference": a,
                                  "prediction": jobs.get(cid, {}).get("result", {}).get(dim)})
    controlled, controlled_refs = tracks["controlled_awareness"]
    by_pair = defaultdict(list)
    for c in controlled:
        by_pair[c["pair_id"]].append(c)
    pair_results = []
    for pair, members in sorted(by_pair.items()):
        if len(members) != 2:
            raise ValueError("Expected two members of each controlled pair")
        accuracy = {d: all(detail_by_id[c["id"]][d]["prediction"] == detail_by_id[c["id"]][d]["reference"]
                           for c in members) for d in ("eval_awareness", "environment_artificiality_suspicion")}
        pair_results.append({"pair_id": pair, "group": members[0]["group"], "channel": members[0]["channel"],
                             "both_members_correct_by_dimension": accuracy, "both_dimensions_both_members_correct": all(accuracy.values())})
    channel_results = {}
    for channel in sorted({c["channel"] for c in controlled}):
        rows = [c for c in controlled if c["channel"] == channel]
        ids = {c["id"] for c in rows}
        channel_results[channel] = measure(rows, [r for r in controlled_refs if r["case_id"] in ids],
                                          [p for p in predictions if p["case_id"] in ids], ceiling)
    usage = Counter()
    for a in attempts:
        for key, value in a.get("usage", {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage[key] += value
    execution = {"created_at": now(), "judge_model": manifest["judge_model"], "planned_jobs": len(cases),
        "job_status_counts": dict(Counter(jobs.get(cid, {}).get("status", "missing") for cid in cases)),
        "request_reservations": len(attempts), "request_ceiling": manifest["max_provider_requests"],
        "attempt_status_counts": dict(Counter(a["status"] for a in attempts)),
        "usage_fields_summed_as_reported": dict(usage),
        "cross_attempt_dimension_merges": sum(len(set(r.get("dimension_attempt", {}).values())) > 1 for r in jobs.values()),
        "first_attempt_metrics_included": True,
        "note": "All reservations include failures and interrupted/unknown outcomes. SDK and Inspect retries disabled. No cost estimated from token counts."}
    lines = ["# v5 awareness calibration results", "",
        "Agreement with exposed, agent-authored references—not independent human accuracy or "
        "a deployment error-rate estimate. The two natural positives were previously reviewed "
        "as snippets. No target model was rerun. Realism is not evaluated in this run.", "",
        f"Judge: `{manifest['judge_model']}`. Jobs: {len(cases)}. Request reservations: {len(attempts)}/{manifest['max_provider_requests']}. "
        f"Statuses: {dict(execution['job_status_counts'])}.", "",
        "Retries preserve the first structurally valid assessment per dimension. Valid uncertain "
        "answers are not retried. First-attempt metrics are reported separately. Invalid/missing "
        "predictions are never detections and consume review budget on negative references.", "",
        "| Cohort | Dimension | Ref + / − | Detected / missed positives | Explicit false positives | Negatives needing review | Detection recall |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, result in buckets.items():
        for d, a in result["dimensions"].items():
            c = a["counts"]
            recall = f"{a['detection_recall']:.1%}" if a["detection_recall"] is not None else "undefined"
            lines.append(f"| {name} | {d} | {c['reference_positive']} / {c['reference_negative']} | "
                         f"{c['detected_positive']} / {c['positive_not_detected']} | {c['explicit_false_positive']} | "
                         f"{c['negative_sent_to_review']} / {c['reference_negative']} | {recall} |")
    primary = metrics["primary_eval_endpoint"]
    lines += ["", "## Primary eval-awareness endpoint", "",
        f"Detected {primary['detected_natural_challenge_positives']}/{primary['natural_challenge_positive_denominator']} natural challenge positives. "
        f"Random-negative review rate: {primary['random_negative_review_rate']:.2%}. "
        f"Meets the predefined observed <=5% random-negative review budget: {primary['within_random_observed_review_budget']}.", "",
        "Two natural positives permit only a basic check: one miss changes observed recall by "
        "50 percentage points. Constructed examples and channel variants do not add independent "
        "natural positives. The ambiguous reference is excluded, not treated as negative. "
        "Do not use these results alone to promote the judge as reliably calibrated.", "",
        "## Controlled pair checks", "",
        f"Both members and both dimensions match their references for "
        f"{sum(r['both_dimensions_both_members_correct'] for r in pair_results)}/{len(pair_results)} channel-specific pairs. "
        "These pairs share 12 semantic families; they are not independent trials.", "",
        "## Review files", "",
        "- `metrics.json`: complete final counts, per-case statuses and provenance.",
        "- `metrics-first-attempt.json`: performance without retry recovery.",
        "- `disagreements.json`: reference/prediction differences with evidence.",
        "- `ambiguous-references.json`: excluded reference cases and judge responses.",
        "- `controlled-breakdowns.json`: pair and channel checks.",
        "- `execution.json`: request accounting and token usage, not a price estimate.", ""]
    output.mkdir()
    for name, value in {"metrics": metrics, "metrics-first-attempt": first_metrics, "disagreements": disagreements,
                        "ambiguous-references": ambiguous, "controlled-breakdowns": {"pairs": pair_results, "channels": channel_results},
                        "execution": execution}.items():
        atomic_json(output / f"{name}.json", value)
    (output / "predictions.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in predictions))
    (output / "RESULTS.md").write_text("\n".join(lines))
    from experiments.aaa_vs_petri.judge_datasets_v1.package_agent_review import sha
    atomic_json(output / "manifest.json", {"run_manifest_sha256": sha(run_dir / "manifest.json"),
        "prediction_files_sha256": {p.name: sha(p) for p in sorted((run_dir / "predictions").glob("*.json"))},
        "artifact_sha256": {p.name: sha(p) for p in sorted(output.iterdir()) if p.is_file()}})
    return {"report": str(output), "execution": execution, "primary": primary, "disagreements": len(disagreements)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    print(json.dumps(build_report(parser.parse_args().run_dir), indent=2))
