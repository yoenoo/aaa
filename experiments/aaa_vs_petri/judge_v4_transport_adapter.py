"""Second transport-only compatibility repair, isolated from all frozen rubrics.

The installed adapter sets additionalProperties=false on primitives and anyOf
nodes. Anthropic rejects this. Apply it only to object schemas, locally for this
process, retaining native structured output and the unchanged full local validator.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.aaa_vs_petri import judge_v4_transport_repair as repair
from experiments.aaa_vs_petri.judge_validation_v4 import run as frozen


def object_only_additional_properties(schema):
    schema.additionalProperties = False if schema.type == "object" else None
    if schema.items:
        object_only_additional_properties(schema.items)
    for value in (schema.properties or {}).values():
        object_only_additional_properties(value)
    for value in schema.anyOf or []:
        object_only_additional_properties(value)


def prepare(previous, output):
    m, previous_repair = repair.verify(previous)
    if (previous / "transport-run.lock").exists():
        raise ValueError("Do not copy a running comparison")
    paths = sorted((previous / "predictions").glob("*.json"))
    if repair.used_requests(previous / "predictions") != 57:
        raise ValueError("Expected 56 original reservations plus one rejected canary")
    frozen.prepare(Path(m["corpus"]), output, allow_agent=True)
    dest = output / "predictions"
    dest.mkdir()
    for path in paths:
        row = json.loads(path.read_text())
        for attempt in row["attempts"]:
            if attempt.get("phase") == "repaired_transport":
                attempt["phase"] = "reference_inlining_only"
        (dest / path.name).write_text(json.dumps(row, indent=2) + "\n")
    (output / "transport-repair.json").write_bytes((previous / "transport-repair.json").read_bytes())
    adapter = {"previous": str(previous.resolve()),
               "previous_manifest_sha256": frozen.sha(previous / "manifest.json"),
               "previous_predictions_sha256": {p.name: frozen.sha(p) for p in paths},
               "code_sha256": frozen.sha(Path(__file__)),
               "initial_reserved_requests": 57,
               "change": "Scope additionalProperties=false to object schemas only; union, primitive and array schemas carry no object-only keyword. No prompt, reference, payload, model, validator or retry-budget change.",
               "extra_retry_authority": previous_repair["approval"]}
    (output / "transport-adapter.json").write_text(json.dumps(adapter, indent=2) + "\n")
    manifest = json.loads((output / "manifest.json").read_text())
    manifest.update(transport_repair_sha256=frozen.sha(output / "transport-repair.json"),
                    transport_adapter_sha256=frozen.sha(output / "transport-adapter.json"),
                    attempt_policy=m["attempt_policy"])
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"prepared": str(output), "reserved_requests_carried": 57, "remaining_ceiling": 387, "paid_calls": 0}))


def verify(output):
    m, r = repair.verify(output)
    p = output / "transport-adapter.json"
    if frozen.sha(p) != m["transport_adapter_sha256"]:
        raise ValueError("Transport adapter manifest changed")
    adapter = json.loads(p.read_text())
    if frozen.sha(Path(__file__)) != adapter["code_sha256"]:
        raise ValueError("Transport adapter code changed")
    previous = Path(adapter["previous"])
    repair.verify(previous)
    if frozen.sha(previous / "manifest.json") != adapter["previous_manifest_sha256"]:
        raise ValueError("Previous transport manifest changed")
    for name, digest in adapter["previous_predictions_sha256"].items():
        if frozen.sha(previous / "predictions" / name) != digest:
            raise ValueError("Previous transport attempt changed")
    return m, r


async def run(output, split, concurrency):
    verify(output)
    from inspect_ai.model._providers import anthropic
    with patch.object(anthropic, "set_additional_properties_false", object_only_additional_properties):
        await repair.run(output, split, concurrency)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run"])
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--split", choices=["development", "holdout"], default="development")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--approved-transport-repair", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        if args.previous is None:
            parser.error("prepare requires --previous")
        prepare(args.previous, args.output_dir)
    elif not args.approved_transport_repair:
        parser.error("Explicit approval required for extra transport-failure retries")
    else:
        asyncio.run(run(args.output_dir, args.split, args.concurrency))
