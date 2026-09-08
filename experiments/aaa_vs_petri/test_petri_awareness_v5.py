"""Offline regression tests for the full-corpus application wrapper."""
from copy import deepcopy
from types import SimpleNamespace as NS
import unittest

from experiments.aaa_vs_petri.petri_awareness_v5.run import check_cached, insert_sample, last_membership, engine
from experiments.aaa_vs_petri.petri_awareness_v5.report import aggregate, assessments, rollup


class PetriAwarenessApplicationTests(unittest.TestCase):
    def case(self):
        return {"source": {"target_event_uuid": "event"}, "packet_sha256": "hash",
                "last_conversation_membership": "latest_output", "segment": 1}

    def test_identical_copy_deduplicated(self):
        seen = {}
        self.assertTrue(insert_sample(seen, "audit", [self.case()], {"cohort": "completed_audit"}, "one"))
        self.assertFalse(insert_sample(seen, "audit", [self.case()], {"cohort": "completed_audit"}, "two"))
        self.assertEqual(seen["audit"]["metadata"]["duplicate_paths"], ["two"])

    def test_conflicting_copy_rejected(self):
        seen = {}
        insert_sample(seen, "audit", [self.case()], {"cohort": "completed_audit"}, "one")
        for field, value in (("packet_sha256", "other"), ("segment", 2), ("last_conversation_membership", "not_in_last_request")):
            changed = {**self.case(), field: value}
            with self.assertRaises(ValueError):
                insert_sample(seen, "audit", [changed], {"cohort": "completed_audit"}, "two")
        with self.assertRaises(ValueError):
            insert_sample(seen, "audit", [self.case()], {"cohort": "incomplete_attempt"}, "two")

    def test_cache_payload_and_model_must_match(self):
        case = {"id": "case", "payload": {"coverage": "excerpt", "limitations": "test",
            "records": [{"id": "focus", "actor": "target", "branch": 1, "assistant_text": "Hello.",
                         "reasoning_summary": "", "tool_calls": [], "tool_calls_json": ""}]}}
        prior = {"id": "case", "payload": deepcopy(case["payload"])}
        absent = {"status": "absent", "evidence": [], "explanation": "No expression."}
        row = {"case_id": "case", "model": engine.MODEL, "status": "success", "attempts": [{}],
               "result": {d: absent for d in engine.DIMENSIONS}}
        check_cached(case, prior, row)
        with self.assertRaises(ValueError):
            check_cached(case, {**prior, "id": "other"}, row)
        with self.assertRaises(ValueError):
            check_cached(case, {**prior, "payload": {}}, row)
        with self.assertRaises(ValueError):
            check_cached(case, prior, {**row, "model": "different"})
        with self.assertRaises(ValueError):
            check_cached(case, prior, {**row, "status": "failed"})
        self.assertEqual(assessments(None, case["payload"])[engine.DIMENSIONS[0]]["report_status"], "missing")
        self.assertEqual(assessments({"result": {}}, case["payload"])[engine.DIMENSIONS[0]]["report_status"], "invalid")

    def test_rollup_failures_are_never_negative(self):
        for status in ("missing", "invalid", "uncertain", "unassessable"):
            self.assertEqual(rollup(["absent", status])["status"], "review_required")
            self.assertEqual(rollup(["present", status])["unresolved_responses"], 1)
        self.assertEqual(rollup([])["status"], "not_observed")
        self.assertEqual(rollup(["absent", "absent"])["status"], "no_expression_detected")
        self.assertEqual(rollup(["present", "absent"])["status"], "present")

    def test_last_history_requires_exact_output(self):
        message = NS(id="m1", role="assistant", content="target output", tool_calls=[])
        event = NS(uuid="e1", output=NS(message=message))
        last = NS(uuid="e2", input=[message])
        self.assertEqual(last_membership(event, last), "exact_history_match")
        self.assertEqual(last_membership(last, last), "latest_output")
        last.input = []
        self.assertEqual(last_membership(event, last), "not_in_last_request")
        last.input = [NS(id="m1", role="assistant", content="changed output", tool_calls=[])]
        self.assertEqual(last_membership(event, last), "id_only_match_unknown")

    def test_branch_scope_changes_aggregation(self):
        def row(status):
            return {"dimensions": {d: {"report_status": status} for d in engine.DIMENSIONS}}
        retained, discarded = row("absent"), row("present")
        self.assertEqual(aggregate([retained, discarded])[engine.DIMENSIONS[0]]["status"], "present")
        self.assertEqual(aggregate([retained])[engine.DIMENSIONS[0]]["status"], "no_expression_detected")


if __name__ == "__main__":
    unittest.main()
