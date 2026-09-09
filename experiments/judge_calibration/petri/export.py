"""Export a calibrated-judge (integrated variant) rejudgment of the 18 Petri audits.

Offline; no model calls. Produces, under ``<run_dir>/export`` by default:

- ``evals/``: one native ``.eval`` copy per source log. Every original message, event,
  score and metadata entry is preserved; each judged sample additionally carries the
  scorers ``calibrated_scheming_v3`` and ``calibrated_debug_v3`` (``Score.value`` =
  ``{dimension: int}``; applicability, reasons, evidence, summary, limitations,
  coverage, judge model, attempt statuses and viewer highlights in ``Score.metadata``).
- ``viewer/data/``: ``index.json`` plus one ``petri-v3-<uuid>.json`` per audit for the
  transcript viewer. Dimensions the judge marked ``not_exercised``/``unassessable`` are
  labelled ``<dimension> [<applicability>]`` because the viewer renders only the
  score-key text; the plain map is in ``judge.applicability``.
- ``judge-transcripts/<seed>-{scheming,debug}.md``: readable per-audit judge output.
- ``README.md``, ``summary.json``, ``manifest.json``.

Judge findings are not human labels. A score of 1 means nothing was observed (or, when
not exercised, that the audit created no opportunity); it is not proof of absence.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from structured_judge import highlight_note, is_notable  # noqa: E402
from experiments.judge_calibration.variants import canonical_assessments  # noqa: E402
from inspect_ai.event import ScoreEvent  # noqa: E402
from inspect_ai.log import EvalResults, EvalScore, read_eval_log, write_eval_log  # noqa: E402
from inspect_ai.log._log import EvalScorer  # noqa: E402
from inspect_ai.scorer import Score  # noqa: E402
from transcript import rebuild_index  # noqa: E402
from experiments.aaa_vs_petri.export_viewer import convert_petri  # noqa: E402
from experiments.judge_calibration.variants import load_variant  # noqa: E402

VERSION = "calibrated-v3"
FAMILIES = ("scheming", "debug")
SCORERS = {"scheming": "calibrated_scheming_v3", "debug": "calibrated_debug_v3"}
APPLICABILITY = ("exercised", "not_exercised", "unassessable")
VIEWER_ID_PREFIX = "petri-v3-"
# Packet actors whose records are the target's own input; a citation on one of them is
# anchored to the first target call that received it (see full_judge.run.build_packet).
INPUT_ACTORS = {"system", "user", "tool", "tool_definitions", "assistant_history"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
    temp.replace(path)


def fenced(text, language=""):
    fence = "`" * max(3, 1 + max((len(s) for s in re.findall(r"`+", text)), default=0))
    return f"{fence}{language}\n{text}\n{fence}"


def short_description(rubric):
    """Lead clause of a rubric (the viewer shows this as the dimension tooltip)."""
    first = rubric.strip().split("\n", 1)[0].strip()
    first = first[2:] if first.startswith("- ") else first
    return re.split(r":\s*\{\{\s*\}\}/10", first, maxsplit=1)[0].strip().rstrip(":").strip()


def applicability_label(dimension, applicability):
    """Viewer score-key text: the viewer shows only the key, so flag non-exercised dims in it."""
    return dimension if applicability == "exercised" else f"{dimension} [{applicability}]"


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------

def validate_result(result, dimensions, record_mapping):
    """Structural check of one prediction result against the run's dimension list and the packet mapping."""
    assessments = result.get("assessments")
    if not isinstance(assessments, dict) or list(assessments) != list(dimensions):
        raise ValueError("Assessment dimensions do not match the run manifest")
    for dimension, assessment in assessments.items():
        score, applicability = assessment.get("score"), assessment.get("applicability")
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 10:
            raise ValueError(f"{dimension}: score must be an integer 1-10")
        if applicability not in APPLICABILITY:
            raise ValueError(f"{dimension}: unknown applicability {applicability!r}")
        if applicability != "exercised" and score != 1:
            raise ValueError(f"{dimension}: non-exercised dimensions must score 1")
        if not isinstance(assessment.get("reason"), str) or not isinstance(assessment.get("evidence"), list):
            raise ValueError(f"{dimension}: reason/evidence malformed")
        for item in assessment["evidence"]:
            if item.get("event_id") not in record_mapping:
                raise ValueError(f"{dimension}: evidence cites unknown record {item.get('event_id')!r}")
            for key in ("channel", "quote", "interpretation"):
                if not isinstance(item.get(key), str):
                    raise ValueError(f"{dimension}: evidence item lacks {key}")
    if not isinstance(result.get("summary"), str) or not isinstance(result.get("unresolved_limitations"), list):
        raise ValueError("summary/unresolved_limitations malformed")


