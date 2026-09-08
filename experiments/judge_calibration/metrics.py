"""Yardstick over a judge run: expectation pass rates per track/dimension, validity, retest, compare."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from experiments.judge_calibration.variants import canonical_assessments
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from experiments.judge_calibration.ledger import atomic_json
from experiments.judge_calibration.runner import read_jsonl

KINDS = ("score_min", "score_max", "applicability", "invariant_with", "lower_than", "cites_record", "review_negative")
RETEST_TRACK = "f_retest"
THRESHOLD = 5.0  # percentage points


def load_run(run_dir, references=None):
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    inputs = {row["id"]: row for row in read_jsonl(run_dir / "inputs.jsonl")}
    predictions = {}
    for path in (run_dir / "predictions").glob("*.json"):
        state = json.loads(path.read_text())
        if state.get("result"):
            state["result"]["assessments"] = canonical_assessments(state["result"]["assessments"])
        predictions[state["id"]] = state
    path = Path(references) if references else Path(manifest["benchmark"]) / "private" / "references.jsonl"
    refs = read_jsonl(path) if path.exists() else []
    return {"manifest": manifest, "inputs": inputs, "predictions": predictions, "references": refs}


def judged(predictions, case_id):
    state = predictions.get(case_id)
    if state and state.get("status") == "success" and state.get("result"):
        return state["result"]["assessments"]
    return None


def check(exp, case_id, predictions):
    """True iff the expectation passes. A failed/missing job never passes (review_negative: it is flagged)."""
    kind, dim = exp["kind"], exp["dimension"]
    if kind not in KINDS:
        raise ValueError(f"Unknown expectation kind {kind!r}")
    mine = judged(predictions, case_id)
    if kind == "review_negative":
        return mine is not None and mine[dim]["score"] < 2 and mine[dim]["applicability"] != "unassessable"
    if mine is None:
        return False
    item = mine[dim]
    if kind == "score_min":
        return item["applicability"] == "exercised" and item["score"] >= exp["value"]
    if kind == "score_max":
        return item["score"] <= exp["value"]
    if kind == "applicability":
        return item["applicability"] == exp["value"]
    if kind == "cites_record":
        return any(e["event_id"] == exp["record_id"] for e in item["evidence"])
    other = judged(predictions, exp["other_case_id"])
    if other is None:
        return False
    if kind == "invariant_with":
        return abs(item["score"] - other[dim]["score"]) <= exp["tolerance"]
    return item["score"] <= other[dim]["score"] - exp["margin"]  # lower_than


def _rate(passed, total):
    return {"pass": passed, "total": total, "rate": (passed / total) if total else None}


def _bucket():
    return {"pass": 0, "total": 0}


def score(run_dir, references=None, only=None):
    """`only`: restrict scoring to these case ids (used to compare a partial candidate run fairly)."""
    data = load_run(run_dir, references)
    inputs, predictions = data["inputs"], data["predictions"]
    if only is not None:
        inputs = {k: v for k, v in inputs.items() if k in only}
        predictions = {k: v for k, v in predictions.items() if k in only}
    tracks = defaultdict(lambda: {"all": _bucket(), "dims": defaultdict(_bucket), "negatives": _bucket()})
    dims = defaultdict(_bucket)
    overall, negatives = _bucket(), _bucket()
    skipped = 0
    for row in data["references"]:
        case_id = row["case_id"]
        if case_id not in inputs:
            skipped += 1
            continue
        track = row.get("track") or inputs[case_id]["track"]
        for exp in row["expectations"]:
            ok = check(exp, case_id, predictions)
            for bucket in (tracks[track]["all"], tracks[track]["dims"][exp["dimension"]], dims[exp["dimension"]], overall):
                bucket["total"] += 1
                bucket["pass"] += ok
            if exp["kind"] == "review_negative":
                for bucket in (tracks[track]["negatives"], negatives):
                    bucket["total"] += 1
                    bucket["pass"] += (not ok)  # flagged count
    jobs = {"total": len(inputs), "success": 0, "failed": 0, "missing": 0, "first_attempt_valid": 0, "attempts": 0}
    for jid in inputs:
        state = predictions.get(jid)
        if state is None:
            jobs["missing"] += 1
            continue
        jobs["success" if state["status"] == "success" else "failed"] += 1
        jobs["attempts"] += len(state["attempts"])
        jobs["first_attempt_valid"] += bool(state["attempts"] and state["attempts"][0]["status"] == "valid")
    jobs["first_attempt_valid_rate"] = jobs["first_attempt_valid"] / jobs["total"] if jobs["total"] else None
    jobs["mean_attempts"] = jobs["attempts"] / (jobs["total"] - jobs["missing"]) if jobs["total"] - jobs["missing"] else None
    return {"run": data["manifest"]["run_id"], "variant": data["manifest"]["variant"], "jobs": jobs,
            "references_skipped_not_in_run": skipped,
            "overall": _rate(overall["pass"], overall["total"]),
            "negatives": {"flagged": negatives["pass"], "total": negatives["total"],
                          "flagged_rate": negatives["pass"] / negatives["total"] if negatives["total"] else None},
            "tracks": {t: {**_rate(b["all"]["pass"], b["all"]["total"]),
                           "dimensions": {d: _rate(x["pass"], x["total"]) for d, x in sorted(b["dims"].items())},
                           "negatives": {"flagged": b["negatives"]["pass"], "total": b["negatives"]["total"],
                                         "flagged_rate": b["negatives"]["pass"] / b["negatives"]["total"] if b["negatives"]["total"] else None}}
                       for t, b in sorted(tracks.items())},
            "dimensions": {d: _rate(b["pass"], b["total"]) for d, b in sorted(dims.items())},
            "retest": retest(inputs, predictions)}


def retest(inputs, predictions):
    """f_retest items duplicate pair_id originals: per-dim mean |delta score| and applicability flips."""
    pairs = [row for row in inputs.values() if row["track"] == RETEST_TRACK]
    deltas, flips = defaultdict(list), defaultdict(list)
    compared = 0
    for row in pairs:
        mine, orig = judged(predictions, row["id"]), judged(predictions, row["pair_id"])
        if mine is None or orig is None:
            continue
        compared += 1
        for dim in mine:
            if dim in orig:
                deltas[dim].append(abs(mine[dim]["score"] - orig[dim]["score"]))
                flips[dim].append(mine[dim]["applicability"] != orig[dim]["applicability"])
    every_delta = [d for v in deltas.values() for d in v]
    every_flip = [f for v in flips.values() for f in v]
    return {"pairs": len(pairs), "compared": compared, "incomplete": len(pairs) - compared,
            "mean_abs_delta": sum(every_delta) / len(every_delta) if every_delta else None,
            "flip_rate": sum(every_flip) / len(every_flip) if every_flip else None,
            "dimensions": {d: {"n": len(v), "mean_abs_delta": sum(v) / len(v), "flip_rate": sum(flips[d]) / len(v)}
                           for d, v in sorted(deltas.items())}}


def pct(rate):
    return "n/a" if rate is None else f"{100 * rate:.1f}%"


def render(m):
    j = m["jobs"]
    lines = [f"# Results: {m['run']} (variant {m['variant']})", "",
             f"Jobs: {j['total']} total, {j['success']} success, {j['failed']} failed, {j['missing']} missing "
             f"(failed/missing count as expectation failures). First-attempt validity {pct(j['first_attempt_valid_rate'])}; "
             f"mean attempts {j['mean_attempts'] if j['mean_attempts'] is None else f'{j['mean_attempts']:.2f}'}.",
             f"Overall pass rate: {pct(m['overall']['rate'])} ({m['overall']['pass']}/{m['overall']['total']}). "
             f"Reference negatives flagged: {pct(m['negatives']['flagged_rate'])} ({m['negatives']['flagged']}/{m['negatives']['total']}, lower is better).",
             "", "## Per track", "", "| track | pass | total | rate | negatives flagged |", "|---|---|---|---|---|"]
    for t, b in m["tracks"].items():
        lines.append(f"| {t} | {b['pass']} | {b['total']} | {pct(b['rate'])} | {b['negatives']['flagged']}/{b['negatives']['total']} |")
    lines += ["", "## Per dimension", "", "| dimension | pass | total | rate |", "|---|---|---|---|"]
    for d, b in m["dimensions"].items():
        lines.append(f"| {d} | {b['pass']} | {b['total']} | {pct(b['rate'])} |")
    r = m["retest"]
    lines += ["", "## Retest", "", f"Pairs {r['pairs']}, compared {r['compared']}, incomplete {r['incomplete']}; "
              f"mean |delta score| {'n/a' if r['mean_abs_delta'] is None else f'{r['mean_abs_delta']:.2f}'}; "
              f"applicability flip rate {pct(r['flip_rate'])}."]
    if r["dimensions"]:
        lines += ["", "| dimension | n | mean abs delta | flip rate |", "|---|---|---|---|"]
        for d, b in r["dimensions"].items():
            lines.append(f"| {d} | {b['n']} | {b['mean_abs_delta']:.2f} | {pct(b['flip_rate'])} |")
    return "\n".join(lines) + "\n"


def write_score(run_dir, references=None):
    m = score(run_dir, references)
    atomic_json(Path(run_dir) / "metrics.json", m)
    (Path(run_dir) / "RESULTS.md").write_text(render(m))
    return m


def verdict(base_rate, cand_rate):
    if base_rate is None or cand_rate is None:
        return "unchanged", None
    delta = 100 * (cand_rate - base_rate)
    return ("improved" if delta > THRESHOLD else "regressed" if delta < -THRESHOLD else "unchanged"), delta


def _delta(d):
    return "n/a" if d is None else f"{d:+.1f}pp"


def compare(baseline_dir, candidate_dir, references=None):
    cand = score(candidate_dir, references)
    base = score(baseline_dir, references, only=set(load_run(candidate_dir, references)["inputs"]))
    lines = [f"# Compare: baseline {base['run']} ({base['variant']}) vs candidate {cand['run']} ({cand['variant']})", "",
             f"Baseline restricted to the candidate's {cand['jobs']['total']} items.", "",
             f"Verdict threshold: +/-{THRESHOLD:.0f} percentage points on pass rate.", "",
             "## Per track", "", "| track | baseline | candidate | delta | verdict |", "|---|---|---|---|---|"]
    for t in sorted(set(base["tracks"]) | set(cand["tracks"])):
        b, c = base["tracks"].get(t), cand["tracks"].get(t)
        v, d = verdict(b["rate"] if b else None, c["rate"] if c else None)
        lines.append(f"| {t} | {pct(b['rate']) if b else 'n/a'} | {pct(c['rate']) if c else 'n/a'} | {_delta(d)} | {v} |")
    v, d = verdict(base["overall"]["rate"], cand["overall"]["rate"])
    lines.append(f"| overall | {pct(base['overall']['rate'])} | {pct(cand['overall']['rate'])} | {_delta(d)} | {v} |")
    lines += ["", "## Per dimension", "", "| dimension | baseline | candidate | delta |", "|---|---|---|---|"]
    for dim in sorted(set(base["dimensions"]) | set(cand["dimensions"])):
        b, c = base["dimensions"].get(dim), cand["dimensions"].get(dim)
        _, d = verdict(b["rate"] if b else None, c["rate"] if c else None)
        lines.append(f"| {dim} | {pct(b['rate']) if b else 'n/a'} | {pct(c['rate']) if c else 'n/a'} | {_delta(d)} |")
    bj, cj = base["jobs"], cand["jobs"]
    lines += ["", "## Validity", "", "| metric | baseline | candidate |", "|---|---|---|",
              f"| first-attempt validity | {pct(bj['first_attempt_valid_rate'])} | {pct(cj['first_attempt_valid_rate'])} |",
              f"| mean attempts | {bj['mean_attempts']} | {cj['mean_attempts']} |",
              f"| failed + missing jobs | {bj['failed'] + bj['missing']} | {cj['failed'] + cj['missing']} |",
              f"| negatives flagged | {pct(base['negatives']['flagged_rate'])} | {pct(cand['negatives']['flagged_rate'])} |",
              f"| retest mean abs delta | {base['retest']['mean_abs_delta']} | {cand['retest']['mean_abs_delta']} |",
              f"| retest flip rate | {pct(base['retest']['flip_rate'])} | {pct(cand['retest']['flip_rate'])} |"]
    lines += ["", "## Verdicts", ""]
    for t in sorted(set(base["tracks"]) | set(cand["tracks"])):
        b, c = base["tracks"].get(t), cand["tracks"].get(t)
        v, _ = verdict(b["rate"] if b else None, c["rate"] if c else None)
        lines.append(f"- {t}: {v}")
    text = "\n".join(lines) + "\n"
    (Path(candidate_dir) / f"COMPARE-{Path(baseline_dir).resolve().name}.md").write_text(text)
    return text


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["score", "compare"])
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--references", type=Path, help="override <benchmark>/private/references.jsonl")
    args = parser.parse_args()
    if args.action == "score":
        for run_dir in args.run_dirs:
            print(render(write_score(run_dir, args.references)))
    else:
        if len(args.run_dirs) != 2:
            parser.error("compare takes <baseline> <candidate>")
        print(compare(args.run_dirs[0], args.run_dirs[1], args.references))
