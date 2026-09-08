"""Freeze completed, successful samples from a running log for post-hoc scoring.

The projection is explicitly labeled and immutable; the running source is never
modified. Previously captured sample UUIDs are excluded on subsequent calls.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from inspect_ai.log import read_eval_log, write_eval_log


def snapshot(source: Path, output_dir: Path):
    existing = set()
    for path in output_dir.glob("completed-*.eval"):
        prior = read_eval_log(path)
        existing.update(sample.uuid for sample in prior.samples or [])
    log = read_eval_log(source, resolve_attachments="full")
    selected = [s for s in log.samples or []
                if s.completed_at and not s.error and s.uuid not in existing]
    if not selected:
        print("No newly completed successful samples to snapshot.")
        return None
    for sample in selected:
        if not (sample.metadata or {}).get("source_scenario"):
            raise ValueError(f"Not a catalog sample: {sample.id}")
    identity = "\n".join(sorted(s.uuid for s in selected))
    output = output_dir / f"completed-{hashlib.sha256(identity.encode()).hexdigest()[:16]}.eval"
    if output.exists():
        raise ValueError(f"Snapshot already exists: {output}")
    metadata = {**(log.eval.metadata or {}), "completed_sample_snapshot": {
        "source_log": str(source), "source_eval_id": log.eval.eval_id,
        "source_status_at_capture": log.status,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sample_uuids": [s.uuid for s in selected],
        "description": "Successful completed-sample projection, not the original full evaluation",
    }}
    dataset = log.eval.dataset.model_copy(update={
        "samples": len(selected), "sample_ids": [s.id for s in selected]})
    spec = log.eval.model_copy(update={"metadata": metadata, "dataset": dataset})
    # 'success' describes only the selected completed subset; the source status
    # is preserved explicitly above and the source file is not rewritten.
    projection = log.model_copy(update={
        "eval": spec, "samples": selected, "status": "success",
        "results": None, "reductions": None,
        "stats": log.stats.model_copy(update={"model_usage": {}}) if log.stats else None,
    })
    output_dir.mkdir(parents=True, exist_ok=True)
    write_eval_log(projection, output)
    print(json.dumps({"snapshot": str(output), "samples": [s.id for s in selected]}))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    snapshot(args.source, args.output_dir)


if __name__ == "__main__":
    main()