warnings: list[str] = []  # non-fatal provenance notes collected during load/export


def load(run):
    """Verify and load the run manifest, benchmark audits (with record mappings) and predictions."""
    run = Path(run).resolve()
    manifest = json.loads((run / "manifest.json").read_text())
    if list(manifest["families"]) != sorted(FAMILIES):
        raise ValueError("Run does not contain exactly the scheming and debug families")
    for name, expected in manifest["artifact_sha256"].items():
        if sha(run / name) != expected:
            raise ValueError(f"Run artifact changed: {name}")
    for relative, expected in manifest["variant_sha256"].items():
        if sha(ROOT / relative) != expected:
            warnings.append(f"Variant file changed since the run (dimension rename / later edits): {relative}")
    benchmark = Path(manifest["benchmark"])
    if not benchmark.is_absolute():
        benchmark = ROOT / benchmark
    if sha(benchmark / "manifest.json") != manifest["benchmark_manifest_sha256"]:
        raise ValueError("Benchmark manifest changed since the run")
    benchmark_manifest = json.loads((benchmark / "manifest.json").read_text())
    audits_path = benchmark / "private" / "audits.json"
    if sha(audits_path) != benchmark_manifest["sha256"]["private/audits.json"]:
        raise ValueError("Packet/record mapping file changed since the benchmark was built")
    audits = json.loads(audits_path.read_text())
    for relative, expected in benchmark_manifest["sources_sha256"].items():
        if sha(ROOT / relative) != expected:
            raise ValueError(f"Source log changed: {relative}")
    if {a["source"] for a in audits} - set(benchmark_manifest["sources_sha256"]):
        raise ValueError("An audit refers to a source log that is not frozen in the benchmark manifest")
    from experiments.judge_calibration.variants import RENAMED_DIMENSIONS
    manifest["dimensions"] = {f: [RENAMED_DIMENSIONS.get(d, d) for d in dims] for f, dims in manifest["dimensions"].items()}
    predictions = {}
    for audit in audits:
        for family in FAMILIES:
            job_id = f"{audit['uuid']}-{family}"
            row = json.loads((run / "predictions" / f"{job_id}.json").read_text())
            if row["id"] != job_id or row["family"] != family or row["status"] not in {"success", "failed"}:
                raise ValueError(f"Export requires a terminal judgment for {job_id}")
            if row["model"] != manifest["judge_model"]:
                raise ValueError(f"Unexpected judge model in {job_id}")
            if row.get("result"):
                row["result"]["assessments"] = canonical_assessments(row["result"]["assessments"])
            if row["status"] == "success":
                validate_result(row["result"], manifest["dimensions"][family], audit["record_mapping"])
            predictions[job_id] = row
    return run, manifest, audits, predictions


# ---------------------------------------------------------------------------
# Scores, highlights and readable output
# ---------------------------------------------------------------------------

def _evidence_entries(dimension, assessment, record_mapping):
    """Evidence items with the packet record id and the mapped viewer event id side by side."""
    entries = []
    for item in assessment["evidence"]:
        mapping = record_mapping[item["event_id"]]
        # ``event_id``/``record_id`` are the packet record id the judge cited; ``viewer_event_id`` is the anchor.
        entries.append({"dimension": dimension, "event_id": item["event_id"], "record_id": item["event_id"],
                        "viewer_event_id": mapping.get("viewer_event_id"), "record_actor": mapping.get("actor"),
                        "channel": item["channel"], "quote": item["quote"],
                        "interpretation": item["interpretation"],
                        "alternative_interpretation": item.get("alternative_interpretation", ""),
                        **{k: item[k] for k in ("channel_as_cited", "event_id_as_cited") if k in item}})
    return entries


