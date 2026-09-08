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
from judge_packet import compact  # production size-budgeted compaction (src/judge_packet.py)

TRACK = "petri_audit"
FAMILIES = ("scheming", "debug")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(output, sources=None, expected_audits=18):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a fresh output directory")
    rows, audits, sources_sha = [], [], {}
    for path in (sources or SOURCES):
        path = Path(path).resolve()
        log = read_eval_log(str(path), resolve_attachments="full")
        sources_sha[str(path.relative_to(ROOT))] = sha(path)
        for sample in log.samples or []:
            if sample.error or any(a["uuid"] == sample.uuid for a in audits):
                continue
            # Errored target generations have no output and cannot be judged; the frozen
            # builder's resume-window check would otherwise reject the whole audit.
            errored = [e for e in sample.events if e.event == "model" and e.role == "target" and e.error]
            if errored:
                sample = sample.model_copy(update={"events": [e for e in sample.events if e not in errored]})
            packet, mapping = build_packet(sample)
            packet = compact(packet)  # long audits must fit the judge's context; records marked when shortened
            for family in FAMILIES:
                rows.append({"id": f"{sample.uuid}-{family}", "track": TRACK, "family": family, "subset": ["full"],
                             "payload": packet, "group": sample.metadata["source_scenario"], "pair_id": sample.uuid, "variant": None})
            audits.append({"uuid": sample.uuid, "seed": sample.metadata["source_scenario"], "source": str(path.relative_to(ROOT)),
                           "target_outputs": len(packet["requests"]), "records": len(packet["records"]),
                           "excluded_errored_target_events": len(errored), "truncation": packet.get("truncation"),
                           "coverage": packet["coverage"], "record_mapping": mapping})
    if len(audits) != expected_audits:
        raise ValueError(f"Expected {expected_audits} completed audits, found {len(audits)}")
    output.mkdir(parents=True)
    (output / "private").mkdir()
    (output / "inputs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    (output / "private" / "audits.json").write_text(json.dumps(audits, indent=2))
    manifest = {"version": "petri-full-audits-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                "audits": len(audits), "jobs": len(rows), "sources_sha256": sources_sha,
                                "sha256": {"inputs.jsonl": sha(output / "inputs.jsonl"), "private/audits.json": sha(output / "private/audits.json")},
                "builder_sha256": sha(__file__)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return {"output": str(output), "audits": len(audits), "jobs": len(rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "logs/judge-calibration/petri-inputs-v1")
    parser.add_argument("--sources", type=Path, nargs="*", help="Petri .eval logs (default: the 18-audit Gemini 3.1 corpus)")
    parser.add_argument("--expect-audits", type=int, default=18)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.sources, args.expect_audits), indent=2))
