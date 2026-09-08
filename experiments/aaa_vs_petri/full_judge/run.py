"""Prepare/run a bounded two-judge full Petri rejudgment; no target execution."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from copy import deepcopy
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
from transcript import _text
from experiments.aaa_vs_petri.export_rejudged import target_message_ids, verify_report
from experiments.aaa_vs_petri.export_viewer import response_events
from experiments.aaa_vs_petri.judge_validation_v4.corpus import SOURCES, calls, recorded_packet
from experiments.aaa_vs_petri.judge_datasets_v1.build import digest
from experiments.aaa_vs_petri.judge_datasets_v1.run_awareness_v5 import (
    MODEL, PACKAGES, atomic_json, inline_schema, now, object_only_additional_properties, sha,
)
from experiments.aaa_vs_petri.full_judge import spec

DEFAULT = ROOT / "logs/petri-full-judge/integrated-v1-opus48"
PREVIOUS = ROOT / "logs/petri-awareness-v5/all-recorded-opus48"


def build_packet(sample):
    targets = [e for e in sample.events if e.event == "model" and e.role == "target" and e.output and not e.error]
    if not targets or sample.error:
        raise ValueError("Only completed populated audits are in scope")
    anchors = target_message_ids(sample)
    by_resume, _ = response_events(sample)
    positions = {e.uuid: index for index, e in enumerate(targets)}
    rollbacks = [e for e in sample.events if e.event == "tool"
                 and e.function in {"rollback_conversation", "restart_conversation"}
                 and not e.error and not getattr(e, "failed", False)]
    records, requests, mapping, cache = [], [], {}, {}
    for index, event in enumerate(targets):
        branch = 1 + sum(e.timestamp < event.timestamp for e in rollbacks)
        packet = recorded_packet(event)
        input_ids = []
        for record in packet["records"][:-1]:
            body = {k: v for k, v in record.items() if k not in {"id", "branch"}}
            key = digest(body)
            if key not in cache:
                rid = f"input-{len(cache) + 1:04d}"
                cache[key] = rid
                records.append({"id": rid, **body})
                mapping[rid] = {"viewer_event_id": anchors[event.uuid], "actor": body["actor"], "occurrences": []}
            rid = cache[key]
            mapping[rid]["occurrences"].append({"request_index": index, "source_record_id": record["id"]})
            input_ids.append(rid)
        output_id = f"target-{index + 1:04d}"
        records.append({**packet["records"][-1], "id": output_id, "branch": branch})
        mapping[output_id] = {"viewer_event_id": anchors[event.uuid], "actor": "target",
            "target_event_uuid": event.uuid, "target_event_index": index, "branch": branch}
        requests.append({"id": f"request-{index + 1:04d}", "branch": branch, "input_ids": input_ids,
                         "output_id": output_id, "coverage": packet["coverage"]})
    auditor_ids = []
    for index, message in enumerate(sample.messages):
        rid = f"audit-{index + 1:04d}"
        record = {"id": rid, "actor": "auditor_context", "author_role": message.role,
                  "text": _text(message.content)[0]}
        if message.role == "assistant":
            record["tool_calls_json"] = json.dumps(calls(message), ensure_ascii=False, sort_keys=True) if message.tool_calls else ""
        if message.role == "tool" and message.tool_call_id in by_resume:
            event = by_resume[message.tool_call_id]
            record["text"] = ""
            record["target_output_id"] = f"target-{positions[event.uuid] + 1:04d}"
        records.append(record)
        auditor_ids.append(rid)
        mapping[rid] = {"viewer_event_id": f"e{index}" if message.role != "system" else None, "actor": "auditor_context"}
    packet = {"coverage": "text_only_audit" if any(r.get("nontext_omitted") for r in records) else "complete_recorded_audit",
        "limitations": "All recorded target requests and generated outputs. Deduplicated records are referenced in exact request order, not concatenated across branches. Auditor-only context is separated; resume wrappers reference authoritative target outputs. This does not establish independently executed world state, full private cognition or unrecorded real-world history.",
        "records": records, "requests": requests, "auditor_message_ids": auditor_ids}
    check_packet(packet)
    # Lossless within the recorded_packet representation: rebuild every request
    # and output independently, including source actor, channels and tool calls.
    by_id = {r["id"]: r for r in records}
    for request, event in zip(requests, targets):
        actual = [by_id[rid] for rid in request["input_ids"] + [request["output_id"]]]
        expected = recorded_packet(event)["records"]
        strip = lambda r: {k: v for k, v in r.items() if k not in {"id", "branch"}}
        if [strip(r) for r in actual] != [strip(r) for r in expected]:
            raise ValueError("Deduplication changed a target request")
    return packet, mapping


def check_packet(packet):
    records = {r["id"]: r for r in packet["records"]}
    if len(records) != len(packet["records"]):
        raise ValueError("Duplicate record IDs")
    outputs = []
    for request in packet["requests"]:
        if any(rid not in records or records[rid]["actor"] in {"target", "auditor_context"} for rid in request["input_ids"]):
            raise ValueError("Invalid recorded input references")
        output_id = request["output_id"]
        if output_id not in records or records[output_id]["actor"] != "target":
            raise ValueError("Missing generated target output")
        outputs.append(output_id)
    if len(outputs) != len(set(outputs)) or set(outputs) != {r["id"] for r in records.values() if r["actor"] == "target"}:
        raise ValueError("Generated output coverage differs")


def prepare(output):
    output = output.resolve()
    if output.exists():
        raise ValueError("Choose a fresh run directory")
    verify_report(PREVIOUS)
    packets, audits, sources = {}, [], {}
    for path in SOURCES:
        log = read_eval_log(path, resolve_attachments="full")
        if log.eval.model_roles["auditor"].model != MODEL:
            raise ValueError("Unexpected auditor model")
        sources[str(path.relative_to(ROOT))] = sha(path)
        for sample in log.samples or []:
            if sample.error or sample.uuid in packets:
                raise ValueError("Unexpected incomplete/duplicate audit")
            targets = [e for e in sample.events if e.event == "model" and e.role == "target"]
            if any(e.model != "google/gemini-3.1-pro-preview" or e.error for e in targets):
                raise ValueError("Unexpected target model/error")
            packet, mapping = build_packet(sample)
            packets[sample.uuid] = packet
            audits.append({"id": sample.uuid, "seed": sample.metadata["source_scenario"],
                "source": str(path.relative_to(ROOT)), "source_sha256": sha(path),
                "target_outputs": len(packet["requests"]), "record_mapping": mapping})
    if len(audits) != 18 or sum(a["target_outputs"] for a in audits) != 397:
        raise ValueError("Approval covers exactly 18 completed audits / 397 outputs")
    output.mkdir(parents=True)
    for name in ("private", "inputs", "prompts", "predictions", "exchanges"):
        (output / name).mkdir()
    schemas, jobs = {}, []
    from inspect_ai.model import ResponseSchema
    from inspect_ai.util._json import JSON_SCHEMA_EXTENDED_FIELDS, json_schema_dump
    for family in spec.FAMILIES:
        semantic = spec.schema(family)
        inlined = inline_schema(semantic)
        transported = ResponseSchema(name=family, json_schema=inlined).json_schema
        object_only_additional_properties(transported)
        schemas[family] = {"semantic": semantic, "inlined": inlined,
                           "provider_projection": json_schema_dump(transported, exclude=JSON_SCHEMA_EXTENDED_FIELDS)}
        (output / "prompts" / f"{family}.txt").write_text(spec.prompt(family))
        for audit in audits:
            job = f"{audit['id']}-{family}"
            packet = spec.visible(packets[audit["id"]], family)
            text = json.dumps(packet, ensure_ascii=False)
            # Preserve exact application input bytes separately from metadata.
            (output / "inputs" / f"{job}.json").write_text(text)
            jobs.append({"id": job, "audit_id": audit["id"], "family": family, "input_chars": len(text)})
    atomic_json(output / "schemas.json", schemas)
    atomic_json(output / "private/audits.json", audits)
    atomic_json(output / "private/frozen-v5-audits.json", json.loads((PREVIOUS / "report/audits.json").read_text()))
    atomic_json(output / "jobs.json", jobs)
    dependencies = [*Path(__file__).parent.glob("*.py"), ROOT / "src/awareness_v5.py", ROOT / "src/judge_v4.py",
        ROOT / "src/prompts/__init__.py", ROOT / "src/prompts/awareness_v5.txt", ROOT / "src/transcript.py",
        ROOT / "experiments/aaa_vs_petri/export_rejudged.py", ROOT / "experiments/aaa_vs_petri/export_viewer.py",
        ROOT / "experiments/aaa_vs_petri/judge_validation_v4/corpus.py",
        ROOT / "experiments/aaa_vs_petri/judge_datasets_v1/run_awareness_v5.py",
        ROOT / "experiments/aaa_vs_petri/judge_v4_transport_adapter.py",
        ROOT / "experiments/aaa_vs_petri/judge_v4_transport_repair.py",
        *sorted((ROOT / "src/prompts/judges").glob("*/*"))]
    manifest = {"version": "full-audit-integration-v1", "created_at": now(), "judge_model": MODEL,
        "families": list(spec.FAMILIES), "completed_audits": 18, "target_outputs": 397,
        "planned_jobs": 36, "max_provider_requests": 108, "max_attempts_per_job": 3,
        "max_tokens": 16000, "timeout_seconds": 300, "max_concurrency": 6,
        "execution_backend": "modal", "modal_function_retries": 0,
        "automatic_sdk_retries": 0, "automatic_inspect_retries": 0, "streaming": False, "cache_prompt": "auto",
        "dimension_counts": {"scheming_numeric": 31, "scheming_categorical_awareness": 2, "debug_numeric": 14},
        "configuration_note": "New full-audit integration using v5 awareness definitions and v4 debugging safeguards, NOT the calibrated standalone per-response v5 configuration. Compare to frozen v5 detection results as a regression check, not independent accuracy.",
        "approval": "User explicitly approved 36 full-judge calls to Claude Opus 4.8 on the 18 completed Petri transcripts, up to 108 requests; no target/tool reruns.",
        "retry_policy": "Only transport, JSON and structural/evidence validation failures; never retry a valid low score, absent, uncertain or unassessable result. First valid whole-family result wins. Durable reservations count unknown/interrupted attempts. No fallback models or changed-prompt retries.",
        "source_sha256": sources,
        "frozen_v5_report_manifest_sha256": sha(PREVIOUS / "report/manifest.json"),
        "runtime_versions": {p: importlib.metadata.version(p) for p in PACKAGES},
        "code_sha256": {str(p.relative_to(ROOT)): sha(p) for p in dependencies if p.is_file()},
        "artifact_sha256": {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}}
    atomic_json(output / "manifest.json", manifest)
    return {"prepared": str(output), "jobs": len(jobs), "request_ceiling": 108,
            "input_characters": {"min": min(j["input_chars"] for j in jobs), "max": max(j["input_chars"] for j in jobs)}, "paid_calls": 0}


def verify(output):
    m = json.loads((output / "manifest.json").read_text())
    for key, base in (("artifact_sha256", output), ("code_sha256", ROOT), ("source_sha256", ROOT)):
        for relative, expected in m[key].items():
            if sha(base / relative) != expected:
                raise ValueError(f"Frozen {key} changed: {relative}")
    for package, version in m["runtime_versions"].items():
        if importlib.metadata.version(package) != version:
            raise ValueError("Runtime changed")
    if (m["judge_model"], m["planned_jobs"], m["max_provider_requests"], m["max_attempts_per_job"]) != (MODEL, 36, 108, 3):
        raise ValueError("Approved scope changed")
    return m


def terminal_provider_error(error):
    code = getattr(error, "status_code", None)
    text = str(error).lower()
    return code in {400, 401, 403, 404} or any(marker in text for marker in (
        "specified workspace api usage limits", "schema type is missing", "invalid x-api-key",
        "invalid_request_error", "authentication_error", "permission_error"))


async def execute(output, manifest, model, *, canary_only=False):
    from inspect_ai.model import ChatMessageSystem, ChatMessageUser, GenerateConfig, ResponseSchema
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    jobs = json.loads((output / "jobs.json").read_text())
    schemas = json.loads((output / "schemas.json").read_text())
    prompts = {family: (output / "prompts" / f"{family}.txt").read_text() for family in spec.FAMILIES}
    rows = {}
    valid_ids = {job["id"] for job in jobs}
    for path in (output / "predictions").glob("*.json"):
        row = json.loads(path.read_text())
        if row["id"] != path.stem or row["id"] not in valid_ids or len(row["attempts"]) > 3 or row["model"] != MODEL:
            raise ValueError("Invalid saved job state")
        for attempt in row["attempts"]:
            if attempt["status"] == "reserved":
                attempt["status"] = "interrupted_outcome_unknown"
        rows[row["id"]] = row
        atomic_json(path, row)
    total = sum(len(row["attempts"]) for row in rows.values())
    if total > manifest["max_provider_requests"]:
        raise ValueError("Request ceiling exceeded")
    sem = asyncio.Semaphore(manifest["max_concurrency"])

    async def one(job):
        nonlocal total
        jid, family = job["id"], job["family"]
        path = output / "predictions" / f"{jid}.json"
        row = rows.setdefault(jid, {**job, "model": MODEL, "status": "pending", "attempts": []})
        text = (output / "inputs" / f"{jid}.json").read_text()
        packet = json.loads(text)
        if row["status"] == "success":
            spec.validate(row["result"], packet, family)
            return
        if row["status"] == "failed":
            return
        messages = [ChatMessageSystem(content=prompts[family]), ChatMessageUser(content=text)]
        config = GenerateConfig(response_schema=ResponseSchema(name=family, json_schema=schemas[family]["inlined"]), max_retries=0)
        async with sem:
            while len(row["attempts"]) < manifest["max_attempts_per_job"] and total < manifest["max_provider_requests"]:
                attempt = {"number": len(row["attempts"]) + 1, "reserved_at": now(), "status": "reserved"}
                row["attempts"].append(attempt)
                total += 1
                atomic_json(path, row)  # reserve durably before any network await
                previous = transcript()
                capture = Transcript()
                init_transcript(capture)
                fatal = False
                try:
                    reply = await model.generate(messages, config=config)
                    attempt.update(response=reply.completion, model_output=reply.model_dump(mode="json"),
                                   usage=reply.usage.model_dump(mode="json") if reply.usage else {}, stop_reason=reply.stop_reason)
                    row["result"] = spec.validate(json.loads(reply.completion), packet, family)
                    row["status"] = attempt["status"] = "success"
                except Exception as error:
                    attempt.update(status="error", error_type=type(error).__name__, error=str(error))
                    fatal = terminal_provider_error(error)
                finally:
                    attempt["completed_at"] = now()
                    attempt["model_events"] = [e.model_dump(mode="json") for e in capture.events if e.event == "model"]
                    init_transcript(previous)
                    atomic_json(path, row)
                if fatal:
                    raise RuntimeError(f"Provider rejected {jid}; details saved privately in predictions. Stop, no blind retries.")
                if row["status"] == "success":
                    break
            if row["status"] != "success":
                row["status"] = "failed"
            atomic_json(path, row)
            print(f"{row['status']}: {jid}; attempts={len(row['attempts'])}; requests={total}/108", flush=True)

    # A genuine scheduled job for each schema doubles as its canary.
    first_audit = jobs[0]["audit_id"]
    canaries = [j for j in jobs if j["audit_id"] == first_audit]
    for job in canaries:
        await one(job)
        if rows[job["id"]]["status"] != "success":
            raise RuntimeError("Canary failed validation; inspect before continuing")
    if not canary_only:
        tasks = [asyncio.create_task(one(job)) for job in jobs if job not in canaries]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
    return {"requests_reserved": total, "job_status_counts": dict(Counter(r["status"] for r in rows.values())), "canary_only": canary_only}


async def run(output, canary_only=False):
    m = verify(output)
    with (output / ".run.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        from inspect_ai._util.dotenv import init_dotenv
        from inspect_ai.model import GenerateConfig, get_model
        from inspect_ai.model._providers import anthropic
        init_dotenv()
        model = get_model(MODEL, config=GenerateConfig(max_connections=m["max_concurrency"], max_retries=0,
            timeout=m["timeout_seconds"], max_tokens=m["max_tokens"], cache_prompt="auto"), max_retries=0, streaming=False)
        if model.api.client.max_retries != 0:
            raise ValueError("SDK retries must be disabled")
        try:
            with patch.object(anthropic, "set_additional_properties_false", object_only_additional_properties):
                result = await execute(output, m, model, canary_only=canary_only)
        finally:
            await model.api.aclose()
        atomic_json(output / "progress.json", {**result, "recorded_at": now()})
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "verify"])
    parser.add_argument("output", type=Path, nargs="?", default=DEFAULT)
    parser.add_argument("--approved-paid-run", action="store_true")
    parser.add_argument("--canary-only", action="store_true")
    args = parser.parse_args()
    if args.action == "run" and not args.approved_paid_run:
        parser.error("Explicit paid-run approval is required")
    result = (prepare(args.output) if args.action == "prepare" else verify(args.output) if args.action == "verify"
              else asyncio.run(run(args.output, args.canary_only)))
    print(json.dumps(result, indent=2), flush=True)
