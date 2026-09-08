"""Re-validate the stored responses of FAILED jobs with the current validator (no paid calls).

A response that now validates becomes the job's result; the state records which attempt was
accepted and that acceptance came from re-validation, so provenance stays explicit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.judge_calibration.ledger import atomic_json
from experiments.judge_calibration.runner import now
from experiments.judge_calibration.variants import load_variant, validate


def revalidate(run_dir):
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    inputs = {json.loads(l)["id"]: json.loads(l) for l in (run_dir / "inputs.jsonl").read_text().splitlines()}
    specs = {f: load_variant(manifest["variant"], f) for f in manifest["families"]}
    changed = []
    for path in sorted((run_dir / "predictions").glob("*.json")):
        state = json.loads(path.read_text())
        if state["status"] != "failed":
            continue
        for attempt in state["attempts"]:
            if attempt.get("status") != "validation_error" or not attempt.get("response"):
                continue
            try:
                result = validate(json.loads(attempt["response"]), inputs[state["id"]]["payload"], specs[state["family"]])
            except ValueError as error:
                attempt["revalidation_error"] = str(error)
                continue
            state.update(result=result, status="success", revalidated={"attempt": attempt["number"], "at": now(),
                         "note": "Accepted by a later validator version (event_id/channel relabelling of verbatim quotes)."})
            attempt["status"] = "valid_on_revalidation"
            changed.append((state["id"], attempt["number"]))
            break
        atomic_json(path, state)
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    print(json.dumps({"revalidated": revalidate(parser.parse_args().run_dir)}))
