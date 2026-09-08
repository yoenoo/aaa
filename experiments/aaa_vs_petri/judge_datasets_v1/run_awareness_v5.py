"""Frozen, bounded v5 awareness run. Prepare offline; run only with explicit paid approval."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import random
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from awareness_v5 import DIMENSIONS, payload, prompt, response_schema, validate_response
from experiments.aaa_vs_petri.judge_datasets_v1.labels import read_jsonl, unique, verify_dataset
from experiments.aaa_vs_petri.judge_datasets_v1.package_agent_review import sha
from experiments.aaa_vs_petri.judge_v4_transport_repair import inline_schema
from experiments.aaa_vs_petri.judge_v4_transport_adapter import object_only_additional_properties

MODEL = "anthropic/claude-opus-4-8"
PACKAGES = ("inspect_ai", "anthropic", "pydantic")


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    """Replace only this run's generated state, keeping old state safe on interruption."""
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".state-", delete=False) as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        temp = Path(stream.name)
    temp.replace(path)


def prepare(dataset, output):
    dataset, output = dataset.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(dataset):
        raise ValueError("Use a new run directory outside the frozen dataset")
    source_manifest = verify_dataset(dataset)
    inputs = read_jsonl(dataset / "inputs.jsonl")
    unique(inputs, "id")
    if len(inputs) != 134 or source_manifest.get("version") != "2-positive-awareness":
        raise ValueError("Approval covers the 134-packet positive-awareness v2 dataset only")
    for row in inputs:
        if set(row) != {"id", "payload"} or payload(row["payload"]) != row["payload"]:
            raise ValueError("Judge inputs must be the unchanged metadata-free evidence packets")
    for name, digest in source_manifest["builder_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f"Frozen dataset dependency changed: {name}")
    schema = response_schema()
    wire_schema = inline_schema(schema)
    from inspect_ai.model import ResponseSchema
    from inspect_ai.util._json import JSON_SCHEMA_EXTENDED_FIELDS, json_schema_dump
    transported = ResponseSchema(name="awareness_v5", json_schema=wire_schema).json_schema
    object_only_additional_properties(transported)
    provider_projection = json_schema_dump(transported, exclude=JSON_SCHEMA_EXTENDED_FIELDS)
    output.mkdir(parents=True)
    (output / "predictions").mkdir()
    (output / "inputs.jsonl").write_bytes((dataset / "inputs.jsonl").read_bytes())
    (output / "prompt.txt").write_text(prompt())
    atomic_json(output / "schemas.json", {"semantic": schema, "inlined": wire_schema, "provider_projection": provider_projection})
    code = [Path(__file__), HERE / "report_awareness_v5.py", HERE / "positive_metrics.py",
            HERE / "positive_dataset.py", HERE / "metrics.py", HERE / "labels.py", HERE / "package_agent_review.py",
            ROOT / "src/awareness_v5.py", ROOT / "src/judge_v4.py", ROOT / "src/prompts/awareness_v5.txt",
            HERE.parent / "judge_v4_transport_repair.py", HERE.parent / "judge_v4_transport_adapter.py"]
    manifest = {"created_at": now(), "dataset": str(dataset), "dataset_manifest_sha256": sha(dataset / "manifest.json"),
        "judge_model": MODEL, "planned_jobs": 134, "max_attempts_per_job": 3, "max_provider_requests": 402,
        "automatic_inspect_retries": 0, "automatic_sdk_retries": 0, "max_concurrency": 6,
        "max_tokens": 8000, "timeout_seconds": 300, "cache_prompt": "auto", "streaming": False,
        "generation_policy": "Unchanged v5 prompt, evidence and schema on every attempt. No fallback model or executable tools. Provider default reasoning/temperature.",
        "retry_policy": "Retry only request/JSON/validation failures, never valid uncertain or absent judgments. Preserve the first valid assessment independently for each dimension; no semantic/label-driven retries.",
        "reference_policy": "No references, review notes, selection metadata or source paths are included in model messages. This run measures agreement with exposed agent references, not independent human accuracy.",
        "approval_context": "User requested 'lets run it' after discussion of the revised 134-packet v5 run; previously proposed Claude Opus 4.8 and maximum 402 requests including retries. No target reruns.",
        "runtime_versions": {name: importlib.metadata.version(name) for name in PACKAGES},
        "code_sha256": {str(p.relative_to(ROOT)): sha(p) for p in code},
        "artifact_sha256": {name: sha(output / name) for name in ("inputs.jsonl", "prompt.txt", "schemas.json")}}
    atomic_json(output / "manifest.json", manifest)
    return {"prepared": str(output), "jobs": 134, "request_ceiling": 402, "paid_calls": 0}


def verify(output):
    m = verify_dataset(output)
    dataset = Path(m["dataset"])
    verify_dataset(dataset)
    if sha(dataset / "manifest.json") != m["dataset_manifest_sha256"]:
        raise ValueError("Frozen dataset manifest changed")
    for name, digest in m["code_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f"Frozen run dependency changed: {name}")
    for name, version in m["runtime_versions"].items():
        if importlib.metadata.version(name) != version:
            raise ValueError(f"Runtime version changed: {name}")
    if m["judge_model"] != MODEL or m["planned_jobs"] != 134 or m["max_provider_requests"] != 402 or m["max_attempts_per_job"] != 3:
        raise ValueError("The approved model/job/request limits must not change")
    return m


def absorb(row, raw, packet, number):
    """First valid dimension wins; an uncertain answer is valid, not a retry trigger."""
    validated = validate_response(raw, packet)
    row.setdefault("result", {})
    row.setdefault("dimension_attempt", {})
    for d, result in validated["dimensions"].items():
        if result["valid"] and d not in row["result"]:
            row["result"][d] = {k: result[k] for k in ("status", "evidence", "explanation")}
            row["dimension_attempt"][d] = number
    return validated


def available(row, total, manifest):
    return (len(row["attempts"]) < manifest["max_attempts_per_job"]
            and total < manifest["max_provider_requests"] and len(row.get("result", {})) < len(DIMENSIONS))


def terminal(row):
    if len(row.get("result", {})) == len(DIMENSIONS):
        return "success"
    return "partial" if row.get("result") else "failed"


async def execute(output, manifest, model, *, concurrency=6, canary_only=False):
    """Reservations persist before each generate; automatic provider retries must be disabled."""
    from inspect_ai.model import ChatMessageSystem, ChatMessageUser, GenerateConfig, ResponseSchema
    cases = read_jsonl(output / "inputs.jsonl")
    by_id = unique(cases, "id")
    dest = output / "predictions"
    rows = {}
    for path in dest.glob("*.json"):
        row = json.loads(path.read_text())
        if row["case_id"] not in by_id or path.stem != row["case_id"] or len(row["attempts"]) > manifest["max_attempts_per_job"]:
            raise ValueError("Unexpected job state or attempts outside the frozen budget")
        for a in row["attempts"]:
            if a["status"] == "reserved":
                a["status"] = "interrupted_outcome_unknown"
        rows[row["case_id"]] = row
        atomic_json(path, row)
    total = sum(len(r["attempts"]) for r in rows.values())
    if total > manifest["max_provider_requests"]:
        raise ValueError("Request ceiling already exceeded")
    rubric = (output / "prompt.txt").read_text()
    schema = json.loads((output / "schemas.json").read_text())["inlined"]
    config = GenerateConfig(response_schema=ResponseSchema(name="awareness_v5", json_schema=schema), max_retries=0)
    sem = asyncio.Semaphore(concurrency)

    async def one(case):
        nonlocal total
        cid = case["id"]
        path = dest / f"{cid}.json"
        row = rows.setdefault(cid, {"case_id": cid, "model": manifest["judge_model"],
                                   "status": "pending", "attempts": [], "result": {}, "dimension_attempt": {}})
        if row["status"] in {"success", "partial", "failed"}:
            return
        async with sem:
            while available(row, total, manifest):
                a = {"number": len(row["attempts"]) + 1, "status": "reserved", "reserved_at": now()}
                row["attempts"].append(a)
                total += 1  # No await between ceiling check and durable reservation.
                atomic_json(path, row)
                fatal = False
                try:
                    reply = await model.generate([ChatMessageSystem(content=rubric),
                        ChatMessageUser(content=json.dumps(case["payload"], ensure_ascii=False))], config=config)
                    a.update(response=reply.completion, usage=reply.usage.model_dump(mode="json") if reply.usage else {},
                             stop_reason=reply.stop_reason, completed_at=now())
                    a["validation"] = absorb(row, json.loads(reply.completion), case["payload"], a["number"])
                    a["status"] = "valid" if all(r["valid"] for r in a["validation"]["dimensions"].values()) else "validation_error"
                except Exception as error:
                    # Keep raw error private in this run; do not print provider credentials or payloads.
                    a.update(status="error", error_type=type(error).__name__, error=str(error), completed_at=now())
                    status_code = getattr(error, "status_code", None)
                    fatal = status_code in {400, 401, 403, 404} or "schema type is missing" in str(error).lower()
                if len(row["result"]) == len(DIMENSIONS):
                    row["status"] = "success"
                atomic_json(path, row)
                if fatal:
                    raise RuntimeError(f"Provider rejected request for {cid}; stopping for inspection, no blind retries")
                if row["status"] == "success":
                    break
            row["status"] = terminal(row)
            atomic_json(path, row)
            print(f"{row['status']}: {cid}; attempts={len(row['attempts'])}; reserved_total={total}", flush=True)

    scheduled = sorted(cases, key=lambda c: c["id"])
    random.Random(20260908).shuffle(scheduled)
    # This is the first scheduled job, not an extra paid fixture.
    await one(scheduled[0])
    if canary_only:
        return {"canary_case": scheduled[0]["id"], "status": rows[scheduled[0]["id"]]["status"], "requests_reserved": total}
    tasks = [asyncio.create_task(one(c)) for c in scheduled[1:]]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return {"jobs": len(rows), "status_counts": dict(Counter(r["status"] for r in rows.values())), "requests_reserved": total}


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
        if model.api.client.max_retries != 0:
            raise ValueError("SDK automatic retries must be disabled before any request")
        try:
            with patch.object(anthropic, "set_additional_properties_false", object_only_additional_properties):
                result = await execute(output, m, model, concurrency=concurrency, canary_only=canary_only)
        finally:
            await model.api.aclose()
        atomic_json(output / "progress.json", {**result, "recorded_at": now(), "canary_only": canary_only})
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run"])
    parser.add_argument("output", type=Path)
    parser.add_argument("--dataset", type=Path, default=ROOT / "logs/judge-datasets/v2-positive-awareness")
    parser.add_argument("--approved-paid-run", action="store_true")
    parser.add_argument("--canary-only", action="store_true")
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare(args.dataset, args.output)
    else:
        if not args.approved_paid_run:
            parser.error("Explicit paid-run approval is required")
        result = asyncio.run(run(args.output, concurrency=args.concurrency, canary_only=args.canary_only))
    print(json.dumps(result, indent=2), flush=True)
