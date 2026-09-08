"""Explicit, budget-preserving transport repair; original comparison stays immutable.

Does not change any rubric, reference, semantic schema, validator or evidence.
Inspect's JSONSchema model ignores $ref/$defs, so inline references BEFORE model
construction. Provider-supported constraints remain native; full validation stays
in the original frozen parser. No unstructured fallback is permitted.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.aaa_vs_petri.judge_validation_v4 import run as frozen
from inspect_ai.util._json import resolve_schema_references


def inline_schema(schema):
    result = resolve_schema_references(schema)
    def check(node):
        if isinstance(node, dict):
            if "$ref" in node or "$defs" in node:
                raise ValueError("Unresolved/recursive reference: cannot send lossily")
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)
    check(result)
    return result


def prepare(original, output):
    m = frozen.verify(original)
    frozen.prepare(Path(m["corpus"]), output, allow_agent=True)
    paths = sorted((original / "predictions").glob("*.json"))
    limits, statuses = {}, {}
    dest = output / "predictions"
    dest.mkdir()
    total = 0
    repaired = 0
    for path in paths:
        row = json.loads(path.read_text())
        total += len(row["attempts"])
        statuses[path.name] = row["status"]
        if row["status"] == "failed":
            if not (row["family"].endswith("_v4") and len(row["attempts"]) == 3 and
                    all("Schema type is missing" in a.get("error", "") and "response" not in a for a in row["attempts"])):
                raise ValueError("Only the explicitly approved pre-generation schema failures may receive extra attempts")
            limits[path.name] = 6
            row["status"] = "pending"
            repaired += 1
        for attempt in row["attempts"]:
            attempt["phase"] = "initial_transport"
            if attempt["status"] == "reserved":
                attempt["status"] = "interrupted_outcome_unknown"
        (dest / path.name).write_text(json.dumps(row, indent=2) + "\n")
    if repaired != 12 or total != 56:
        raise ValueError("Original attempt set differs from the approved 12-job/56-reservation repair")
    schemas = json.loads((output / "schemas.json").read_text())
    repaired_schemas = {f: inline_schema(s) for f, s in schemas.items()}
    repair = {"original": str(original.resolve()), "original_manifest_sha256": frozen.sha(original / "manifest.json"),
              "original_predictions_sha256": {p.name: frozen.sha(p) for p in paths},
              "original_statuses": statuses, "initial_reserved_requests": total,
              "extra_attempt_limits": limits, "total_request_ceiling": 444,
              "approval": "User explicitly approved up to three additional attempts for the 12 pre-generation schema-rejected v4 jobs, within 444 requests total; completed judgments reused.",
              "wire_schemas": repaired_schemas,
              "code_sha256": frozen.sha(Path(__file__)),
              "change": "Inline JSON Schema references before Inspect ResponseSchema construction. Frozen rubric prompts, semantic schemas, local validators, model and payloads unchanged."}
    repair_path = output / "transport-repair.json"
    repair_path.write_text(json.dumps(repair, indent=2) + "\n")
    new_manifest = json.loads((output / "manifest.json").read_text())
    new_manifest["transport_repair_sha256"] = frozen.sha(repair_path)
    new_manifest["attempt_policy"] = "3 total reservations normally; 6 only for the 12 approved schema-rejected jobs; 444 aggregate ceiling includes all original/interrupted reservations"
    (output / "manifest.json").write_text(json.dumps(new_manifest, indent=2) + "\n")
    print(json.dumps({"prepared": str(output), "carried_reservations": total, "additional_request_ceiling": 444-total,
                      "reused_successes": sum(s == "success" for s in statuses.values()), "paid_calls": 0}))


def verify(output):
    m = frozen.verify(output)
    path = output / "transport-repair.json"
    if frozen.sha(path) != m["transport_repair_sha256"]:
        raise ValueError("Frozen transport repair changed")
    repair = json.loads(path.read_text())
    if frozen.sha(Path(__file__)) != repair["code_sha256"]:
        raise ValueError("Frozen repair runner changed")
    original = Path(repair["original"])
    frozen.verify(original)
    if frozen.sha(original / "manifest.json") != repair["original_manifest_sha256"]:
        raise ValueError("Original manifest changed")
    for name, digest in repair["original_predictions_sha256"].items():
        if frozen.sha(original / "predictions" / name) != digest:
            raise ValueError("Original attempted judgment changed")
    return m, repair


def used_requests(dest):
    return sum(len(json.loads(p.read_text())["attempts"]) for p in dest.glob("*.json"))


def available(row, name, repair, total):
    return (len(row["attempts"]) < repair["extra_attempt_limits"].get(name, 3)
            and total < repair["total_request_ceiling"])


async def run(output, split, concurrency):
    m, repair = verify(output)
    # One local process owns reservations across all in-flight calls.
    lock_path = output / "transport-run.lock"
    with lock_path.open("x"):
        pass
    try:
        if split == "holdout":
            frozen.claim_holdout(m, output)
        from inspect_ai._util.dotenv import init_dotenv
        from inspect_ai.model import ChatMessageSystem, ChatMessageUser, GenerateConfig, ResponseSchema, get_model
        init_dotenv()
        model = get_model(m["judge_model"], config=GenerateConfig(
            max_connections=concurrency, max_retries=0, timeout=300, max_tokens=8000, cache_prompt="auto"))
        prompts = json.loads((output / "prompts.json").read_text())
        cases = [c for c in json.loads((output / "cases.json").read_text()) if c["split"] == split]
        dest = output / "predictions"
        total = used_requests(dest)
        sem = asyncio.Semaphore(concurrency)

        async def one(case, family):
            nonlocal total
            path = dest / f"{case['id']}-{family}.json"
            row = json.loads(path.read_text()) if path.exists() else {
                "case_id": case["id"], "family": family, "model": m["judge_model"], "status": "pending",
                "runner_fidelity": frozen.runner_fidelity(case["payload"]), "attempts": []}
            if row["status"] in {"success", "failed"}:
                return
            config = GenerateConfig(response_schema=ResponseSchema(name=family, json_schema=repair["wire_schemas"][family])) if family in repair["wire_schemas"] else GenerateConfig()
            async with sem:
                while available(row, path.name, repair, total):
                    attempt = {"number": len(row["attempts"])+1, "status": "reserved", "phase": "repaired_transport",
                               "reserved_at": datetime.now(timezone.utc).isoformat()}
                    row["attempts"].append(attempt)
                    # No await between checking the shared ceiling and reserving.
                    total += 1
                    path.write_text(json.dumps(row, indent=2) + "\n")
                    try:
                        reply = await model.generate([
                            ChatMessageSystem(content=prompts[family]),
                            ChatMessageUser(content=json.dumps(frozen.payload(case["payload"], family), ensure_ascii=False))], config=config)
                        attempt.update(response=reply.completion, usage=reply.usage.model_dump(mode="json") if reply.usage else {}, stop_reason=reply.stop_reason)
                        row["result"] = frozen.parse(reply.completion, family, case["payload"])
                        row["status"] = attempt["status"] = "success"
                    except Exception as error:
                        attempt.update(status="error", error=str(error))
                        # Repeated deterministic request rejection cannot improve by retrying.
                        if "invalid_request_error" in str(error) and "schema" in str(error).lower():
                            path.write_text(json.dumps(row, indent=2) + "\n")
                            raise RuntimeError("Native schema request rejected; stopping before further retries") from error
                    path.write_text(json.dumps(row, indent=2) + "\n")
                    if row["status"] == "success":
                        break
                else:
                    row.update(status="failed", triage=frozen.triage(), exhausted="job_or_aggregate_request_budget")
                    path.write_text(json.dumps(row, indent=2) + "\n")
            print(f"{row['status']}: {case['id']} / {family}", flush=True)

        scheduled = [(c, f) for c in cases for f in frozen.FAMILIES]
        # Canary calls are real scheduled jobs, not extra paid fixtures. Sequential
        # first calls check both native schemas before opening normal concurrency.
        if split == "development":
            for family in ("awareness_v4", "debug_v4"):
                await one(cases[0], family)
                row = json.loads((dest / f"{cases[0]['id']}-{family}.json").read_text())
                if row["status"] != "success":
                    raise RuntimeError("Transport canary did not produce a valid judgment; inspect before continuing")
        random.Random(20260908).shuffle(scheduled)
        await asyncio.gather(*(one(c, f) for c, f in scheduled))
        print(json.dumps({"split": split, "total_reserved_requests_including_original": total}), flush=True)
    finally:
        lock_path.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run"])
    parser.add_argument("--original", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--split", choices=["development", "holdout"], default="development")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--approved-transport-repair", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        if args.original is None:
            parser.error("prepare requires --original")
        prepare(args.original, args.output_dir)
    elif not args.approved_transport_repair:
        parser.error("Explicit approval is required for extra retries after transport repair")
    else:
        asyncio.run(run(args.output_dir, args.split, args.concurrency))
