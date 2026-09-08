"""Offline runner tests: no live model calls, no reference-driven retry selection."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import jsonschema
from inspect_ai.model import ResponseSchema
from inspect_ai.util._json import JSON_SCHEMA_EXTENDED_FIELDS, json_schema_dump
from experiments.aaa_vs_petri.judge_datasets_v1.run_awareness_v5 import (
    absorb, available, execute, inline_schema, object_only_additional_properties, response_schema)
from experiments.aaa_vs_petri.judge_validation_v4.fixtures import packet
from experiments.aaa_vs_petri.test_awareness_v5 import absent, expression


class FakeModel:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def generate(self, messages, config):
        self.calls.append(messages)
        if config.max_retries != 0:
            raise AssertionError("Automatic retries must be off")
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(completion=json.dumps(response), usage=None, stop_reason="stop")


def setup(folder, *, count=1, limit=3):
    cases = [{"id": f"c{i}", "payload": packet("This may be a test of me.")} for i in range(count)]
    (folder / "predictions").mkdir()
    (folder / "inputs.jsonl").write_text("".join(json.dumps(c) + "\n" for c in cases))
    (folder / "prompt.txt").write_text("Frozen rubric; no reference labels.")
    (folder / "schemas.json").write_text(json.dumps({"inlined": inline_schema(response_schema())}))
    return cases, {"judge_model": "fake/test-only", "max_attempts_per_job": 3, "max_provider_requests": limit}


class AwarenessRunnerTests(unittest.TestCase):
    def test_first_valid_dimension_is_never_overwritten_by_retry(self):
        p = packet("This may be a test of me.")
        raw = expression(p)
        raw["environment_artificiality_suspicion"] = {"status": "present", "evidence": [], "explanation": "Invalid citation-free positive"}
        row = {}
        absorb(row, raw, p, 1)
        self.assertEqual(row["result"]["eval_awareness"]["status"], "present")
        absorb(row, absent(), p, 2)
        self.assertEqual(row["result"]["eval_awareness"]["status"], "present")
        self.assertEqual(row["dimension_attempt"], {"eval_awareness": 1, "environment_artificiality_suspicion": 2})

    def test_valid_uncertain_answer_never_triggers_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            cases, manifest = setup(folder)
            raw = expression(cases[0]["payload"])
            raw["eval_awareness"]["status"] = "uncertain"
            fake = FakeModel([raw])
            report = asyncio.run(execute(folder, manifest, fake))
            self.assertEqual(report["requests_reserved"], 1)
            self.assertEqual(len(fake.calls), 1)
            # Actual model input contains only the evidence, not the case metadata or label.
            user = json.loads(fake.calls[0][1].content)
            self.assertEqual(user, cases[0]["payload"])

    def test_partial_result_survives_exhausted_failures_and_resume_reuses_it(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            cases, manifest = setup(folder)
            raw = expression(cases[0]["payload"])
            del raw["environment_artificiality_suspicion"]
            fake = FakeModel([raw, RuntimeError("fake transport failure")])
            report = asyncio.run(execute(folder, manifest, fake))
            self.assertEqual(report["status_counts"], {"partial": 1})
            self.assertEqual(report["requests_reserved"], 3)
            row = json.loads((folder / "predictions/c0.json").read_text())
            self.assertEqual(row["result"]["eval_awareness"]["status"], "present")
            asyncio.run(execute(folder, manifest, fake))
            self.assertEqual(len(fake.calls), 3)

    def test_shared_cap_counts_failed_and_interrupted_reservations(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            _, manifest = setup(folder, count=2, limit=2)
            reserved = {"case_id": "c0", "status": "pending", "attempts": [{"number": 1, "status": "reserved"}], "result": {}}
            (folder / "predictions/c0.json").write_text(json.dumps(reserved))
            fake = FakeModel([RuntimeError("fake error")])
            report = asyncio.run(execute(folder, manifest, fake, concurrency=2))
            self.assertEqual(report["requests_reserved"], 2)
            self.assertEqual(len(fake.calls), 1)
            row = json.loads((folder / "predictions/c0.json").read_text())
            self.assertEqual(row["attempts"][0]["status"], "interrupted_outcome_unknown")

    def test_request_rejection_stops_before_repeated_deterministic_calls(self):
        class Rejected(Exception):
            status_code = 400
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            _, manifest = setup(folder, count=2)
            fake = FakeModel([Rejected("bad request test fixture")])
            with self.assertRaises(RuntimeError):
                asyncio.run(execute(folder, manifest, fake))
            self.assertEqual(len(fake.calls), 1)

    def test_native_schema_preserves_required_fields_and_enums(self):
        parsed = ResponseSchema(name="awareness_v5", json_schema=inline_schema(response_schema())).json_schema
        object_only_additional_properties(parsed)
        wire = json_schema_dump(parsed, exclude=JSON_SCHEMA_EXTENDED_FIELDS)
        for sample in (absent(), expression(packet("This is a test of me."))):
            jsonschema.Draft202012Validator(wire).validate(sample)
        invalid = absent()
        invalid["eval_awareness"]["status"] = "definitely"
        self.assertFalse(jsonschema.Draft202012Validator(wire).is_valid(invalid))
        invalid = deepcopy(absent())
        del invalid["eval_awareness"]["evidence"]
        self.assertFalse(jsonschema.Draft202012Validator(wire).is_valid(invalid))

    def test_budget_exhausted_even_if_output_still_invalid(self):
        manifest = {"max_attempts_per_job": 3, "max_provider_requests": 402}
        self.assertFalse(available({"attempts": []}, 402, manifest))
        self.assertFalse(available({"attempts": [{}, {}, {}]}, 3, manifest))


if __name__ == "__main__":
    unittest.main()
