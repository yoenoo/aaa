"""Offline attribution tests for native Petri viewer conversion."""

from types import SimpleNamespace as NS
import unittest

from inspect_ai.model import ChatMessageAssistant, ChatMessageTool
from inspect_ai.tool import ToolCall

from export_viewer import delivered_results, identity_flags, response_events


class AttributionTests(unittest.TestCase):
    def test_model_identity_screen_is_not_a_keyword_scan(self):
        model = "google/gemini-3.1-pro-preview"
        self.assertEqual(identity_flags(model, ["You are Codex, a coding assistant."]),
                         ["Gemini target assigned Codex identity"])
        self.assertEqual(identity_flags(model, ["You are Atlas. Review the Claude 5 launch."]), [])

    def test_result_requires_exact_target_message_and_call_id(self):
        message = ChatMessageAssistant(id="target-A", content="", tool_calls=[
            ToolCall(id="call-A", function="shell", arguments={"command": "pwd"})])
        current = NS(timestamp=1, output=NS(message=message))
        wrong = NS(timestamp=2, input=[
            message.model_copy(update={"id": "sibling-B"}),
            ChatMessageTool(tool_call_id="call-A", content="wrong branch")])
        right = NS(timestamp=3, input=[message,
            ChatMessageTool(tool_call_id="different-call", content="wrong call"),
            ChatMessageTool(tool_call_id="call-A", content="observed simulated result")])
        self.assertEqual(delivered_results(current, [wrong]), {})
        self.assertEqual(delivered_results(current, [wrong, right]),
                         {"call-A": "observed simulated result"})

    def test_no_future_input_does_not_imply_tool_execution(self):
        current = NS(timestamp=1, output=NS(message=ChatMessageAssistant(
            id="A", content="", tool_calls=[ToolCall(id="C", function="bash", arguments={})])))
        self.assertEqual(delivered_results(current, []), {})

    def test_rollback_replayed_ancestor_cannot_supply_original_branch_result(self):
        message = ChatMessageAssistant(id="ancestor", content="", tool_calls=[
            ToolCall(id="shared-call", function="shell", arguments={})])
        current = NS(timestamp=1, output=NS(message=message))
        sibling = NS(timestamp=4, input=[message, ChatMessageTool(
            tool_call_id="shared-call", content="alternate branch result")])
        self.assertEqual(delivered_results(current, [sibling], cutoff=3), {})

    def test_rejected_resume_is_not_a_target_turn(self):
        target = NS(event="model", role="target", timestamp=2, completed=3, uuid="T")
        good = NS(event="tool", function="resume", timestamp=1, completed=4,
                  id="R", result="<target_response>actual output</target_response>")
        rejected = NS(event="tool", function="resume", timestamp=5, completed=6,
                      id="rejected", result="")
        sample = NS(id="seed", events=[good, target, rejected])
        mapped, targets = response_events(sample)
        self.assertEqual(mapped, {"R": target})
        self.assertEqual(targets, [target])

    def test_ambiguous_window_is_rejected(self):
        targets = [NS(event="model", role="target", timestamp=2, completed=3, uuid=x)
                   for x in ("A", "B")]
        resume = NS(event="tool", function="resume", timestamp=1, completed=4,
                    id="R", result="<target_response>ambiguous</target_response>")
        with self.assertRaises(ValueError):
            response_events(NS(id="seed", events=[resume, *targets]))


if __name__ == "__main__":
    unittest.main()
