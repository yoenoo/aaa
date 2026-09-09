"""Re-judge existing AAA petri_task logs with the production v3 judges (no target reruns).

For each source .eval: copy, drop the old scores, score with scheming_judge_v3 + debug_judge_v3,
write `<name>-v3.eval` under --out, dump viewer transcripts, and record every judge request in the
budget ledger (allocation --allocation) after the fact. Stops when the per-invocation cap is hit.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from experiments.judge_calibration import ledger  # noqa: E402


def sources(target, exclude_seeds):
    from inspect_ai.log import read_eval_log
    out = []
    for p in sorted(set(glob.glob(str(ROOT / "logs/**/*petri-task*.eval"), recursive=True)
                        + glob.glob(str(ROOT / "results/**/*petri-task*.eval"), recursive=True))):
        if "/judge-" in p or "smoke" in p or "rescored" in p or "-v3.eval" in p:
            continue
        try:
            log = read_eval_log(p, header_only=True)
        except Exception:
            continue
        roles = log.eval.model_roles or {}
        if log.status != "success" or not roles.get("target") or roles["target"].model != target:
            continue
        seed = (log.eval.task_args or {}).get("seed_name")
        if seed in exclude_seeds:
            continue
        out.append((p, seed))
    return out


def attempts_of(sample):
    n = 0
    for sc in (sample.scores or {}).values():
        n += len(((sc.metadata or {}).get("attempts") or []))
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default="google/gemini-3.1-pro-preview")
    ap.add_argument("--out", type=Path, default=ROOT / "logs/judge-v3-aaa-gemini31pro")
    ap.add_argument("--exclude-seeds", default="gr-alignment-eval-sabotage,gr-alignment-eval-sabotage-v2",
                    help="retired designs (the active alignment-eval-sabotage seed is the former -v3)")
    ap.add_argument("--allocation", default="phase2")
    ap.add_argument("--max-requests", type=int, default=450)
    ap.add_argument("--limit-logs", type=int)
    ap.add_argument("--shard", default="0/1", help="i/N: process logs where index %% N == i (run N workers concurrently)")
    ap.add_argument("--samples-per-seed", type=int, help="stratified subset: judge at most N samples per seed")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--no-viewer", action="store_true", help="do not (re)write viewer transcripts")
    ap.add_argument("--approved-paid-run", action="store_true")
    ap.add_argument("--viewer-dir", type=Path, default=ROOT / "viewer/public/data")
    ap.add_argument("--judges", default="scheming,debug", help="comma-separated: scheming, debug")
    args = ap.parse_args()
    if not args.approved_paid_run:
        ap.error("--approved-paid-run required")
    from inspect_ai import score
    from inspect_ai.log import read_eval_log, write_eval_log
    from inspect_ai._util.dotenv import init_dotenv
    from scorer import scheming_judge_v3, debug_judge_v3
    from transcript import write_all_transcripts_and_index
    init_dotenv()
    args.out.mkdir(parents=True, exist_ok=True)
    srcs = sources(args.target, set(args.exclude_seeds.split(",")))
    if args.limit_logs:
        srcs = srcs[:args.limit_logs]
    i, n = (int(x) for x in args.shard.split("/"))
    srcs = [src for k, src in enumerate(srcs) if k % n == i]
    print(f"{len(srcs)} source logs", flush=True)
    used = 0
    summary = []
    per_seed = {}
    for i, (p, seed) in enumerate(srcs):
        dest = args.out / (Path(p).stem + "-v3.eval")
        if dest.exists():
            print(f"skip (done): {dest.name}", flush=True); continue
        if used >= args.max_requests:
            print("request cap reached; stopping", flush=True); break
        log = read_eval_log(p, resolve_attachments="full")
        work = copy.deepcopy(log)
        if args.samples_per_seed:
            room = args.samples_per_seed - per_seed.get(seed, 0)
            if room <= 0:
                continue
            work.samples = work.samples[:room]
            per_seed[seed] = per_seed.get(seed, 0) + len(work.samples)
        for s in work.samples:
            s.scores = {}
        judges = [j for name, j in (("scheming", scheming_judge_v3(retries=args.retries)), ("debug", debug_judge_v3(retries=args.retries))) if name in args.judges.split(",")]
        scored = score(work, judges, action="overwrite", display="plain")
        write_eval_log(scored, str(dest))
        n = sum(attempts_of(s) for s in scored.samples)
        used += n
        if n:
            ledger.reserve(args.allocation, "aaa-gemini31pro-v3", n=n, note=dest.name)
        ok = {name: sum(1 for s in scored.samples if (s.scores or {}).get(name) and s.scores[name].answer not in ("JUDGE_PARSE_FAILURE", "JUDGE_PACKET_FAILURE"))
              for name in ("scheming_judge_v3", "debug_judge_v3") if name.split("_")[0] in args.judges.split(",")}
        if not args.no_viewer:
            write_all_transcripts_and_index(scored, args.viewer_dir, eval_id=Path(p).stem.split("_")[-1] + "-v3")
        summary.append({"source": os.path.relpath(p, ROOT), "dest": dest.name, "seed": seed, "samples": len(scored.samples), "requests": n, "valid": ok})
        print(f"[{i+1}/{len(srcs)}] {seed:36s} samples={len(scored.samples)} requests={n} valid={ok} total_used={used}", flush=True)
        (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({"logs": len(summary), "requests": used}), flush=True)


if __name__ == "__main__":
    main()