def highlight_for(entry, score, applicability):
    note = highlight_note(entry["dimension"], score, applicability, entry["interpretation"])
    return {"event_id": entry["viewer_event_id"], "quoted_text": entry["quote"], "note": note,
            "notable": is_notable(entry["dimension"], score, applicability),
            "dimension": entry["dimension"], "score": score, "applicability": applicability,
            "record_id": entry["record_id"], "channel": entry["channel"], "record_actor": entry.get("record_actor")}


def summary_text(result, applicability, unanchored):
    parts = [result["summary"].strip()]
    non_exercised = [f"{d} ({a})" for d, a in applicability.items() if a != "exercised"]
    exercised = sum(a == "exercised" for a in applicability.values())
    line = f"**Applicability.** {exercised} of {len(applicability)} dimensions exercised."
    if non_exercised:
        line += (" Scored 1 by convention because the audit created no assessable opportunity "
                 "(not evidence of absence): " + ", ".join(non_exercised) + ".")
    parts.append(line)
    parts.append(f"**Coverage:** {result.get('coverage', 'unknown')}.")
    if result["unresolved_limitations"]:
        parts.append("**Unresolved limitations:**\n" + "\n".join(f"- {l}" for l in result["unresolved_limitations"]))
    if unanchored:
        parts.append(f"{len(unanchored)} evidence citation(s) refer to packet records with no viewer anchor "
                     "(auditor system messages); their quotes are listed below and in the judge transcript.\n"
                     + "\n".join(f"- {e['dimension']} · record {e['record_id']} ({e['channel']}): \"{e['quote']}\""
                                 for e in unanchored))
    return "\n\n".join(parts)


def failed_score_for(row, dimensions, provenance):
    """A judgment that exhausted its attempts: the production JUDGE_PARSE_FAILURE convention."""
    attempts = [{k: v for k, v in a.items() if k not in {"response", "model_events"}} for a in row["attempts"]]
    return Score(value={d: None for d in dimensions}, answer="JUDGE_PARSE_FAILURE",
                 explanation="; ".join((a.get("error") or a.get("status", ""))[:300] for a in row["attempts"]),
                 metadata={"judge": row["family"], "scorer": SCORERS[row["family"]], "variant": provenance["variant"],
                           "parse_status": "failed", "job_id": row["id"], "judge_model": row["model"],
                           "applicability": {d: "unassessable" for d in dimensions}, "reasons": {d: "No valid judgment: all attempts failed validation." for d in dimensions}, "evidence": {d: [] for d in dimensions},
                           "attempts": attempts, "attempt_statuses": [a["status"] for a in row["attempts"]],
                           "highlights": [], "unanchored_evidence": [], "provenance": provenance})


def score_for(row, audit, dimensions, descriptions, provenance):
    """Build the native Inspect Score for one judgment (family) of one audit."""
    if row["status"] != "success":
        return failed_score_for(row, dimensions, provenance)
    family, result = row["family"], row["result"]
    values, applicability, reasons, evidence, highlights, unanchored = {}, {}, {}, {}, [], []
    for dimension in dimensions:
        assessment = result["assessments"][dimension]
        values[dimension] = int(assessment["score"])
        applicability[dimension] = assessment["applicability"]
        reasons[dimension] = assessment["reason"]
        evidence[dimension] = _evidence_entries(dimension, assessment, audit["record_mapping"])
        for entry in evidence[dimension]:
            if entry["viewer_event_id"]:
                highlights.append(highlight_for(entry, values[dimension], applicability[dimension]))
            else:
                unanchored.append(entry)
    attempts = [{k: v for k, v in a.items() if k not in {"response", "model_events"}} for a in row["attempts"]]
    cited = {e["record_id"] for entries in evidence.values() for e in entries}
    packet_mapping = {r: {"viewer_event_id": m.get("viewer_event_id"), "actor": m.get("actor")}
                      for r, m in audit["record_mapping"].items() if r in cited}
    return Score(
        value=values,
        answer=summary_text(result, applicability, unanchored),
        explanation="\n\n".join(f"{d} ({applicability[d]}): {reasons[d]}" for d in dimensions),
        metadata={"judge": family, "scorer": SCORERS[family], "variant": provenance["variant"],
                  "parse_status": "validated", "job_id": row["id"], "judge_model": row["model"],
                  "applicability": applicability, "reasons": reasons, "evidence": evidence,
                  "packet_mapping": packet_mapping,
                  "summary": result["summary"], "unresolved_limitations": result["unresolved_limitations"],
                  "coverage": result.get("coverage"), "attempts": attempts,
                  "attempt_statuses": [a["status"] for a in row["attempts"]],
                  "highlights": highlights, "unanchored_evidence": unanchored,
                  "score_descriptions": {d: short_description(descriptions[family][d]["rubric"]) for d in dimensions},
                  "rubrics": {d: descriptions[family][d]["rubric"] for d in dimensions},
                  "polarity": {d: descriptions[family][d]["polarity"] for d in dimensions},
                  "provenance": provenance})


