"""Re-judge ONE sample of an AAA log under a new viewer id (for checking a judge/packet fix).

Copies the sample, drops its scores, sets uuid to <uuid><suffix>, scores it with the v3 judges,
writes logs/judge-v3-aaa-gemini31pro/refix/<stem><suffix>.eval, dumps it to the viewer and
records the judge requests in the ledger. The original viewer file is left untouched.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from experiments.judge_calibration import ledger  # noqa: E402
from experiments.judge_calibration.aaa.rejudge import attempts_of  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source")
    ap.add_argument("uuid")
    ap.add_argument("--suffix", default="-refix")
    ap.add_argument("--out", type=Path, default=ROOT / "logs/judge-v3-aaa-gemini31pro/refix")
    ap.add_argument("--viewer-dir", type=Path, default=ROOT / "viewer/public/data")
    ap.add_argument("--allocation", default="phase2")
    ap.add_argument("--judges", default="scheming,debug", help="comma-separated; a judge not listed keeps its score from an existing dest log")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--approved-paid-run", action="store_true")
    args = ap.parse_args()
    if not args.approved_paid_run:
        ap.error("--approved-paid-run required")
    from inspect_ai import score
    from inspect_ai.log import read_eval_log, write_eval_log
    from inspect_ai._util.dotenv import init_dotenv
    from scorer import scheming_judge_v3, debug_judge_v3
    from transcript import write_all_transcripts_and_index
    init_dotenv()
    log = read_eval_log(args.source, resolve_attachments="full")
    [sample] = [s for s in log.samples if s.uuid == args.uuid]
    work = copy.deepcopy(log)
    sample = copy.deepcopy(sample)
    sample.scores = {}
    sample.uuid = args.uuid + args.suffix
    work.samples = [sample]
    args.out.mkdir(parents=True, exist_ok=True)
    dest = args.out / (Path(args.source).stem + args.suffix + ".eval")
    wanted = args.judges.split(",")
    judges = [j for name, j in (("scheming", scheming_judge_v3(retries=args.retries)), ("debug", debug_judge_v3(retries=args.retries))) if name in wanted]
    scored = score(work, judges, action="overwrite", display="plain")
    if dest.exists():  # keep the scores of judges we did not rerun
        prev = read_eval_log(str(dest)).samples[0].scores or {}
        for name, sc in prev.items():
            if name.split("_")[0] not in wanted:
                scored.samples[0].scores[name] = sc
    write_eval_log(scored, str(dest))
    n = attempts_of(scored.samples[0])
    if n:
        ledger.reserve(args.allocation, "aaa-gemini31pro-v3", n=n, note=dest.name)
    for name, sc in (scored.samples[0].scores or {}).items():
        print(name, sc.answer, flush=True)
    written = write_all_transcripts_and_index(scored, args.viewer_dir, eval_id=Path(args.source).stem.split("_")[-1] + args.suffix)
    print("requests", n, "viewer", [str(p) for p in written], flush=True)


if __name__ == "__main__":
    main()
