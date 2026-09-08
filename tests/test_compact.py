"""Packet compaction: stages, budgets, markers, validator refusal, and (slow) every real AAA packet."""
from copy import deepcopy
import json
import os
import unittest

from _fixtures import AUDITOR, ROOT, aaa_sample, cite, valid_response

import judge_packet as jp
import structured_judge as sj


def big_packet(env_chars=50_000, tools_chars=60_000, reasoning_chars=30_000, calls_chars=0):
    """Synthetic full-audit packet with oversized environment, tool-definition and reasoning records."""
    messages, events = aaa_sample()
    packet, _ = jp.build_packet(messages, events, AUDITOR)
    for record in packet["records"]:
        if record["actor"] == "tool_definitions":
            record["text"] = "T" * tools_chars
        elif record["actor"] in ("system", "user", "tool"):
            record["text"] = f"{record['actor']}-head " + "e" * env_chars + " tail-end"
        elif record["actor"] == "auditor_context" and record.get("author_role") == "assistant" and calls_chars:
            record["tool_calls_json"] = "c" * calls_chars
        elif record["actor"] == "target":
            record["reasoning_summary"] = "R" * reasoning_chars
    return packet


def truncated(packet):
    return [r for r in packet["records"] if r.get("truncated")]


class CompactTests(unittest.TestCase):
    def test_under_budget_is_untouched(self):
        packet = big_packet()
        out = jp.compact(packet, 10_000_000)
        self.assertEqual(out, packet)
        self.assertNotIn("truncation", out)

    def test_stage_a_tool_definitions_head_only(self):
        packet = big_packet(env_chars=100, reasoning_chars=100)
        size = jp.packet_chars(packet)
        out = jp.compact(packet, size - 30_000)
        self.assertEqual(out["truncation"]["stage"], "tool_definitions")
        self.assertEqual(out["coverage"], "truncated_recorded_audit")
        tools = next(r for r in out["records"] if r["actor"] == "tool_definitions")
        self.assertTrue(tools["text"].startswith("T" * jp.TOOL_DEFINITIONS_CAP + "\n[... 40000 chars omitted ...]"))
        self.assertEqual(tools["omitted_chars"], 40_000)
        self.assertTrue(tools["truncated"])
        self.assertEqual(out["truncation"]["records"], 1)
        self.assertEqual(out["truncation"]["omitted_chars"], 40_000)
        self.assertLessEqual(jp.packet_chars(out), size - 30_000)
        self.assertIn("[... N chars omitted ...]", out["limitations"])
        self.assertEqual(packet["coverage"], "complete_recorded_audit")  # input not mutated

    def test_stage_b_steps_down_and_keeps_head_and_tail(self):
        packet = big_packet(reasoning_chars=100)
        out = jp.compact(packet, 100_000)
        self.assertTrue(out["truncation"]["stage"].startswith("environment_text_"))
        self.assertEqual(out["coverage"], "truncated_recorded_audit")
        self.assertLessEqual(jp.packet_chars(out), 100_000)
        for record in truncated(out):
            if record["actor"] in ("system", "user", "tool"):
                self.assertTrue(record["text"].startswith(f"{record['actor']}-head "))
                self.assertTrue(record["text"].endswith(" tail-end"))
                self.assertRegex(record["text"], r"\n\[\.\.\. \d+ chars omitted \.\.\.\]\n")
        # A tighter budget reaches a lower cap.
        tighter = jp.compact(packet, 40_000)
        self.assertLess(int(tighter["truncation"]["stage"].rsplit("_", 1)[1]), int(out["truncation"]["stage"].rsplit("_", 1)[1]))
        self.assertLessEqual(jp.packet_chars(tighter), 40_000)

    def test_stage_b_covers_auditor_tool_calls_json(self):
        packet = big_packet(env_chars=100, tools_chars=100, reasoning_chars=100, calls_chars=80_000)
        out = jp.compact(packet, jp.packet_chars(packet) - 100_000)
        auditor = [r for r in truncated(out) if r["actor"] == "auditor_context"]
        self.assertTrue(auditor)
        self.assertIn("chars omitted", auditor[0]["tool_calls_json"])

    def test_stage_c_reasoning_only_after_environment_exhausted(self):
        packet = big_packet(env_chars=3_000, tools_chars=100, reasoning_chars=200_000)
        out = jp.compact(packet, 100_000)
        self.assertTrue(out["truncation"]["stage"].startswith("target_reasoning_"))
        self.assertEqual(out["coverage"], "truncated_recorded_audit")
        for record in out["records"]:
            if record["actor"] == "target":
                self.assertIn("chars omitted", record["reasoning_summary"])
        # Environment records were cut to the smallest cap first.
        env = next(r for r in out["records"] if r["actor"] == "user" and r.get("truncated"))
        self.assertLess(len(env["text"]), 1_200)

    def test_target_assistant_text_and_tool_calls_never_touched(self):
        packet = big_packet(env_chars=100, tools_chars=100, reasoning_chars=100)
        for record in packet["records"]:
            if record["actor"] == "target":
                record["assistant_text"] = "A" * 300_000
                record["tool_calls_json"] = "C" * 300_000
        out = jp.compact(packet, 10_000)
        self.assertEqual(out["coverage"], "insufficient")
        self.assertEqual(out["truncation"]["stage"], "insufficient")
        for before, after in zip(packet["records"], out["records"]):
            if before["actor"] == "target":
                self.assertEqual(after["assistant_text"], before["assistant_text"])
                self.assertEqual(after["tool_calls_json"], before["tool_calls_json"])
                self.assertEqual(after["tool_calls"], before["tool_calls"])

    def test_stage_d_prefix_encoding_is_lossless(self):
        packet = big_packet(env_chars=100, tools_chars=100, reasoning_chars=100)
        # Many small requests: the id lists dominate, so only prefix encoding brings it under budget.
        base = packet["requests"][-1]
        ids = list(base["input_ids"])
        for k in range(400):
            ids = ids + [f"input-{(k % 6) + 1:04d}"]
            packet["requests"].append({"id": f"request-{k + 10:04d}", "branch": 2, "input_ids": list(ids),
                                       "output_id": "target-0003", "coverage": "complete_recorded_request"})
        size = jp.packet_chars(packet)
        out = jp.compact(packet, size // 4)
        self.assertEqual(out["truncation"]["stage"], "request_prefixes")
        self.assertEqual(out["coverage"], "truncated_recorded_audit")
        self.assertGreater(out["truncation"]["prefixed_requests"], 390)
        self.assertLessEqual(jp.packet_chars(out), size // 4)
        encoded = [r["input_ids"] for r in out["requests"] if isinstance(r["input_ids"], dict)]
        self.assertEqual(set(encoded[0]), {"prefix", "then"})
        self.assertEqual([r["input_ids"] for r in jp.expand_requests(out)["requests"]],
                         [r["input_ids"] for r in packet["requests"]])
        self.assertEqual(out["truncation"]["final_chars"], jp.packet_chars(out))

    def test_stage_e_floors_then_insufficient(self):
        packet = big_packet(env_chars=3_000, reasoning_chars=3_000)
        for record in packet["records"]:
            if record["actor"] == "auditor_context":
                record["text"] = "x" * 3_000
        out = jp.compact(packet, 30_000)
        self.assertIn(out["truncation"]["stage"], {"floor_512", "floor_256"})
        self.assertEqual(out["coverage"], "truncated_recorded_audit")
        self.assertLessEqual(jp.packet_chars(out), 30_000)
        worst = jp.compact(packet, 1_000)
        self.assertEqual(worst["coverage"], "insufficient")
        self.assertEqual(worst["truncation"]["stage"], "insufficient")
        self.assertGreater(worst["truncation"]["records"], 0)
        for record in worst["records"]:
            if record["actor"] in ("system", "user", "tool"):
                self.assertLess(len(record["text"]), 400)
            if record["actor"] == "target":
                self.assertLess(len(record["reasoning_summary"]), 700)

    def test_validator_rejects_marker_quotes(self):
        packet = jp.compact(big_packet(reasoning_chars=100), 100_000)
        spec = sj.load_spec("debug")
        response = valid_response(spec, packet)
        system = next(r for r in packet["records"] if r["actor"] == "system")
        marker_quote = system["text"][system["text"].index("[..."):system["text"].index("...]") + 4]
        spanning = system["text"][system["text"].index("[...") - 5:system["text"].index("...]") + 8]
        for quote in (marker_quote, spanning):
            item = next(i for i in response["assessments"] if i["dimension"] == "scenario_realism")
            item["evidence"] = [cite(system["id"], "text", quote)]
            with self.assertRaises(ValueError) as ctx:
                sj.validate(deepcopy(response), packet, spec)
            self.assertIn("quote contains an omission marker", str(ctx.exception))
        # A verbatim quote from the kept head still validates.
        item = next(i for i in response["assessments"] if i["dimension"] == "scenario_realism")
        item["evidence"] = [cite(system["id"], "text", "system-head eeee")]
        result = sj.validate(response, packet, spec)
        self.assertEqual(result["assessments"]["scenario_realism"]["score"], 8)

    def test_truncated_coverage_is_valid_output(self):
        packet = jp.compact(big_packet(reasoning_chars=100), 100_000)
        spec = sj.load_spec("scheming")
        response = valid_response(spec, packet)
        response["coverage"] = "truncated_recorded_audit"
        self.assertEqual(sj.validate(response, packet, spec)["coverage"], "truncated_recorded_audit")
        self.assertIn("truncated_recorded_audit", sj.wire_schema(spec)["properties"]["coverage"]["enum"])
        self.assertIn("truncated_recorded_audit", sj.build_prompt(spec))


LOGS = ROOT / "logs"


@unittest.skipUnless(LOGS.is_dir() and any(LOGS.rglob("*petri-task_*.eval")), "AAA logs not present")
class SlowAllAaaLogsCompactionTests(unittest.TestCase):
    """SLOW (reads every petri-task .eval under logs/, several minutes): every completed AAA
    sample's packet must compact under the default 600k-char budget. Set AAA_SKIP_SLOW=1 to skip."""

    @unittest.skipIf(os.environ.get("AAA_SKIP_SLOW"), "AAA_SKIP_SLOW set")
    def test_every_completed_sample_compacts_under_budget(self):
        from inspect_ai.log import read_eval_log
        built, over, insufficient, failures = 0, 0, [], []
        for path in sorted(LOGS.rglob("*petri-task_*.eval")):
            if "judge-v3-smoke" in path.parts:
                continue  # rescored copies of logs already covered
            try:
                if read_eval_log(str(path), header_only=True).status != "success":
                    continue
                log = read_eval_log(str(path), resolve_attachments="full")
            except Exception as error:  # unreadable/foreign log: not this test's concern
                failures.append((path.name, f"read: {error}"))
                continue
            for sample in log.samples or []:
                try:
                    packet, _ = jp.sample_packet(sample, str(log.eval.model))
                except ValueError:
                    continue  # no completed target generations (aborted audits)
                built += 1
                before = jp.packet_chars(packet)
                out = jp.compact(packet)
                after = jp.packet_chars(out)
                if before > jp.DEFAULT_BUDGET_CHARS:
                    over += 1
                    self.assertIn("truncation", out, path.name)
                    self.assertTrue(all(r.get("truncated") is None or r["omitted_chars"] > 0 for r in out["records"]))
                if after > jp.DEFAULT_BUDGET_CHARS:
                    insufficient.append((path.name, before, after))
                for old, new in zip(packet["records"], out["records"]):
                    if old["actor"] == "target":
                        self.assertEqual(new["assistant_text"], old["assistant_text"])
                        self.assertEqual(new["tool_calls_json"], old["tool_calls_json"])
        print(f"\n[slow] packets built={built} over_budget={over} insufficient={len(insufficient)} unreadable={len(failures)}")
        self.assertGreater(built, 0)
        self.assertEqual(insufficient, [], f"packets still over budget after compaction: {insufficient}")


if __name__ == "__main__":
    unittest.main()
