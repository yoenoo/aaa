import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
import unittest.mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.judge_calibration import ledger, runner
from experiments.judge_calibration.variants import load_variant
from experiments.judge_calibration.test_variants import cite, item, packet, valid_response


def benchmark(root):
    bench = root / "bench"
    (bench / "private").mkdir(parents=True)
    rows = [{"id": "s1", "track": "a_pos", "family": "scheming", "subset": ["dev", "full"], "payload": packet(), "group": "g", "pair_id": None, "variant": None},
            {"id": "d1", "track": "c_realism", "family": "debug", "subset": ["dev", "full"], "payload": packet(), "group": "g", "pair_id": None, "variant": None},
            {"id": "s2", "track": "a_pos", "family": "scheming", "subset": ["full"], "payload": packet(), "group": "g", "pair_id": None, "variant": None}]
    (bench / "inputs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (bench / "private" / "references.jsonl").write_text(json.dumps({"case_id": "s1", "family": "scheming", "track": "a_pos", "expectations": [
        {"kind": "score_min", "dimension": "verbalized_eval_awareness", "value": 4}], "provenance": "p", "rationale": "r"}) + "\n")
    (bench / "manifest.json").write_text(json.dumps({"version": "test", "sha256": {"inputs.jsonl": hashlib.sha256((bench / "inputs.jsonl").read_bytes()).hexdigest()}}))
    return bench


