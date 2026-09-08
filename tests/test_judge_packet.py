"""Full-audit packet: synthetic AAA sample, and byte-equality with the experiment builder on a Petri log."""
import json
import unittest

from _fixtures import AUDITOR, ROOT, aaa_sample

import judge_packet as jp

AAA_LOG = ROOT / "logs" / "2026-09-04T07-33-36-00-00_petri-task_GD2kFyXNJUdjWnxbJjaPVh.eval"
CORPUS = ROOT / "experiments" / "aaa_vs_petri" / "judge_validation_v4" / "corpus.py"


class SyntheticAaaTests(unittest.TestCase):
    def setUp(self):
        self.messages, self.events = aaa_sample()
        self.packet, self.mapping = jp.build_packet(self.messages, self.events, AUDITOR)

    def test_generations_exclude_preflight_and_follow_turns(self):
        generations, wrappers = jp.target_generations(self.messages, self.events, AUDITOR)
        self.assertEqual([e.uuid for e, _, _ in generations], ["ev-30", "ev-40", "ev-70"])
        self.assertEqual([(anchor, branch) for _, anchor, branch in generations], [("e6", 1), ("e6", 1), ("e11", 2)])
        self.assertEqual(wrappers, {6: ["ev-30", "ev-40"], 11: ["ev-70"]})

    def test_requests_and_dedup(self):
        requests = self.packet["requests"]
        self.assertEqual([r["output_id"] for r in requests], ["target-0001", "target-0002", "target-0003"])
        self.assertEqual([r["branch"] for r in requests], [1, 1, 2])
        # Shared scaffold system prompt + tool definitions are recorded once and referenced twice.
        self.assertEqual(requests[0]["input_ids"][:2], requests[2]["input_ids"][:2])
        by_id = {r["id"]: r for r in self.packet["records"]}
        self.assertEqual(by_id["input-0001"]["actor"], "tool_definitions")
        self.assertEqual(by_id["input-0002"]["actor"], "system")
        self.assertEqual(by_id["target-0002"]["assistant_text"], "Rotated 3 keys. Could this be a test of my behavior?")
        self.assertEqual(self.packet["coverage"], "complete_recorded_audit")
        self.assertEqual(len(self.mapping["input-0001"]["occurrences"]), 3)

    def test_auditor_context_and_wrappers(self):
        by_id = {r["id"]: r for r in self.packet["records"]}
        self.assertEqual(self.packet["auditor_message_ids"], [f"audit-{i + 1:04d}" for i in range(len(self.messages))])
        self.assertEqual(by_id["audit-0007"]["text"], "")
        self.assertEqual(by_id["audit-0007"]["target_output_ids"], ["target-0001", "target-0002"])
        self.assertEqual(by_id["audit-0012"]["target_output_ids"], ["target-0003"])
        self.assertIn('"query_target"', by_id["audit-0005"]["tool_calls_json"])
        self.assertEqual(by_id["audit-0004"]["text"], "README.md")
        self.assertIsNone(self.mapping["audit-0001"]["viewer_event_id"])
        self.assertEqual(self.mapping["audit-0007"]["viewer_event_id"], "e6")
        self.assertEqual(self.mapping["target-0003"], {"viewer_event_id": "e11", "actor": "target", "target_event_uuid": "ev-70",
                                                       "target_event_index": 2, "branch": 2})

    def test_no_generations_raises(self):
        with self.assertRaises(ValueError):
            jp.build_packet(self.messages[:2], self.events[:2], AUDITOR)

    def test_packet_is_json_serializable(self):
        json.dumps(self.packet, ensure_ascii=False)


@unittest.skipUnless(AAA_LOG.exists(), "AAA log not present")
class RecordedAaaTests(unittest.TestCase):
    def test_packet_from_recorded_gemini_cli_audit(self):
        from inspect_ai.log import read_eval_log
        log = read_eval_log(str(AAA_LOG), resolve_attachments="full")
        sample = log.samples[0]
        packet, mapping = jp.sample_packet(sample, str(log.eval.model))
        scaffold_calls = [e for e in sample.events if e.event == "model" and e.role is None
                          and e.model == str(log.eval.model_roles["target"].model)]
        self.assertEqual(len(packet["requests"]), len(scaffold_calls))  # ping (role=target) excluded
        self.assertEqual(sorted({r["branch"] for r in packet["requests"]}), [1, 2])
        wrappers = [r for r in packet["records"] if r.get("target_output_ids")]
        self.assertEqual(len(wrappers), sum(1 for m in sample.messages if m.role == "tool" and m.function == "query_target"))
        self.assertTrue(all(r["text"] == "" for r in wrappers))
        self.assertTrue(all(mapping[r["id"]]["viewer_event_id"].startswith("e") for r in packet["records"] if r["actor"] == "target"))


@unittest.skipUnless(CORPUS.exists(), "experiment corpus not present")
class PetriEqualityTests(unittest.TestCase):
    def test_equals_experiment_build_packet(self):
        from inspect_ai.log import read_eval_log
        from experiments.aaa_vs_petri.full_judge.run import build_packet as experiment_build
        from experiments.aaa_vs_petri.judge_validation_v4.corpus import SOURCES
        source = next((p for p in SOURCES if p.exists()), None)
        if source is None:
            self.skipTest("Petri source log not present")
        log = read_eval_log(str(source), resolve_attachments="full")
        sample = next(s for s in log.samples if not s.error)
        packet, mapping = jp.sample_packet(sample)
        expected_packet, expected_mapping = experiment_build(sample)
        self.assertEqual(packet, expected_packet)
        self.assertEqual(mapping, expected_mapping)


if __name__ == "__main__":
    unittest.main()
