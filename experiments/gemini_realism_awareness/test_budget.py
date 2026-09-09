import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import asyncio
from inspect_ai.util import LimitExceededError
from experiments.gemini_realism_awareness.budget import reserve, settle, committed, reserve_sandbox


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'budget.json'

    def tearDown(self):
        self.tmp.cleanup()

    def test_outstanding_requests_block_overspend(self):
        for _ in range(36): reserve('google/gemini-3.1-pro-preview', 'test', 100, 64, self.path)
        with self.assertRaises(LimitExceededError): reserve('google/gemini-3.1-pro-preview', 'test', 100, 64, self.path)
        self.assertEqual(committed(json.loads(self.path.read_text())), 900)

    def test_settlement_releases_only_unused_reservation(self):
        rid = reserve('google/gemini-3.1-pro-preview', 'test', 100, 64, self.path)
        settle(rid, {'input_tokens': 1000, 'output_tokens': 100}, self.path)
        self.assertAlmostEqual(committed(json.loads(self.path.read_text())), .0058)
        with self.assertRaises(LimitExceededError): settle(rid, {}, self.path)

    def test_invalid_usage_keeps_reservation(self):
        rid = reserve('google/gemini-3.1-pro-preview', 'test', 100, 64, self.path)
        with self.assertRaises(LimitExceededError): settle(rid, {'output_tokens': -1}, self.path)
        self.assertEqual(committed(json.loads(self.path.read_text())), 25)

    def test_unknown_models_and_large_requests_fail_closed(self):
        with self.assertRaises(LimitExceededError): reserve('unknown/model', 'test', 100, 64, self.path)
        with self.assertRaises(LimitExceededError): reserve('google/gemini-3.1-pro-preview', 'test', 3_000_000, 64, self.path)

    def test_infrastructure_cap(self):
        for _ in range(33): reserve_sandbox('test', self.path)
        with self.assertRaises(LimitExceededError): reserve_sandbox('test', self.path)

    def test_limit_exception_propagates_through_real_inspect_hooks(self):
        from inspect_ai.hooks._hooks import emit_before_model_generate
        from inspect_ai.model import GenerateConfig
        error = LimitExceededError('cost', value=900, limit=900)
        with patch.dict('os.environ', {'AAA_EXPERIMENT_BUDGET': '1'}), patch('experiments.gemini_realism_awareness.budget.reserve', side_effect=error):
            with self.assertRaises(LimitExceededError):
                asyncio.run(emit_before_model_generate('google/gemini-3.1-pro-preview', [], [], 'auto', GenerateConfig(), None))


if __name__ == '__main__': unittest.main()