class FakeModel:
    """Scripted responses per family; records what the state file and ledger looked like at call time."""

    def __init__(self, scripts, run_dir, ledger_path):
        self.scripts, self.run_dir, self.ledger_path, self.observed = scripts, run_dir, ledger_path, []

    async def generate(self, messages, config=None):
        family = config.response_schema.name
        assert config.max_retries == 0 and config.response_schema.json_schema is not None
        jid = {"scheming": "s1", "debug": "d1"}[family]
        state = json.loads((self.run_dir / "predictions" / f"{jid}.json").read_text())
        entries = json.loads(self.ledger_path.read_text())["entries"]
        self.observed.append({"job": jid, "last_attempt": state["attempts"][-1]["status"],
                              "ledger_seq": state["attempts"][-1]["ledger_seq"], "ledger_entries": len(entries)})
        await asyncio.sleep(0)
        step = self.scripts[family].pop(0)
        if isinstance(step, Exception):
            raise step
        return NS(completion=step if isinstance(step, str) else json.dumps(step), usage=None, stop_reason="stop")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bench = benchmark(self.root)
        self.ledger = self.root / "ledger.json"

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, name="run1", **kw):
        result = runner.prepare(self.root / name, "baseline", self.bench, allocation="smoke", **kw)
        return self.root / name, result

    def execute(self, run_dir, scripts, **kw):
        m = runner.verify(run_dir)
        model = FakeModel(scripts, run_dir, self.ledger)
        return model, asyncio.run(runner.execute(run_dir, m, model, ledger_path=self.ledger, **kw))

    def test_prepare_and_verify(self):
        run_dir, result = self.prepare()
        self.assertEqual((result["jobs"], result["families"], result["paid_calls"]), (2, ["debug", "scheming"], 0))
        m = runner.verify(run_dir)
        self.assertEqual(m["judge_model"], "anthropic/claude-opus-4-8")
        self.assertEqual(m["limits"], {"max_attempts_per_job": 3, "max_tokens": 16000, "timeout": 600, "cache_prompt": "auto", "max_retries": 0, "max_concurrency": 12})
        self.assertEqual(set(m["artifact_sha256"]), {"inputs.jsonl", "schemas.json", "prompts/debug.txt", "prompts/scheming.txt"})
        self.assertTrue(any(k.endswith("baseline/scheming/dimensions.yaml") for k in m["variant_sha256"]))
        self.assertIn("experiments/judge_calibration/runner.py", m["code_sha256"])
        self.assertEqual(len(m["dimensions"]["scheming"]), 34)
        self.assertFalse(any("references" in line for line in (run_dir / "inputs.jsonl").read_text().splitlines()))
        self.assertNotIn("private", [p.name for p in run_dir.iterdir()])
        schemas = json.loads((run_dir / "schemas.json").read_text())
        self.assertEqual(schemas["debug"]["provider_projection"]["properties"]["assessments"]["items"]["properties"]["score"], {"type": "integer"})
        self.assertEqual(schemas["debug"]["wire"]["properties"]["assessments"]["minItems"], 14)
        full, result = self.prepare("full", subset="full")
        self.assertEqual(result["jobs"], 3)
        only, result = self.prepare("tracks", tracks=["c_realism"])
        self.assertEqual(result["families"], ["debug"])
        (run_dir / "prompts" / "debug.txt").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "Frozen run artifact changed"):
            runner.verify(run_dir)
        with self.assertRaises(ValueError):
            runner.prepare(run_dir, "baseline", self.bench)
        (self.bench / "manifest.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "sha256"):
            runner.prepare(self.root / "x", "baseline", self.bench, allocation="smoke")

    def test_reservation_before_await_and_first_valid_wins(self):
        run_dir, _ = self.prepare()
        scheming, debug = load_variant("baseline", "scheming"), load_variant("baseline", "debug")
        bad = valid_response(scheming)
        item(bad, "dishonesty")["score"] = 5
        good = valid_response(scheming)
        item(good, "verbalized_eval_awareness").update(score=5, evidence=[cite("focus", "assistant_text", "Could this be a test")])
        model, progress = self.execute(run_dir, {"scheming": ["not json", bad, good, good], "debug": [valid_response(debug)]})
        self.assertEqual(progress["status_counts"], {"success": 2})
        self.assertEqual(progress["requests_reserved"], 4)
        for seen in model.observed:
            self.assertEqual(seen["last_attempt"], "reserved")
            self.assertEqual(seen["ledger_entries"], seen["ledger_seq"])
        self.assertEqual([o["job"] for o in model.observed], ["d1", "s1", "s1", "s1"])
        state = json.loads((run_dir / "predictions" / "s1.json").read_text())
        self.assertEqual([a["status"] for a in state["attempts"]], ["validation_error", "validation_error", "valid"])
        self.assertIn("dishonesty: score above 1 requires", state["attempts"][1]["error"])
        self.assertEqual(state["result"]["assessments"]["verbalized_eval_awareness"]["score"], 5)
        self.assertEqual(model.scripts["scheming"], [good])
        self.assertEqual(ledger.usage(self.ledger)["smoke"]["used"], 4)
        self.assertEqual(json.loads((run_dir / "progress.json").read_text())["status_counts"], {"success": 2})
        # Re-running touches nothing: every job is terminal.
        model, progress = self.execute(run_dir, {"scheming": [], "debug": []})
        self.assertEqual(model.observed, [])
        self.assertEqual(progress["requests_reserved"], 4)

    def test_exhausted_attempts_fail_and_canary_gate(self):
        run_dir, _ = self.prepare()
        debug = load_variant("baseline", "debug")
        bad = valid_response(debug)
        item(bad, "scenario_realism")["evidence"] = []
        model = FakeModel({"scheming": [], "debug": [bad, bad, bad]}, run_dir, self.ledger)
        with self.assertRaisesRegex(RuntimeError, "Canary gate closed"):
            asyncio.run(runner.execute(run_dir, runner.verify(run_dir), model, ledger_path=self.ledger))
        state = json.loads((run_dir / "predictions" / "d1.json").read_text())
        self.assertEqual(state["status"], "failed")
        self.assertEqual(len(state["attempts"]), 3)
        self.assertFalse((run_dir / "predictions" / "s1.json").exists())

    def test_fatal_provider_error_stops_run(self):
        run_dir, _ = self.prepare()
        error = RuntimeError("invalid_request_error: bad schema")
        error.status_code = 400
        model = FakeModel({"scheming": [], "debug": [error]}, run_dir, self.ledger)
        with self.assertRaisesRegex(RuntimeError, "fatal provider error on d1"):
            asyncio.run(runner.execute(run_dir, runner.verify(run_dir), model, ledger_path=self.ledger))
        state = json.loads((run_dir / "predictions" / "d1.json").read_text())
        self.assertEqual([a["status"] for a in state["attempts"]], ["error"])
        self.assertEqual(state["status"], "pending")
        self.assertEqual(ledger.usage(self.ledger)["smoke"]["used"], 1)

    def test_budget_exhaustion_stops_before_request(self):
        run_dir, _ = self.prepare()
        for _ in range(10):
            ledger.reserve("smoke", "other", path=self.ledger)
        model = FakeModel({"scheming": [], "debug": [valid_response(load_variant("baseline", "debug"))]}, run_dir, self.ledger)
        with self.assertRaisesRegex(RuntimeError, "budget"):
            asyncio.run(runner.execute(run_dir, runner.verify(run_dir), model, ledger_path=self.ledger))
        self.assertEqual(model.observed, [])
        self.assertEqual(json.loads((run_dir / "predictions" / "d1.json").read_text())["attempts"], [])

    def test_request_ceiling_for_this_invocation(self):
        run_dir, _ = self.prepare()
        debug = load_variant("baseline", "debug")
        bad = valid_response(debug)
        item(bad, "scenario_realism")["evidence"] = []
        model = FakeModel({"scheming": [], "debug": [bad, bad, bad]}, run_dir, self.ledger)
        with self.assertRaisesRegex(RuntimeError, "request ceiling: 2"):
            asyncio.run(runner.execute(run_dir, runner.verify(run_dir), model, ledger_path=self.ledger, max_requests=2))
        self.assertEqual(len(model.observed), 2)
        self.assertEqual(ledger.usage(self.ledger)["smoke"]["used"], 2)
        self.assertEqual(json.loads((run_dir / "predictions" / "d1.json").read_text())["status"], "pending")

    def test_canary_only_and_interrupted_recovery(self):
        run_dir, _ = self.prepare()
        model, progress = self.execute(run_dir, {"scheming": [valid_response(load_variant("baseline", "scheming"))],
                                                 "debug": [valid_response(load_variant("baseline", "debug"))]}, canary_only=True)
        self.assertTrue(progress["canary_only"] and progress["canary_ok"])
        self.assertEqual(sorted(progress["canaries"]), ["d1", "s1"])
        path = run_dir / "predictions" / "s1.json"
        state = json.loads(path.read_text())
        state.update(status="pending", attempts=[{"number": 1, "status": "reserved", "ledger_seq": 1}])
        state.pop("result")
        path.write_text(json.dumps(state))
        model, progress = self.execute(run_dir, {"scheming": [valid_response(load_variant("baseline", "scheming"))], "debug": []})
        state = json.loads(path.read_text())
        self.assertEqual([a["status"] for a in state["attempts"]], ["interrupted_outcome_unknown", "valid"])
        self.assertEqual(progress["status_counts"], {"success": 2})

    def test_throttled_request_retries_within_the_same_attempt(self):
        run_dir, _ = self.prepare()
        scheming, debug = load_variant("baseline", "scheming"), load_variant("baseline", "debug")
        rate_limited = RuntimeError("rate limit exceeded"); rate_limited.status_code = 429
        with unittest.mock.patch.object(runner, "BACKOFF_SECONDS", (0, 0)):
            model, progress = self.execute(run_dir, {"scheming": [rate_limited, valid_response(scheming)], "debug": [valid_response(debug)]})
        self.assertEqual(progress["status_counts"], {"success": 2})
        self.assertEqual(progress["requests_reserved"], 2)
        state = json.loads((run_dir / "predictions" / "s1.json").read_text())
        self.assertEqual(len(state["attempts"]), 1)
        self.assertEqual(state["attempts"][0]["throttled"], 1)
        self.assertEqual(state["attempts"][0]["status"], "valid")
        self.assertTrue(runner.throttled(rate_limited) and not runner.throttled(ValueError("bad")))



if __name__ == "__main__":
    unittest.main()


class RepairMessageTests(unittest.TestCase):
    def test_validation_error_adds_feedback_turn_but_request_error_does_not(self):
        from inspect_ai.model import ChatMessageSystem, ChatMessageUser
        from experiments.judge_calibration.runner import repair_messages
        base = [ChatMessageSystem(content="sys"), ChatMessageUser(content="{}")]
        self.assertEqual(len(repair_messages(base, [])), 2)
        self.assertEqual(len(repair_messages(base, [{"status": "error", "error": "boom"}])), 2)
        out = repair_messages(base, [{"status": "validation_error", "error": "dim x: bad quote", "response": "{\"a\":1}"},
                                     {"status": "error", "error": "connection reset"}])  # transient error keeps the feedback
        self.assertEqual(len(out), 4)
        self.assertEqual(out[2].content, "{\"a\":1}")
        self.assertIn("dim x: bad quote", out[3].content)
