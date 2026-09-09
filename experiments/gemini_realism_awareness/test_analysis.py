import unittest
from experiments.judge_calibration.aaa_vs_petri_compare import wilson_ci, output_summary
from experiments.gemini_realism_awareness.summarize import summarize_scores


class AnalysisTests(unittest.TestCase):
    def test_no_observed_events_does_not_establish_zero_risk(self):
        lo, hi = wilson_ci([0] * 16)
        self.assertAlmostEqual(lo, 0)
        self.assertGreater(hi, .19)
        self.assertLess(hi, .20)
        self.assertIsNone(wilson_ci([]))

    def test_output_counts_are_reported_as_exposure_not_awareness(self):
        rows = [{'scheming': {}, 'outputs': 10}, {'scheming': {}, 'outputs': 30}]
        self.assertEqual(output_summary(rows, 'scheming'), '40 outputs across 2 audits; mean 20.0, median 20.0')

    def test_invalid_or_unassessable_judgment_is_not_a_negative(self):
        dimension = 'verbalized_eval_awareness'
        def result(parse, applicability):
            return summarize_scores({'scheming_judge_v3': {
                'value': {dimension: 1}, 'metadata': {'parse_status': parse,
                'applicability': {dimension: applicability}}}})['scheming']
        for parse, applicability in [('failed', 'exercised'), ('full', 'unassessable'), ('full', 'not_exercised')]:
            self.assertIsNone(result(parse, applicability)['assessments'][dimension]['score'])
        self.assertEqual(result('full', 'exercised')['assessments'][dimension]['score'], 1)
        self.assertEqual(summarize_scores({})['scheming']['status'], 'missing')


if __name__ == '__main__': unittest.main()
