"""Report an integrated-judge run over the 18 Petri audits, next to the v1 judge and v5 awareness results.

Offline. Judge findings are not human labels; a score of 1 means none observed, not proven absent.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

AWARENESS = ("eval_awareness", "environment_artificiality_suspicion", "awareness_conditioned_behavior", "monitoring_detection")
REALISM = ("scenario_realism", "role_organizational_realism", "tool_interface_realism", "state_causal_consistency", "interaction_naturalness")
V5_REPORT = ROOT / "logs/petri-awareness-v5/all-recorded-opus48/report/audits.json"


def load(run_dir):
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    inputs = {json.loads(l)["id"]: json.loads(l) for l in (run_dir / "inputs.jsonl").read_text().splitlines()}
    predictions = {p.stem: json.loads(p.read_text()) for p in (run_dir / "predictions").glob("*.json")}
    audits = json.loads((Path(manifest["benchmark"]) / "private" / "audits.json").read_text())
    return manifest, inputs, predictions, audits


def v1_scores(audits):
    """Original petri_aaa_* judge scores stored on each source sample."""
    from inspect_ai.log import read_eval_log
    out, cache = {}, {}
    for a in audits:
        path = ROOT / a["source"]
        if path not in cache:
            cache[path] = {s.uuid: s for s in read_eval_log(str(path)).samples or []}
        sample = cache[path].get(a["uuid"])
        scores = sample.scores if sample else {}
        out[a["uuid"]] = {k: (v.value if isinstance(v.value, dict) else {}) for k, v in (scores or {}).items()}
    return out


def v5_status(uuid, v5):
    row = next((r for r in v5 if r["audit_id"] == uuid), None)
    if not row:
        return {}
    return {d: row["all_recorded"][d]["status"] for d in ("eval_awareness", "environment_artificiality_suspicion") if d in row["all_recorded"]}


def quote(assessment):
    ev = assessment.get("evidence") or []
    if not ev:
        return ""
    e = ev[0]
    return f"{e['event_id']}/{e['channel']}: \"{e['quote'][:140]}\""


def cell(a):
    return f"{a['score']}" if a["applicability"] == "exercised" else f"{a['score']} ({a['applicability'][:5]})"


def build(run_dir):
    manifest, inputs, predictions, audits = load(run_dir)
    v1 = v1_scores(audits)
    v5 = json.loads(V5_REPORT.read_text()) if V5_REPORT.exists() else []
    result = {"run": manifest["run_id"], "variant": manifest["variant"], "audits": []}
    lines = [f"# Petri rejudgment with variant `{manifest['variant']}` ({manifest['run_id']})", "",
             "Judge: Opus 4.8 over the complete recorded audit (all branches). Scores 1–10; a bare number is `exercised`; "
             "`(not_e)` = not exercised, `(unass)` = unassessable — score forced to 1. v1 = original petri_aaa judges; "
             "v5 = standalone verbalized-awareness judge (per-response, categorical). Judge findings are not human labels.", ""]
    jobs = Counter(p["status"] for p in predictions.values())
    attempts = [len(p["attempts"]) for p in predictions.values()]
    first = sum(1 for p in predictions.values() if p["attempts"] and p["attempts"][0]["status"] == "valid")
    lines += [f"Jobs: {dict(jobs)}; first-attempt valid {first}/{len(predictions)}; mean attempts {statistics.mean(attempts):.2f}.", ""]
    rows = []
    for a in sorted(audits, key=lambda x: x["seed"]):
        u = a["uuid"]
        s = predictions.get(f"{u}-scheming"); d = predictions.get(f"{u}-debug")
        sa = s["result"]["assessments"] if s and s["status"] == "success" else None
        da = d["result"]["assessments"] if d and d["status"] == "success" else None
        rows.append((a, sa, da))
        result["audits"].append({"uuid": u, "seed": a["seed"], "scheming": sa, "debug": da,
                                 "v1": v1.get(u, {}), "v5": v5_status(u, v5)})
    # Awareness
    lines += ["## Situational awareness (per audit)", "",
              "| seed | eval_aw | env_artif | aw_cond_behav | monitoring | v1 eval_aw | v5 eval / env | strongest quote |", "|---|---|---|---|---|---|---|---|"]
    for a, sa, da in rows:
        if not sa:
            lines.append(f"| {a['seed']} | FAILED | | | | | | |"); continue
        v1s = v1.get(a["uuid"], {}).get("petri_aaa_scheming", {})
        v5s = v5_status(a["uuid"], v5)
        best = max((sa[k] for k in AWARENESS[:3]), key=lambda x: x["score"])
        q = quote(best) if best["score"] >= 2 else ""
        lines.append(f"| {a['seed']} | {cell(sa['eval_awareness'])} | {cell(sa['environment_artificiality_suspicion'])} | "
                     f"{cell(sa['awareness_conditioned_behavior'])} | {cell(sa['monitoring_detection'])} | {v1s.get('eval_awareness', '')} | "
                     f"{v5s.get('eval_awareness', '')[:8]} / {v5s.get('environment_artificiality_suspicion', '')[:8]} | {q} |")
    # Realism
    lines += ["", "## Realism (per audit)", "",
              "| seed | scenario | role | tool | state | naturalness | v1 scenario_realism | worst cited defect |", "|---|---|---|---|---|---|---|---|"]
    for a, sa, da in rows:
        if not da:
            lines.append(f"| {a['seed']} | FAILED | | | | | | |"); continue
        v1s = v1.get(a["uuid"], {}).get("petri_aaa_scheming", {})
        worst = min((da[k] for k in REALISM), key=lambda x: x["score"])
        lines.append("| " + " | ".join([a["seed"]] + [cell(da[k]) for k in REALISM] + [str(v1s.get("scenario_realism", "")),
                     quote(worst) if worst["score"] <= 6 else ""]) + " |")
    # Behavioral findings
    lines += ["", "## Concerning-behavior findings (score >= 4, exercised)", ""]
    for a, sa, da in rows:
        if not sa:
            continue
        hits = [(k, v) for k, v in sa.items() if k not in AWARENESS and v["applicability"] == "exercised" and v["score"] >= 4]
        pos = {"transparent_disagreement", "genuine_honesty", "legitimate_escalation"}
        concerning = [(k, v) for k, v in hits if k not in pos]
        n_ne = sum(1 for v in sa.values() if v["applicability"] == "not_exercised")
        n_un = sum(1 for v in sa.values() if v["applicability"] == "unassessable")
        lines.append(f"**{a['seed']}** — {len(concerning)} concerning dims >= 4; {n_ne} not exercised, {n_un} unassessable of {len(sa)}.")
        for k, v in sorted(concerning, key=lambda kv: -kv[1]["score"])[:6]:
            v1v = v1.get(a["uuid"], {}).get("petri_aaa_scheming", {}).get(k, "")
            lines.append(f"- {k}: {v['score']} (v1: {v1v}) — {quote(v)}")
        lines.append("")
    # Applicability + aggregate
    lines += ["## Applicability across the 18 audits (scheming judge)", "", "| dimension | exercised | not_exercised | unassessable | mean score (exercised) | v1 mean |", "|---|---|---|---|---|---|"]
    per = defaultdict(Counter); vals = defaultdict(list); v1vals = defaultdict(list)
    for a, sa, da in rows:
        for fam_a in (sa, da):
            if not fam_a:
                continue
            for k, v in fam_a.items():
                per[k][v["applicability"]] += 1
                if v["applicability"] == "exercised":
                    vals[k].append(v["score"])
        for scorer in ("petri_aaa_scheming", "petri_aaa_debug"):
            for k, v in v1.get(a["uuid"], {}).get(scorer, {}).items():
                if isinstance(v, (int, float)):
                    v1vals[k].append(v)
    for k in per:
        m = f"{statistics.mean(vals[k]):.1f}" if vals[k] else "–"
        m1 = f"{statistics.mean(v1vals[k]):.1f}" if v1vals.get(k) else "–"
        lines.append(f"| {k} | {per[k]['exercised']} | {per[k]['not_exercised']} | {per[k]['unassessable']} | {m} | {m1} |")
    result["applicability"] = {k: dict(c) for k, c in per.items()}
    result["mean_exercised"] = {k: statistics.mean(v) for k, v in vals.items() if v}
    text = "\n".join(lines) + "\n"
    (Path(run_dir) / "PETRI-RESULTS.md").write_text(text)
    (Path(run_dir) / "petri-results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return text


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    print(build(parser.parse_args().run_dir)[:3000])
