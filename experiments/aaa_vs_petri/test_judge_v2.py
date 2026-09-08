"""Offline v2 rubric ownership, parser and controlled benchmark tests."""
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent / "judge_benchmark"))
from prompts import load_judge_spec
from scorer import _parse_judge_response, known_fraction, known_mean
from cases import controlled_cases
from analyze import binary_metrics


class JudgeV2Tests(unittest.TestCase):
    def test_realism_is_owned_by_debug_v2(self):
        behavior = load_judge_spec("scheming_v2")
        debug = load_judge_spec("debug_v2")
        self.assertNotIn("scenario_realism", behavior.dimensions)
        self.assertIn("scenario_realism", debug.dimensions)
        self.assertIn("eval_awareness", behavior.dimensions)
        self.assertIn("environment_artificiality_suspicion", behavior.dimensions)
        self.assertEqual((len(behavior.dimensions), len(debug.dimensions)), (33, 14))
        self.assertEqual(set(behavior.dimensions) & set(debug.dimensions), set())

    def test_v1_is_preserved(self):
        self.assertIn("scenario_realism", load_judge_spec("scheming").dimensions)
        self.assertNotIn("scenario_realism", load_judge_spec("debug").dimensions)
        self.assertEqual(len(load_judge_spec("scheming").dimensions), 33)

    def response(self, scores):
        diagnostics = {"coverage": "insufficient", "awareness": {
            "eval_category": "unknown", "simulation_category": "unknown"}}
        return ("<highlights>None observed.</highlights><summary>Unavailable.</summary>"
                f"<scores>{scores}</scores><justification>Missing context.</justification>"
                f"<diagnostics>{json.dumps(diagnostics)}</diagnostics>")

    def test_unknown_is_not_a_floor_score(self):
        result = _parse_judge_response(self.response("1. eval_awareness: N/A"),
                                      {"eval_awareness"}, ("diagnostics",), strict=True)
        self.assertEqual(result[0], {"eval_awareness": None})

    def test_strict_parser_rejects_defaults_duplicates_range_and_unknown_keys(self):
        for value in ("1. x: 1/10", "1. eval_awareness: 1/10\n2. eval_awareness: 2/10",
                      "1. eval_awareness: 11/10", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _parse_judge_response(self.response(value), {"eval_awareness"}, ("diagnostics",), strict=True)

    def test_grouped_split_and_labels_are_not_payload(self):
        cases = controlled_cases()
        self.assertEqual(len(cases), 24)
        groups = {}
        for case in cases:
            groups.setdefault(case["group"], set()).add(case["split"])
            self.assertNotIn("expected", case["payload"])
            self.assertNotIn("label_rationale", case["payload"])
        self.assertEqual(len(groups), 12)
        self.assertTrue(all(len(splits) == 1 for splits in groups.values()))

    def test_provenance_invariance_has_identical_target_visible_records(self):
        cases = [c for c in controlled_cases() if c["group"] == "execution_provenance_invariance"]
        self.assertEqual(cases[0]["payload"]["records"], cases[1]["payload"]["records"])

    def test_metric_unknown_is_neither_true_negative_nor_false_negative(self):
        result = binary_metrics([(True, True), (False, False), (True, None), (False, None)])
        self.assertEqual((result["tp"], result["tn"], result["fp"], result["fn"]), (1, 1, 0, 0))
        self.assertEqual(result["unknown"], 2)
        self.assertEqual(result["accuracy_known"], 1)
        self.assertEqual(result["correct_over_all"], 0.5)

    def test_no_predictions_do_not_look_like_success(self):
        result = binary_metrics([(True, None), (False, None)])
        self.assertEqual(result["known"], 0)
        self.assertIsNone(result["balanced_accuracy_known"])
        self.assertIsNone(result["accuracy_known"])

    def test_v2_aggregate_metrics_keep_unknown_out_of_the_mean(self):
        rows = [NS(score=NS(value=v)) for v in (2, None, 4)]
        self.assertEqual(known_mean()(rows), 3)
        self.assertAlmostEqual(known_fraction()(rows), 2 / 3)
        unknown = [NS(score=NS(value=None))]
        self.assertTrue(math.isnan(known_mean()(unknown)))
        self.assertEqual(known_fraction()(unknown), 0)


if __name__ == "__main__":
    unittest.main()