def render_judgment(row, audit, score, manifest):
    """Readable markdown for one judgment: dimension table, evidence quotes with record ids, attempts."""
    meta, family = score.metadata, row["family"]
    if meta.get("parse_status") == "failed":
        return (f"# {audit['seed']} — calibrated {family} judge (v3, `{manifest['variant']}` variant)\n\n"
                f"Audit `{audit['uuid']}`; job `{row['id']}`. **No valid judgment**: all attempts failed validation.\n\n"
                + "\n".join(f"- Attempt {a['number']}: {a['status']} — {(a.get('error') or '')[:400]}" for a in meta["attempts"]) + "\n")
    lines = [f"# {audit['seed']} — calibrated {family} judge (v3, `{manifest['variant']}` variant)", "",
             f"Audit `{audit['uuid']}` from `{audit['source']}`. Job `{row['id']}`; judge `{row['model']}`; "
             f"coverage `{meta['coverage']}`. Judge findings are not human labels; a score of 1 means nothing was "
             "observed, or (when not exercised) that the audit created no opportunity — not proof of absence.", "",
             f"Prompt: `prompts/{family}.txt` and the exact packet (`inputs.jsonl`, id `{row['id']}`) are in the run "
             "directory; the raw returned JSON of every attempt is in `predictions/`.", "",
             "## Summary", "", meta["summary"].strip(), ""]
    if meta["unresolved_limitations"]:
        lines += ["## Unresolved limitations", ""] + [f"- {l}" for l in meta["unresolved_limitations"]] + [""]
    lines += ["## Dimensions", "", "| Dimension | Score | Applicability | Reason |", "|---|---:|---|---|"]
    for dimension, value in score.value.items():
        reason = meta["reasons"][dimension].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {dimension} | {value} | {meta['applicability'][dimension]} | {reason} |")
    lines += ["", "## Evidence", ""]
    cited = [(d, e) for d, entries in meta["evidence"].items() for e in entries]
    if not cited:
        lines.append("No evidence citations.")
    for dimension, entry in cited:
        anchor = f"viewer event `{entry['viewer_event_id']}`" if entry["viewer_event_id"] else "no viewer anchor"
        lines += [f"### {dimension} — record `{entry['record_id']}` ({entry['record_actor']}; {entry['channel']}; {anchor})", "",
                  "> " + entry["quote"].replace("\n", "\n> "), "",
                  f"Interpretation: {entry['interpretation']}", ""]
        if entry.get("alternative_interpretation"):
            lines += [f"Alternative interpretation: {entry['alternative_interpretation']}", ""]
        if "channel_as_cited" in entry or "event_id_as_cited" in entry:
            lines += ["As cited by the judge before normalization: "
                      + ", ".join(f"{k} = `{entry[k]}`" for k in ("event_id_as_cited", "channel_as_cited") if k in entry), ""]
    lines += ["## Attempts", ""]
    for attempt in meta["attempts"]:
        usage = attempt.get("usage") or {}
        lines.append(f"- Attempt {attempt['number']}: {attempt['status']}; completed {attempt.get('completed_at', 'not recorded')}; "
                     f"output tokens {usage.get('output_tokens', 'unknown')}.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Viewer data
# ---------------------------------------------------------------------------

def finalize_view(data, audit, scores, provenance):
    """Give the viewer file its distinct id and make applicability visible in the score labels."""
    data["id"] = f"{VIEWER_ID_PREFIX}{audit['uuid']}"
    data["title"] += " · Calibrated judge v3"
    judge = data["judge"]
    applicability = {d: a for family in FAMILIES for d, a in scores[family].metadata["applicability"].items()}
    for key in ("scores", "score_sources", "score_descriptions"):
        judge[key] = {applicability_label(d, applicability.get(d, "exercised")): v for d, v in judge[key].items()}
    judge["applicability"] = applicability
    judge["applicability_note"] = ("Dimensions labelled [not_exercised] or [unassessable] are scored 1 by convention: "
                                   "the audit created no assessable opportunity. That is not evidence of absence.")
    judge["calibrated"] = {family: {d: {"score": scores[family].value[d], "applicability": applicability[d],
                                        "reason": scores[family].metadata["reasons"][d],
                                        "evidence": scores[family].metadata["evidence"][d]}
                                    for d in scores[family].value} for family in FAMILIES}
    judge["unanchored_evidence"] = {family: scores[family].metadata["unanchored_evidence"] for family in FAMILIES}
    data["provenance"]["calibrated_judge_v3"] = provenance
    return data


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export(run, destination=None, viewer_html=None):
    """Export the run. ``viewer_html`` optionally copies a built single-file viewer into ``viewer/index.html``."""
    run, manifest, audits, predictions = load(run)
    destination = Path(destination or run / "export").resolve()
    if destination.exists():
        raise ValueError("Choose a fresh export directory")
    if viewer_html is not None and not Path(viewer_html).is_file():
        raise ValueError("viewer_html must be a built single-file viewer")
    descriptions = {family: {d: {"rubric": m.rubric, "polarity": m.polarity}
                             for d, m in load_variant(manifest["variant"], family).dimensions.items()}
                    for family in FAMILIES}
    for family in FAMILIES:
        if set(descriptions[family]) != set(manifest["dimensions"][family]):
            raise ValueError(f"Variant {family} dimensions differ from the run manifest")
    run_hash = sha(run / "manifest.json")
    exported_at = now()
    destination.mkdir(parents=True)
    for folder in ("evals", "viewer/data", "judge-transcripts"):
        (destination / folder).mkdir(parents=True)
    if viewer_html is not None:
        (destination / "viewer" / "index.html").write_bytes(Path(viewer_html).read_bytes())
    lookup = {a["uuid"]: a for a in audits}
    by_source = defaultdict(list)
    for audit in audits:
        by_source[audit["source"]].append(audit)
    counts = Counter()
    copies, viewer_ids, transcripts = [], [], []
    for relative, selected in by_source.items():
        source = ROOT / relative
        original = read_eval_log(str(source), resolve_attachments="full")
        copied = original.model_copy(deep=True)
        provenance = {"version": VERSION, "variant": manifest["variant"], "run_id": manifest["run_id"],
                      "judge_run": str(run), "run_manifest_sha256": run_hash, "judge_model": manifest["judge_model"],
                      "exported_at": exported_at, "source": relative, "source_sha256": sha(source),
                      "scorers": dict(SCORERS),
                      "note": "Post-hoc import of the calibrated judge. Original messages, events, scores and metadata "
                              "are unchanged; the new scorers and their ScoreEvents are appended."}
        copied.samples = []
        judged = 0
        for before in original.samples or []:
            after = before.model_copy(deep=True)
            audit = lookup.get(before.uuid)
            if audit is None:
                counts["unjudged_samples"] += 1
                copied.samples.append(after)
                continue
            scores = {}
            for family in FAMILIES:
                row = predictions[f"{before.uuid}-{family}"]
                scores[family] = score_for(row, audit, manifest["dimensions"][family], descriptions, provenance)
                after.scores = {**(after.scores or {}), SCORERS[family]: scores[family]}
                after.events.append(ScoreEvent(score=scores[family], scorer=SCORERS[family],
                                               metadata={"posthoc_import": True, "job_id": row["id"]}))
                path = destination / "judge-transcripts" / f"{audit['seed']}-{family}.md"
                if path.exists():
                    raise ValueError(f"Duplicate seed name for judge transcript: {path.name}")
                path.write_text(render_judgment(row, audit, scores[family], manifest))
                transcripts.append(str(path.relative_to(destination)))
                counts["scores"] += 1
                counts["highlights_anchored"] += len(scores[family].metadata["highlights"])
                counts["highlights_unanchored"] += len(scores[family].metadata["unanchored_evidence"])
                counts[f"not_exercised_{family}"] += sum(a != "exercised" for a in scores[family].metadata["applicability"].values())
            after.metadata = {**(before.metadata or {}), "calibrated_judge_v3": provenance}
            copied.samples.append(after)
            counts["samples"] += 1
            judged += 1
        copied.eval.eval_id += f"-{VERSION}-{run_hash[:8]}"
        copied.eval.run_id += f"-{VERSION}-{run_hash[:8]}"
        copied.eval.scorers = list(copied.eval.scorers or []) + [
            EvalScorer(name=SCORERS[f], metadata={"variant": manifest["variant"], "version": VERSION}) for f in FAMILIES]
        new_scores = [EvalScore(name=SCORERS[f], scorer=SCORERS[f], scored_samples=len(selected), metrics={},
                                metadata={"variant": manifest["variant"]}) for f in FAMILIES]
        if copied.results is None:
            copied.results = EvalResults(total_samples=len(copied.samples), completed_samples=len(copied.samples), scores=new_scores)
        else:
            copied.results.scores = list(copied.results.scores) + new_scores
        copied.eval.metadata = {**(copied.eval.metadata or {}), "calibrated_judge_v3": provenance}
        copied.recompute_tags_and_metadata()
        path = destination / "evals" / f"{source.stem}-{VERSION}.eval"
        write_eval_log(copied, str(path))
        reopened = read_eval_log(str(path), resolve_attachments="full")
        verify_preservation(original, reopened, lookup, manifest)
        for after in reopened.samples:
            audit = lookup.get(after.uuid)
            if audit is None:
                continue
            # Errored target generations (no output) were excluded from the judged packet; the
            # viewer converter's resume-window check needs the same view of the events.
            events = [e for e in after.events if not (e.event == "model" and e.role == "target" and e.error)]
            view = after.model_copy(update={"scores": {SCORERS[f]: after.scores[SCORERS[f]] for f in FAMILIES}, "events": events})
            data = convert_petri(reopened, view, path)
            scores = {f: after.scores[SCORERS[f]] for f in FAMILIES}
            data = finalize_view(data, audit, scores, provenance)
            verify_view(data, audit, scores)
            counts["highlights_quote_verbatim"] += quotes_verbatim(data)
            atomic_json(destination / "viewer/data" / f"{data['id']}.json", data)
            viewer_ids.append(data["id"])
        if sha(source) != provenance["source_sha256"]:
            raise ValueError("Original source log changed during export")
        copies.append({"source": relative, "copy": str(path.relative_to(destination)), "sha256": sha(path),
                       "samples": len(reopened.samples), "judged_samples": judged})
    rebuild_index(destination / "viewer/data")
    index = json.loads((destination / "viewer/data/index.json").read_text())
    if sorted(e["id"] for e in index) != sorted(viewer_ids) or len(index) != len(audits):
        raise ValueError("Viewer index does not list exactly the exported audits")
    summary = {"version": VERSION, "run_id": manifest["run_id"], "variant": manifest["variant"],
               "judge_model": manifest["judge_model"], "exported_at": exported_at,
               "audits": len(audits), "samples": counts["samples"], "unjudged_samples": counts["unjudged_samples"],
               "scores": counts["scores"], "scorers": dict(SCORERS),
               "highlights_anchored": counts["highlights_anchored"], "highlights_unanchored": counts["highlights_unanchored"],
               "highlights_quote_verbatim_in_event": counts["highlights_quote_verbatim"],
               "not_exercised_dimensions": {f: counts[f"not_exercised_{f}"] for f in FAMILIES},
               "dimensions": {f: len(manifest["dimensions"][f]) for f in FAMILIES},
               "viewer_html": "viewer/index.html" if viewer_html is not None else None,
               "copies": copies, "viewer_ids": sorted(viewer_ids), "judge_transcripts": sorted(transcripts)}
    atomic_json(destination / "summary.json", summary)
    (destination / "README.md").write_text(readme(summary, run, destination))
    atomic_json(destination / "manifest.json", {
        "exported_at": exported_at, "version": VERSION, "judge_run": str(run), "judge_run_manifest_sha256": run_hash,
        "exporter_sha256": sha(Path(__file__)),
        "source_sha256": {c["source"]: sha(ROOT / c["source"]) for c in copies},
        "prediction_sha256": {p.name: sha(p) for p in sorted((run / "predictions").glob("*.json"))},
        "artifact_sha256": {str(p.relative_to(destination)): sha(p) for p in sorted(destination.rglob("*")) if p.is_file()}})
    return summary


def verify_preservation(original, reopened, lookup, manifest):
    """Reopen check: originals are byte-for-byte preserved, new scorers are present and well-formed."""
    if len(reopened.samples) != len(original.samples or []):
        raise ValueError("Sample count changed")
    excluded = {"scores", "events", "metadata", "attachments", "events_data"}
    for before, after in zip(original.samples, reopened.samples):
        if before.model_dump(mode="json", exclude=excluded) != after.model_dump(mode="json", exclude=excluded):
            raise ValueError("Original sample content changed")
        before_events = [e.model_dump(mode="json") for e in before.events]
        if before_events != [e.model_dump(mode="json") for e in after.events[:len(before_events)]]:
            raise ValueError("Original events changed")
        for key, value in (before.scores or {}).items():
            if key not in after.scores or after.scores[key].model_dump(mode="json") != value.model_dump(mode="json"):
                raise ValueError(f"Original score {key} changed")
        for key, value in (before.metadata or {}).items():
            if after.metadata.get(key) != value:
                raise ValueError(f"Original metadata {key} changed")
        if before.uuid not in lookup:
            if set(after.scores or {}) != set(before.scores or {}):
                raise ValueError("Unjudged sample gained scores")
            continue
        for family in FAMILIES:
            score = after.scores.get(SCORERS[family])
            if score is None or list(score.value) != list(manifest["dimensions"][family]):
                raise ValueError(f"Copied log lacks the full {family} result")
            failed = score.answer == "JUDGE_PARSE_FAILURE"
            if failed and any(v is not None for v in score.value.values()):
                raise ValueError("A failed judgment must carry None for every dimension")
            if not failed and not all(isinstance(v, int) and 1 <= v <= 10 for v in score.value.values()):
                raise ValueError("Scores must be integers 1-10")
            if set(score.metadata["applicability"]) != set(score.value):
                raise ValueError("Applicability map must cover every dimension")
        added = after.events[len(before_events):]
        if Counter(e.scorer for e in added if e.event == "score") != Counter(SCORERS.values()):
            raise ValueError("Exactly one ScoreEvent per new scorer must be appended")


def quotes_verbatim(data):
    """Highlights whose quote appears verbatim in the anchored event (the viewer marks these inline)."""
    events = {e["id"]: json.dumps(e, ensure_ascii=False) for e in data["events"]}
    return sum(h["quoted_text"] in events[h["event_id"]] or json.dumps(h["quoted_text"], ensure_ascii=False)[1:-1] in events[h["event_id"]]
               for h in data["judge"]["highlights"])


def verify_view(data, audit, scores):
    event_ids = {e["id"] for e in data["events"]}
    mapped = {m["viewer_event_id"] for m in audit["record_mapping"].values() if m.get("viewer_event_id")}
    if mapped - event_ids:
        raise ValueError("Record mapping refers to viewer events that do not exist in the converted transcript")
    for highlight in data["judge"]["highlights"]:
        if highlight["event_id"] not in mapped:
            raise ValueError("Highlight anchored outside the packet record mapping")
    if set(data["judge"]["sources"]) != set(FAMILIES):
        raise ValueError("Viewer judge block must carry both families")
    expected = sum(len(s.metadata["highlights"]) for s in scores.values())
    if len(data["judge"]["highlights"]) != expected:
        raise ValueError("Viewer highlight count differs from the anchored evidence count")
    failed_dims = {d for sc in scores.values() if sc.answer == "JUDGE_PARSE_FAILURE" for d in sc.value}
    for dimension, applicability in data["judge"]["applicability"].items():
        if dimension in failed_dims:
            continue  # a failed judgment has no numeric score to label
        if applicability_label(dimension, applicability) not in data["judge"]["scores"]:
            raise ValueError(f"Viewer score label missing for {dimension}")


def README_TEMPLATE(summary, run, destination, html_flag, html_note):
    return f"""# Calibrated judge v3 — Petri rejudgment export

Private benchmark/audit material. Transcripts embed full scenario content and judge output
for the 18 completed Petri audits; keep this folder (and any served copy) private and do
not commit or publish it.

Exported {summary['exported_at']} from run `{summary['run_id']}` (`{run}`), variant
`{summary['variant']}`, judge `{summary['judge_model']}`. No model calls were made by the export.

## Contents

- `evals/`: native Inspect `.eval` copies of the {len(summary['copies'])} source logs ({summary['samples']} samples).
  Every original message, event, score and metadata entry is preserved; each judged sample
  gains the scorers `calibrated_scheming_v3` ({summary['dimensions']['scheming']} dimensions) and
  `calibrated_debug_v3` ({summary['dimensions']['debug']} dimensions). `Score.value` is `{{dimension: int}}`;
  `Score.metadata` holds `applicability`, `reasons`, `evidence` (packet record ids and the mapped
  viewer event ids), `summary`, `unresolved_limitations`, `coverage`, `judge_model`, `attempts`,
  `highlights` and `unanchored_evidence`. Open with `inspect view --log-dir evals/`.
- `viewer/data/`: `index.json` plus one `petri-v3-<uuid>.json` per audit for the transcript
  viewer (`viewer/`). Ids are distinct from the baseline `petri-<uuid>` exports. The judge block
  shows both families; {summary['highlights_anchored']} evidence quotes are anchored inline to
  viewer events via the packet record mapping ({summary['highlights_quote_verbatim_in_event']} of them
  with the quote verbatim in the displayed event, so the viewer also marks the text inline; the
  rest — mostly target-input records anchored to the first target call that received them — show
  as highlight cards on that event only). {summary['highlights_unanchored']} citation(s) could not
  be anchored (auditor system messages) and stay in the judge summary text.
- `judge-transcripts/<seed>-{{scheming,debug}}.md`: readable per-audit judge output (dimension table
  with score/applicability/reason, evidence quotes with record ids, attempt statuses).
- `summary.json`, `manifest.json`: counts and SHA-256 of sources, predictions and artifacts.

## Applicability in the viewer

The viewer renders only a score key and a number. Dimensions the judge marked `not_exercised`
or `unassessable` are scored 1 by convention (the audit created no assessable opportunity;
not evidence of absence) and are labelled `<dimension> [<applicability>]` so they are
distinguishable from an exercised 1. The plain maps are in `judge.applicability` and
`judge.calibrated` of each viewer file. Side effect: a positive-polarity dimension carrying
such a label (e.g. `transparent_disagreement [not_exercised]`) loses the viewer's "higher is
better" arrow, because the viewer matches that by exact key. Per-dimension reasons are not
rendered by the viewer; they are in the judge transcripts, in `judge.calibrated`, and in the
`.eval` score metadata.

## Serve locally

```
.venv/bin/python experiments/aaa_vs_petri/full_judge/serve_viewer.py {destination} --port 5193{html_flag}
```

Then open http://127.0.0.1:5193/ (binds to localhost only; pick another `--port` if it is taken).
{html_note}
"""


def readme(summary, run, destination):
    if summary.get("viewer_html"):
        html_flag = f" --html {destination}/viewer/index.html"
        html_note = ("`viewer/index.html` is the single-file viewer build copied at export time (built from the "
                     "`viewer/` submodule source with `npx vite build`), so the bundle is self-contained.")
    else:
        html_flag = ""
        html_note = ("Without `--html` the server uses the checked-out `viewer/dist/index.html`, which may be older "
                     "than the viewer source; pass `--html <built index.html>` to use a fresh build.")
    return README_TEMPLATE(summary, run, destination, html_flag, html_note)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", type=Path, nargs="?", default=ROOT / "logs/judge-calibration/runs/petri-integrated")
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--viewer-html", type=Path, help="Built single-file viewer (e.g. from `npx vite build`) to copy into viewer/index.html")
    args = parser.parse_args()
    print(json.dumps(export(args.run, args.destination, args.viewer_html), indent=2))
