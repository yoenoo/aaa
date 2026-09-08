"""Apply the unchanged calibrated v5 judge to all recorded Petri target responses."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import fcntl
import importlib.metadata
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from inspect_ai.log import read_eval_log
from awareness_v5 import payload, prompt, response_schema, validate_response
from transcript import _text
from experiments.aaa_vs_petri.judge_datasets_v1.build import ALIASES, digest, family, opaque, sha
from experiments.aaa_vs_petri.judge_datasets_v1.labels import read_jsonl, unique, verify_dataset
from experiments.aaa_vs_petri.judge_datasets_v1 import run_awareness_v5 as engine
from experiments.aaa_vs_petri.judge_validation_v4.corpus import SOURCES, calls, recorded_packet, render

PREVIOUS = ROOT / "logs/judge-v5-runs/positive-awareness-v2-opus48"
DEFAULT_OUTPUT = ROOT / "logs/petri-awareness-v5/all-recorded-opus48"
EXPECTED = {"responses": 398, "completed_responses": 397, "completed_audits": 18,
            "incomplete_audits": 1, "reused_jobs": 62, "new_jobs": 336}


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def target_events(sample):
    return [e for e in sample.events if e.event == "model" and e.role == "target" and e.output and not e.error]


def last_membership(event, last):
    """Exact recorded output in the last target request, not an inferred final branch."""
    if event.uuid == last.uuid:
        return "latest_output"
    message = event.output.message
    candidates = [m for m in last.input if m.role == "assistant" and m.id and m.id == message.id]
    if not candidates:
        return "not_in_last_request"
    if any(_text(message.content)[:2] == _text(m.content)[:2] and calls(message) == calls(m)
           for m in candidates):
        return "exact_history_match"
    return "id_only_match_unknown"


def insert_sample(seen, sample_id, cases, metadata, path):
    """Scored copies are duplicates only if all event IDs and scoring inputs agree."""
    signature = [(c["source"]["target_event_uuid"], c["packet_sha256"],
                  c["last_conversation_membership"], c["segment"]) for c in cases]
    if sample_id in seen:
        prior = seen[sample_id]
        if prior["signature"] != signature or prior["metadata"]["cohort"] != metadata["cohort"]:
            raise ValueError(f"Conflicting copies of sample {sample_id}; do not choose silently")
        prior["metadata"]["duplicate_paths"].append(path)
        return False
    metadata["duplicate_paths"] = []
    seen[sample_id] = {"signature": signature, "cases": cases, "metadata": metadata}
    return True


def collect():
    preferred = {p.resolve(): i for i, p in enumerate(SOURCES)}
    paths = sorted((ROOT / "logs/petri-trajectories").rglob("*.eval"),
                   key=lambda p: (preferred.get(p.resolve(), len(preferred)), str(p)))
    seen, inventory = {}, []
    for path in paths:
        relative, source_hash = str(path.relative_to(ROOT)), sha(path)
        log = read_eval_log(path, resolve_attachments="full")  # Fail closed on unreadable sources.
        inventory.append({"path": relative, "sha256": source_hash, "status": log.status,
                          "sample_uuids": [s.uuid for s in log.samples or []]})
        for sample in log.samples or []:
            events = target_events(sample)
            seed = str((sample.metadata or {}).get("source_scenario", sample.id))
            seed = ALIASES.get(seed, seed)
            cohort = "incomplete_attempt" if sample.error else "completed_audit"
            rollbacks = [e for e in sample.events if e.event == "tool"
                         and e.function in {"rollback_conversation", "restart_conversation"}
                         and not e.error and not getattr(e, "failed", False)]
            cases = []
            for index, event in enumerate(events):
                packet = payload(recorded_packet(event))
                cases.append({"id": opaque("natural", f"{sample.uuid}:{event.uuid}"),
                    "payload": packet, "packet_sha256": digest(packet), "audit_id": sample.uuid,
                    "seed": seed, "group": family(seed), "cohort": cohort,
                    "segment": 1 + sum(e.timestamp < event.timestamp for e in rollbacks),
                    "last_conversation_membership": last_membership(event, events[-1]),
                    "target_model": event.model,
                    "source": {"path": relative, "sha256": source_hash, "sample_uuid": sample.uuid,
                               "target_event_uuid": event.uuid, "target_event_index": index,
                               "output_message_id": event.output.message.id},
                    "reference_status": "unlabeled_application_not_accuracy_evaluation"})
            metadata = {"audit_id": sample.uuid, "seed": seed, "group": family(seed), "cohort": cohort,
                        "source_path": relative, "target_responses": len(events),
                        "source_sample_error": bool(sample.error),
                        "excluded_target_events": sum(e.event == "model" and e.role == "target"
                                                      and (not e.output or bool(e.error)) for e in sample.events)}
            insert_sample(seen, sample.uuid, cases, metadata, relative)
    cases = sorted([c for audit in seen.values() for c in audit["cases"]], key=lambda c: c["id"])
    unique(cases, "id")
    return cases, {"files": inventory, "audits": [a["metadata"] for _, a in sorted(seen.items())],
                   "deduplication": "Sample UUID + ordered target event UUIDs, exact scoring payload hashes, segment and last-conversation membership; conflicting copies abort."}


def check_cached(case, prior_input, prediction):
    if prior_input != {"id": case["id"], "payload": case["payload"]}:
        raise ValueError("Cache input identity or exact payload differs")
    if prediction.get("case_id") != case["id"] or prediction.get("model") != engine.MODEL:
        raise ValueError("Cache identity or model differs")
    if prediction.get("status") != "success" or not prediction.get("attempts"):
        raise ValueError("Only completed cached judgments can be reused")
    valid = validate_response(prediction["result"], case["payload"])
    if not all(d["valid"] for d in valid["dimensions"].values()):
        raise ValueError("Cached judgment is not valid under the unchanged v5 schema")


def prepare(output):
    output = output.resolve()
    if output.exists():
        raise ValueError("Choose a new output directory; never overwrite an earlier run")
    previous_manifest = engine.verify(PREVIOUS)
    previous_report = json.loads((PREVIOUS / "report/manifest.json").read_text())
    if previous_report["run_manifest_sha256"] != sha(PREVIOUS / "manifest.json"):
        raise ValueError("Prior report/run manifest identity changed")
    if (PREVIOUS / "prompt.txt").read_text() != prompt():
        raise ValueError("Calibrated prompt changed")
    if json.loads((PREVIOUS / "schemas.json").read_text())["semantic"] != response_schema():
        raise ValueError("Calibrated schema changed")
    cases, inventory = collect()
    old_inputs = unique(read_jsonl(PREVIOUS / "inputs.jsonl"), "id")
    reused = {}
    for case in cases:
        if case["id"] not in old_inputs:
            continue
        path = PREVIOUS / "predictions" / f"{case['id']}.json"
        if sha(path) != previous_report["prediction_files_sha256"][path.name]:
            raise ValueError("Frozen cached prediction changed")
        row = json.loads(path.read_text())
        check_cached(case, old_inputs[case["id"]], row)
        reused[case["id"]] = {"path": str(path.relative_to(ROOT)), "sha256": sha(path),
                               "historical_request_reservations": len(row["attempts"])}
    counts = {"responses": len(cases), "completed_responses": sum(c["cohort"] == "completed_audit" for c in cases),
              "completed_audits": sum(a["cohort"] == "completed_audit" for a in inventory["audits"]),
              "incomplete_audits": sum(a["cohort"] == "incomplete_attempt" for a in inventory["audits"]),
              "reused_jobs": len(reused), "new_jobs": len(cases) - len(reused)}
    if counts != EXPECTED:
        raise ValueError(f"Corpus/request scope changed; inspect before sending: {counts}")
    output.mkdir(parents=True)
    for name in ("predictions", "reused_predictions", "private", "packets"):
        (output / name).mkdir()
    all_inputs = [{"id": c["id"], "payload": c["payload"]} for c in cases]
    write_jsonl(output / "all-inputs.jsonl", all_inputs)
    write_jsonl(output / "inputs.jsonl", [c for c in all_inputs if c["id"] not in reused])
    write_jsonl(output / "private/cases.jsonl", [{**{k: v for k, v in c.items() if k != "payload"},
                     "judgment_origin": "reused_calibration" if c["id"] in reused else "new_application"} for c in cases])
    engine.atomic_json(output / "private/source-inventory.json", inventory)
    engine.atomic_json(output / "private/reuse-provenance.json", reused)
    for case in cases:
        (output / "packets" / f"{case['id']}.md").write_text(render(case["id"], case["payload"]))
    for cid, entry in reused.items():
        (output / "reused_predictions" / f"{cid}.json").write_bytes((ROOT / entry["path"]).read_bytes())
    for name in ("prompt.txt", "schemas.json"):
        (output / name).write_bytes((PREVIOUS / name).read_bytes())
    dependencies = dict(previous_manifest["code_sha256"])
    for path in (Path(__file__), Path(__file__).with_name("report.py"),
                 ROOT / "experiments/aaa_vs_petri/judge_datasets_v1/build.py",
                 ROOT / "experiments/aaa_vs_petri/judge_validation_v4/corpus.py", ROOT / "src/transcript.py"):
        dependencies[str(path.relative_to(ROOT))] = sha(path)
    manifest = {"created_at": engine.now(), "version": "petri-all-recorded-awareness-v5", "counts": counts,
        "judge_model": engine.MODEL, "planned_jobs": counts["new_jobs"], "max_attempts_per_job": 3,
        "max_provider_requests": counts["new_jobs"] * 3,
        **{k: previous_manifest[k] for k in ("automatic_inspect_retries", "automatic_sdk_retries",
            "max_concurrency", "max_tokens", "timeout_seconds", "cache_prompt", "streaming",
            "generation_policy", "retry_policy", "runtime_versions")},
        "reference_policy": "No reference labels, scores, source metadata or calibration selection information sent. Application findings, not an accuracy study.",
        "scope": "Every successful recorded Petri target output, including rolled-back outputs. An aborted setup sample is supplemental, outside completed-audit denominators. No target reruns, no live environment tools, local Inspect judge execution (not Modal).",
        "last_conversation_definition": "The last successful target request's exact assistant-history outputs plus its new output; not a claim about subsequent auditor edits or unrecorded context.",
        "approval_context": "User requested running the calibrated judge on existing Petri audit transcripts in a new folder. Scope communicated: 398 outputs, 62 exact cached results, 336 new jobs, at most 1008 new requests.",
        "previous_run": str(PREVIOUS), "previous_manifest_sha256": sha(PREVIOUS / "manifest.json"),
        "previous_report_manifest_sha256": sha(PREVIOUS / "report/manifest.json"),
        "historical_cached_requests": sum(v["historical_request_reservations"] for v in reused.values()),
        "code_sha256": dependencies,
        "artifact_sha256": {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob("*")) if p.is_file()}}
    engine.atomic_json(output / "manifest.json", manifest)
    return {"prepared": str(output), **counts, "max_new_requests": manifest["max_provider_requests"], "paid_calls": 0}


def verify(output):
    m = verify_dataset(output)
    if m["counts"] != EXPECTED or m["judge_model"] != engine.MODEL or m["planned_jobs"] != 336 or m["max_provider_requests"] != 1008 or m["max_attempts_per_job"] != 3:
        raise ValueError("Frozen corpus/model/budget differs from approved scope")
    for name, expected in m["code_sha256"].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"Frozen dependency changed: {name}")
    for name, expected in m["runtime_versions"].items():
        if importlib.metadata.version(name) != expected:
            raise ValueError(f"Runtime changed: {name}")
    for source in json.loads((output / "private/source-inventory.json").read_text())["files"]:
        if sha(ROOT / source["path"]) != source["sha256"]:
            raise ValueError(f"Frozen source changed: {source['path']}")
    engine.verify(PREVIOUS)
    if sha(PREVIOUS / "manifest.json") != m["previous_manifest_sha256"] or sha(PREVIOUS / "report/manifest.json") != m["previous_report_manifest_sha256"]:
        raise ValueError("Prior calibration provenance changed")
    return m


async def run(output, *, concurrency=6, canary_only=False):
    m = verify(output)
    if not 1 <= concurrency <= m["max_concurrency"]:
        raise ValueError("Concurrency outside frozen limit")
    with (output / ".run.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        from inspect_ai._util.dotenv import init_dotenv
        from inspect_ai.model import GenerateConfig, get_model
        from inspect_ai.model._providers import anthropic
        init_dotenv()
        model = get_model(m["judge_model"], config=GenerateConfig(max_connections=concurrency,
            max_retries=0, timeout=m["timeout_seconds"], max_tokens=m["max_tokens"], cache_prompt=m["cache_prompt"]),
            max_retries=0, streaming=False)
        try:
            if model.api.client.max_retries != 0:
                raise ValueError("Automatic SDK retries must be disabled")
            with patch.object(anthropic, "set_additional_properties_false", engine.object_only_additional_properties):
                result = await engine.execute(output, m, model, concurrency=concurrency, canary_only=canary_only)
        finally:
            await model.api.aclose()
        engine.atomic_json(output / "progress.json", {**result, "recorded_at": engine.now(), "canary_only": canary_only})
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "verify", "run"])
    parser.add_argument("output", type=Path, nargs="?", default=DEFAULT_OUTPUT)
    parser.add_argument("--approved-paid-run", action="store_true")
    parser.add_argument("--canary-only", action="store_true")
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare(args.output)
    elif args.action == "verify":
        result = {"verified": str(args.output), "counts": verify(args.output)["counts"]}
    else:
        if not args.approved_paid_run:
            parser.error("Explicit paid-run approval required")
        result = asyncio.run(run(args.output, concurrency=args.concurrency, canary_only=args.canary_only))
    print(json.dumps(result, indent=2), flush=True)
