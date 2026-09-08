"""Offline checks for the Petri-to-AAA scoring adapter."""

import unittest
from unittest.mock import AsyncMock, patch

from inspect_ai.model import ChatMessageAssistant, ChatMessageTool
from inspect_ai.scorer import Score

from aaa_judgments import FORMAT_NOTE, _judge, load_judge_spec, validate_score
from scorer import _format_transcript_xml


class JudgmentValidationTests(unittest.TestCase):
    def result(self, family="scheming"):
        spec = load_judge_spec(family)
        values = {name: 1 for name in spec.dimensions}
        response = "<scores>\n" + "\n".join(
            f"{i}. {name}: 1/10" for i, name in enumerate(values, 1)
        ) + "\n</scores>"
        for tag in ("highlights", "summary", "justification", *spec.extra_blocks):
            response += f"<{tag}>Present</{tag}>"
        return Score(value=values, metadata={"response": response, "parse_status": "full"})

    def test_valid_families(self):
        self.assertEqual(len(load_judge_spec("scheming").dimensions), 33)
        self.assertEqual(len(load_judge_spec("debug").dimensions), 9)
        for family in ("scheming", "debug"):
            validate_score(self.result(family), family)

    def test_missing_scores_cannot_be_silently_defaulted(self):
        result = self.result()
        result.metadata["response"] = result.metadata["response"].replace(
            "1. hidden_goal_evidence: 1/10", "")
        with self.assertRaises(ValueError):
            validate_score(result, "scheming")

    def test_duplicate_out_of_range_and_failed_scores(self):
        for replacement in ("1. hidden_goal_evidence: 11/10",
                            "1. hidden_goal_evidence: 1/10\n2. hidden_goal_evidence: 1/10"):
            result = self.result()
            result.metadata["response"] = result.metadata["response"].replace(
                "1. hidden_goal_evidence: 1/10", replacement)
            with self.assertRaises(ValueError):
                validate_score(result, "scheming")
        result = self.result()
        result.metadata["parse_status"] = "failed"
        with self.assertRaises(ValueError):
            validate_score(result, "scheming")

    def test_missing_required_section(self):
        result = self.result("debug")
        result.metadata["response"] = result.metadata["response"].replace(
            "<infrastructure_issues>Present</infrastructure_issues>", "")
        with self.assertRaises(ValueError):
            validate_score(result, "debug")

    def test_auditor_and_target_are_not_relabelled(self):
        messages = [
            ChatMessageAssistant(content="Auditor assertion"),
            ChatMessageTool(function="resume", content=(
                "<target_response>Target reply</target_response>\n"
                "<target_tool_calls>shell(command='pwd')</target_tool_calls>")),
        ]
        rendered = _format_transcript_xml(messages)
        self.assertIn('<assistant index="1">Auditor assertion', rendered)
        self.assertIn('<tool index="2">&lt;target_response&gt;', rendered)
        self.assertIn("shell(command='pwd')", rendered)
        self.assertIn("NOT target behavior", FORMAT_NOTE)
        self.assertIn("including any rolled", FORMAT_NOTE)


class JudgeAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_aaa_rubric_and_retry_without_network(self):
        factory = JudgmentValidationTests()
        bad = factory.result("debug")
        bad.metadata["parse_status"] = "failed"
        good = factory.result("debug")
        delegate = AsyncMock(side_effect=[bad, good])
        with patch("aaa_judgments._build_judge_scorer", return_value=delegate) as build:
            scorer = _judge("debug", retries=2)
        adapted_spec = build.call_args.args[0]
        original = load_judge_spec("debug")
        self.assertEqual(adapted_spec.dimensions, original.dimensions)
        self.assertEqual(adapted_spec.extra_blocks, original.extra_blocks)
        self.assertEqual(adapted_spec.system_prompt, original.system_prompt + "\n" + FORMAT_NOTE)
        result = await scorer(None, None)
        self.assertEqual(delegate.await_count, 2)
        self.assertTrue(result.metadata["dimensions_unchanged"])

    async def test_persistent_parse_failure_is_not_a_score(self):
        bad = JudgmentValidationTests().result()
        bad.metadata["parse_status"] = "failed"
        with patch("aaa_judgments._build_judge_scorer", return_value=AsyncMock(return_value=bad)):
            scorer = _judge("scheming", retries=2)
        with self.assertRaises(ValueError):
            await scorer(None, None)


if __name__ == "__main__":
    unittest.main()
