"""Read-only reconciliation of finalized generation, snapshots, scores and viewer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from inspect_ai.log import read_eval_log

from aaa_judgments import ROOT, validate_score


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target_events(sample):
    return [e for e in sample.events if e.event == "model" and e.role == "target"]


def verify(source, work_dir, require_complete=True):
    original = read_eval_log(source, resolve_attachments="full")
    if require_complete and original.status == "started":
        raise ValueError("Generation is still running; use --allow-running for partial verification")
    originals = {s.uuid: s for s in original.samples or []}
    captured = set()
    rows = []
    for path in sorted((work_dir / "snapshots").glob("completed-*.eval")):
        snap = read_eval_log(path, resolve_attachments="full")
        provenance = snap.eval.metadata["completed_sample_snapshot"]
        assert provenance["source_eval_id"] == original.eval.eval_id
        scored_path = work_dir / "judgments" / path.stem / f"{path.stem}-aaa.eval"
        if not scored_path.exists() and not require_complete:
            continue
        judged = read_eval_log(scored_path, resolve_attachments="full")
        assert judged.eval.metadata["aaa_posthoc_judgment"]["source_sha256"] == digest(path)
        scored_by_uuid = {s.uuid: s for s in judged.samples}
        assert set(scored_by_uuid) == {s.uuid for s in snap.samples}
        for sample in snap.samples:
            assert sample.uuid not in captured, "Duplicate snapshot sample"
            captured.add(sample.uuid)
            raw = originals[sample.uuid]
            scored = scored_by_uuid[sample.uuid]
            assert not raw.error and raw.completed_at
            assert raw.messages == sample.messages == scored.messages
            assert target_events(raw) == target_events(sample) == target_events(scored)
            values = {}
            for name, family in (("petri_aaa_scheming", "scheming"), ("petri_aaa_debug", "debug")):
                result = scored.scores[name]
                validate_score(result, family)
                values.update(result.value)
            assert len(values) == 42
            viewer_path = ROOT / "viewer/public/data" / f"petri-{sample.uuid}.json"
            if not viewer_path.exists() and not require_complete:
                continue
            viewer = json.loads(viewer_path.read_text())
            assert viewer["provenance"]["source_sha256"] == digest(scored_path)
            assert viewer["judge"]["scores"] == values
            actual = target_events(raw)
            displayed = [e for e in viewer["events"] if e.get("target_activity")]
            assert [e["target_model_event_uuid"] for e in displayed] == [e.uuid for e in actual]
            rows.append({"seed": sample.id, "uuid": sample.uuid, "scores": len(values),
                         "target_calls": len(actual), "snapshot": str(path),
                         "snapshot_sha256": digest(path), "judged": str(scored_path),
                         "judged_sha256": digest(scored_path), "viewer": str(viewer_path),
                         "viewer_sha256": digest(viewer_path)})
    expected = {s.uuid for s in originals.values() if not s.error and s.completed_at}
    if require_complete:
        assert captured == expected, "Missing successful samples in snapshots"
        assert len(originals) == original.eval.dataset.samples, "Missing original sample records"
    return {"source": str(source), "source_sha256": digest(source),
            "source_status": original.status, "final_verification": require_complete,
            "completed_samples": len(expected), "verified_samples": len(rows),
            "errors": [{"seed": s.id, "error": s.error.message}
                       for s in originals.values() if s.error],
            "checks": ["source messages unchanged", "target ModelEvents unchanged",
                       "42 valid AAA scores per sample", "viewer scores match",
                       "one-to-one chronological target-event attribution", "hash provenance"],
            "samples": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--allow-running", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.source, args.work_dir, not args.allow_running), indent=2))


if __name__ == "__main__":
    main()
