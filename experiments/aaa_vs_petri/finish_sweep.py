"""Finish an already-authorized, already-running sweep with AAA judges + viewer.

No target generations. Polls only the selected local log, freezes newly completed
samples, runs both AAA judges, exports their transcripts, and updates screening.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from inspect_ai.log import read_eval_log

from snapshot_completed import snapshot

HERE = Path(__file__).resolve().parent


def run(script, *args):
    subprocess.run([sys.executable, str(HERE / script), *map(str, args)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    snapshots = args.work_dir / "snapshots"
    seen_status = None
    while True:
        log = read_eval_log(args.source)
        progress = (log.status, len(log.samples or []))
        if progress != seen_status:
            print(f"Generation status: {progress[0]}, {progress[1]} completed records", flush=True)
            seen_status = progress
        captured = snapshot(args.source, snapshots)
        # Include prior unscored snapshots so an interrupted postprocessor can
        # resume without rerunning the target or duplicating completed judgments.
        for source in sorted(snapshots.glob("completed-*.eval")):
            output_dir = args.work_dir / "judgments" / source.stem
            scored = output_dir / f"{source.stem}-aaa.eval"
            if not scored.exists():
                run("aaa_judgments.py", source, "--output-dir", output_dir)
            marker = output_dir / "exported.json"
            if not marker.exists():
                run("export_viewer.py", scored)
                run("rank_realism.py", "--output-dir", HERE / "screening")
                marker.write_text(json.dumps({"scored_log": str(scored)}) + "\n")
        if log.status != "started":
            # Reload after the last iteration so a newly finalized file's final
            # samples cannot be skipped by a prior status read.
            final = read_eval_log(args.source)
            captured_ids = {s.uuid for p in snapshots.glob("completed-*.eval")
                            for s in read_eval_log(p).samples or []}
            expected = {s.uuid for s in final.samples or [] if not s.error and s.completed_at}
            if expected != captured_ids:
                continue
            errors = [{"seed": s.id, "error": s.error.message}
                      for s in final.samples or [] if s.error]
            print(json.dumps({"generation_status": final.status,
                              "scored_samples": len(captured_ids), "errors": errors}), flush=True)
            break
        time.sleep(15)


if __name__ == "__main__":
    main()
