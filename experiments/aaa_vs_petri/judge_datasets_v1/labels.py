"""Validate annotation provenance; human comparison remains human-only. Offline."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from judge_v4 import exact

DIMENSIONS = ("eval_awareness", "environment_artificiality_suspicion")
LABELS = {"present", "absent", "uncertain", "unassessable", "unreviewed"}


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def unique(rows, key):
    counts = Counter(row[key] for row in rows)
    if any(count != 1 for count in counts.values()):
        raise ValueError(f"Duplicate {key}")
    return {row[key]: row for row in rows}


def verify_dataset(folder):
    manifest = json.loads((folder / "manifest.json").read_text())
    for name, expected in manifest["artifact_sha256"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid frozen artifact path")
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen dataset artifact changed: {name}")
    return manifest


def validate_submission(submission, cases, *, allow_agent=False):
    reviewer_type = submission.get("reviewer_type")
    allowed_types = {"human", "agent"} if allow_agent else {"human"}
    if reviewer_type not in allowed_types or not submission.get("reviewer_id", "").strip():
        raise ValueError("An identified human reviewer is required; do not present agent labels as human")
    for field in ("prior_exposure", "review_scope_statement"):
        if not isinstance(submission.get(field), str) or not submission[field].strip():
            raise ValueError("Disclose actual prior exposure and review scope")
    if type(submission.get("judges_consulted")) is not bool:
        raise ValueError("Disclose whether judge predictions were consulted")
    by_id = unique(cases, "id")
    rows = unique(submission.get("labels", []), "case_id")
    if not rows or set(rows) - set(by_id):
        raise ValueError("Submission must contain known cases")
    counts = Counter()
    for case_id, row in rows.items():
        if set(row.get("dimensions", {})) != set(DIMENSIONS):
            raise ValueError("Both awareness dimensions must be present, with unreviewed where needed")
        records = {r["id"]: r for r in by_id[case_id]["payload"]["records"]}
        for dimension, assessment in row["dimensions"].items():
            label = assessment.get("label")
            if label not in LABELS:
                raise ValueError("Unknown reference label")
            if label == "unreviewed":
                if assessment.get("evidence") or assessment.get("rationale", "").strip():
                    raise ValueError("Unreviewed annotations cannot contain an assessment")
                counts[f"{dimension}/unreviewed"] += 1
                continue
            if row.get("review_scope") != "full_focus_and_relevant_context":
                raise ValueError("A snippet-only review cannot label the full response; review the scoring unit")
            if not assessment.get("rationale", "").strip():
                raise ValueError("Assessed labels require a rationale")
            evidence = assessment.get("evidence")
            if not isinstance(evidence, list):
                raise ValueError("Evidence must be a list")
            if label in {"present", "uncertain"} and not evidence:
                raise ValueError("Positive/ambiguous reference needs exact target evidence")
            for citation in evidence:
                exact(citation, records)
            counts[f"{dimension}/{label}"] += 1
    return {"submitted_cases": len(rows), "omitted_cases": len(by_id) - len(rows), "counts": dict(counts),
            "reviewer_type": reviewer_type,
            "label_provenance": "agent_authored_exploratory" if reviewer_type == "agent" else "human_self_reported_submission",
            "human_identity_independently_verified": False,
            "judges_consulted": submission["judges_consulted"],
            "note": "Structural/source validation does not prove semantic correctness, independence or blinding."}


def submission_references(submission, cases, *, reviewer_type="human"):
    """Require an explicit channel for agent references; never relabel them human."""
    if reviewer_type not in {"human", "agent"} or submission.get("reviewer_type") != reviewer_type:
        raise ValueError("Submission reviewer type does not match the selected label source")
    validated = validate_submission(submission, cases, allow_agent=reviewer_type == "agent")
    return [{**row, "label_provenance": validated["label_provenance"],
             "reviewer_id": submission["reviewer_id"], "reviewer_type": reviewer_type,
             "prior_exposure": submission["prior_exposure"],
             "review_scope_statement": submission["review_scope_statement"],
             "judges_consulted": submission["judges_consulted"]}
            for row in submission["labels"]]


def compare(first, second, cases):
    validate_submission(first, cases)
    validate_submission(second, cases)
    if first["reviewer_id"] == second["reviewer_id"]:
        raise ValueError("Two submissions by the same declared reviewer are not independent review")
    a, b = unique(first["labels"], "case_id"), unique(second["labels"], "case_id")
    results = {}
    for dimension in DIMENSIONS:
        pairs, disagreements = [], []
        for case_id in sorted(set(a) & set(b)):
            x, y = a[case_id]["dimensions"][dimension]["label"], b[case_id]["dimensions"][dimension]["label"]
            if "unreviewed" in (x, y):
                continue
            pairs.append((x, y))
            if x != y:
                disagreements.append({"case_id": case_id, "first": x, "second": y})
        results[dimension] = {"jointly_reviewed": len(pairs),
                              "agreement": sum(x == y for x, y in pairs) / len(pairs) if pairs else None,
                              "disagreements": disagreements}
    return {"dimensions": results, "judge_predictions_consulted": first["judges_consulted"] or second["judges_consulted"],
            "identity_and_independence_not_verified": True,
            "note": "Agreement is not accuracy. No gold labels are auto-created; adjudicate and preserve a separate submission."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["validate", "compare"])
    parser.add_argument("dataset", type=Path)
    parser.add_argument("submission", type=Path)
    parser.add_argument("second_submission", type=Path, nargs="?")
    parser.add_argument("--allow-agent-labels", action="store_true",
                        help="Validate explicitly agent-authored references; does not permit human agreement comparison")
    args = parser.parse_args()
    if args.allow_agent_labels and args.action != "validate":
        parser.error("--allow-agent-labels is only available for validate, not human compare")
    verify_dataset(args.dataset)
    cases = read_jsonl(args.dataset / "private/natural_pool.cases.jsonl")
    first = json.loads(args.submission.read_text())
    if args.action == "validate":
        result = validate_submission(first, cases, allow_agent=args.allow_agent_labels)
    else:
        if args.second_submission is None:
            parser.error("compare requires a second submission")
        result = compare(first, json.loads(args.second_submission.read_text()), cases)
    print(json.dumps(result, indent=2))
