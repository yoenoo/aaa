"""Package the 18 completed Petri audits as full-audit judge inputs for the calibration runner.

No paid calls. Reuses the frozen full_judge packet builder so records/requests/branches are
identical to the earlier full-judge integration; only the judge (variant) differs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from inspect_ai.log import read_eval_log
from experiments.aaa_vs_petri.full_judge.run import build_packet
from experiments.aaa_vs_petri.judge_validation_v4.corpus import SOURCES

TRACK = "petri_audit"
FAMILIES = ("scheming", "debug")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(output):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a fresh output directory")
    rows, audits, sources = [], [], {}
    for path in SOURCES:
        log = read_eval_log(str(path), resolve_attachments="full")
        sources[str(path.relative_to(ROOT))] = sha(path)
        for sample in log.samples or []:
            if sample.error or any(a["uuid"] == sample.uuid for a in audits):
                continue
            packet, mapping = build_packet(sample)
            for family in FAMILIES:
                rows.append({"id": f"{sample.uuid}-{family}", "track": TRACK, "family": family, "subset": ["full"],
                             "payload": packet, "group": sample.metadata["source_scenario"], "pair_id": sample.uuid, "variant": None})
            audits.append({"uuid": sample.uuid, "seed": sample.metadata["source_scenario"], "source": str(path.relative_to(ROOT)),
                           "target_outputs": len(packet["requests"]), "records": len(packet["records"]),
                           "coverage": packet["coverage"], "record_mapping": mapping})
    if len(audits) != 18:
        raise ValueError(f"Expected 18 completed audits, found {len(audits)}")
    output.mkdir(parents=True)
    (output / "private").mkdir()
    (output / "inputs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    (output / "private" / "audits.json").write_text(json.dumps(audits, indent=2))
    manifest = {"version": "petri-full-audits-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                "audits": len(audits), "jobs": len(rows), "sources_sha256": sources,
                "sha256": {"inputs.jsonl": sha(output / "inputs.jsonl"), "private/audits.json": sha(output / "private/audits.json")},
                "builder_sha256": sha(__file__)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return {"output": str(output), "audits": len(audits), "jobs": len(rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "logs/judge-calibration/petri-inputs-v1")
    print(json.dumps(build(parser.parse_args().output), indent=2))
