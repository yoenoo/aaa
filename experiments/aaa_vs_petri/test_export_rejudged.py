"""Offline tests: copies, attribution, categorical scores and judge provenance."""
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from inspect_ai.event import ScoreEvent
from inspect_ai.log import EvalSample
from inspect_ai.model import ChatMessageUser
from inspect_ai.scorer import Score

from experiments.aaa_vs_petri import export_rejudged as exporter


class RejudgedExportTests(unittest.TestCase):
    def row(self, status="absent", simulation="absent"):
        return {"id": "case", "source": {"target_event_uuid": "target", "target_event_index": 0},
            "dimensions": {dimension: {"report_status": value, "valid": True,
                "evidence": [] if value == "absent" else [{"quote": "Is this a test?", "channel": "assistant_text"}],
                "explanation": "Test fixture."}
                for dimension, value in zip(exporter.DIMENSIONS, (status, simulation))}}

    def test_categories_are_not_numeric_scores(self):
        score = exporter.make_score([self.row("present")], {"target": "e3"}, {})
        self.assertEqual(score.value, {exporter.DIMENSIONS[0]: "present",
                                      exporter.DIMENSIONS[1]: "no_expression_detected"})
        self.assertTrue(all(isinstance(v, str) for v in score.value.values()))
        self.assertEqual(score.metadata["highlights"][0]["event_id"], "e3")

    def test_uncertain_rollup_is_not_absent(self):
        score = exporter.make_score([self.row(simulation="uncertain")], {"target": "e3"}, {})
        self.assertEqual(score.value[exporter.DIMENSIONS[1]], "review_required")
        self.assertIn("uncertain", score.answer)

    def test_missing_evidence_anchor_fails(self):
        with self.assertRaises(KeyError):
            exporter.make_score([self.row("present")], {}, {})

    def test_scoring_spans_retired_but_online_filter_preserved(self):
        def span(sid, parent=None, kind="scorer"):
            return NS(event="span_begin", id=sid, span_id=sid, parent_id=parent, type=kind)
        audit = NS(event="model", span_id="solver", role="target")
        online = NS(event="model", span_id="solver", role="realism")
        nested = NS(event="info", span_id="nested")
        old_judge = NS(event="model", span_id="orphan", role="judge")
        old_score = NS(event="score", span_id=None)
        scorer = span("score", "missing-parent")
        child = span("nested", "score", "generate")
        end = NS(event="span_end", id="score", span_id="score")
        kept, retired = exporter.split_judge_events([audit, online, scorer, child, nested, old_judge, old_score, end])
        self.assertEqual(kept, [audit, online])
        self.assertEqual(retired, [scorer, child, nested, old_judge, old_score, end])

    def test_refuses_to_remove_audit_activity_inside_scorer_span(self):
        scorer = NS(event="span_begin", id="s", span_id="s", parent_id=None, type="scorer")
        for event in [NS(event="model", role="target", span_id="s"), NS(event="tool", span_id="s")]:
            with self.assertRaises(ValueError):
                exporter.split_judge_events([scorer, event])

    def test_replacement_does_not_mutate_original(self):
        old = Score(value={"old_dimension": 9}, answer="Old conclusion")
        sample = EvalSample(id="sample", epoch=1, input="original", target="",
            messages=[ChatMessageUser(content="Original request")],
            scores={"old_judge": old}, metadata={"original": True},
            events=[ScoreEvent(score=old, scorer="old_judge")])
        before = sample.model_dump(mode="json")
        with patch.object(exporter, "target_message_ids", return_value={"target": "e0"}):
            copied, archive = exporter.replace_sample(sample, [self.row()], {"exported_at": "now"})
        self.assertEqual(sample.model_dump(mode="json"), before)
        self.assertEqual(copied.messages, sample.messages)
        self.assertEqual(set(copied.scores), {exporter.SCORER})
        self.assertEqual(archive["scores"]["old_judge"]["value"], {"old_dimension": 9})
        self.assertEqual(len(archive["events"]), 1)
        self.assertEqual(copied.events[0].scorer, exporter.SCORER)
        self.assertTrue(copied.events[0].metadata["not_a_new_model_call"])

    def test_existing_destination_rejected_before_reading_run(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(exporter, "verify_report") as verify:
                with self.assertRaises(ValueError):
                    exporter.export(Path("missing"), Path(directory))
                verify.assert_not_called()

    def test_json_write_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            exporter.json_write(path, {"first": True})
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                exporter.json_write(path, {"second": True})
            self.assertEqual(path.read_bytes(), before)

    def test_exchange_preserves_attempts_without_inventing_failed_output(self):
        case = {"id": "case", "source": {}, "judgment_origin": "new_application"}
        prediction = {"model": "model", "attempts": [
            {"number": 1, "status": "interrupted_outcome_unknown"},
            {"number": 2, "status": "valid", "response": '{"returned":"exactly"}'}],
            "result": {}, "dimension_attempt": {"eval_awareness": 2}}
        snapshot = deepcopy(prediction)
        manifest = {k: None for k in ("max_tokens", "timeout_seconds", "cache_prompt", "streaming",
                                    "automatic_inspect_retries", "automatic_sdk_retries")}
        value = exporter.exchange(case, {"unicode": "é"}, prediction, "Exact prompt", manifest)
        self.assertEqual(value["request_messages"][1]["content"], '{"unicode": "é"}')
        self.assertEqual(value["attempts"], snapshot["attempts"])
        self.assertNotIn("response", value["attempts"][0])
        self.assertIn("No completion was recorded", exporter.render_exchange(value))
        self.assertIn("not a native Inspect", value["limitations"])
        self.assertEqual(prediction, snapshot)

    def test_fences_cannot_be_closed_by_transcript_content(self):
        self.assertEqual(exporter.fenced("contains ``` fence"), "````\ncontains ``` fence\n````")


if __name__ == "__main__":
    unittest.main()
