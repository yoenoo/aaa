"""Offline tests inspect the serialized native schema, not just client acceptance."""
from copy import deepcopy
import unittest

from inspect_ai.model import ResponseSchema
from inspect_ai.util._json import JSON_SCHEMA_EXTENDED_FIELDS, json_schema_dump, set_additional_properties_false
from experiments.aaa_vs_petri.judge_v4_transport_repair import inline_schema, available
from experiments.aaa_vs_petri.judge_v4_transport_adapter import object_only_additional_properties
from experiments.aaa_vs_petri.test_judge_v4 import awareness, debug_result
from experiments.aaa_vs_petri.judge_validation_v4.fixtures import packet, debug_cases
from judge_v4 import response_schema
import jsonschema


class TransportTests(unittest.TestCase):
    def test_union_and_scalar_nodes_never_receive_object_only_keywords(self):
        for family in ("awareness_v4", "debug_v4"):
            parsed = ResponseSchema(name=family, json_schema=inline_schema(response_schema(family))).json_schema
            object_only_additional_properties(parsed)
            wire = json_schema_dump(parsed, exclude=JSON_SCHEMA_EXTENDED_FIELDS)
            def walk(schema):
                if schema.get("type") == "object":
                    self.assertIs(schema["additionalProperties"], False)
                    self.assertEqual(set(schema["required"]), set(schema["properties"]))
                else:
                    self.assertNotIn("additionalProperties", schema)
                for v in schema.get("properties", {}).values():
                    walk(v)
                if "items" in schema:
                    walk(schema["items"])
                for v in schema.get("anyOf", []):
                    walk(v)
            walk(wire)
            example = debug_result(debug_cases()[0], positive=True) if family == "debug_v4" else awareness(packet())
            jsonschema.Draft202012Validator(wire).validate(example)

    def test_actual_provider_projection_keeps_nested_types_and_required_channel(self):
        for family in ("awareness_v4", "debug_v4"):
            original = response_schema(family)
            snapshot = deepcopy(original)
            converted = inline_schema(original)
            self.assertEqual(original, snapshot)
            parsed = ResponseSchema(name=family, json_schema=converted).json_schema
            set_additional_properties_false(parsed)
            wire = json_schema_dump(parsed, exclude=JSON_SCHEMA_EXTENDED_FIELDS)
            scores = wire["properties"]["scores"]
            self.assertEqual(scores["type"], "object")
            self.assertEqual(set(scores["required"]), set(scores["properties"]))
            field = "issues" if family == "debug_v4" else "evidence"
            citation = wire["properties"][field]["items"]
            self.assertEqual(citation["type"], "object")
            self.assertIn("channel", citation["required"])
            self.assertEqual(citation["properties"]["channel"]["type"], "string")
            example = debug_result(debug_cases()[0], positive=True) if family == "debug_v4" else awareness(packet())
            for schema in (original, converted, wire):
                jsonschema.Draft202012Validator(schema).validate(example)
            invalid = deepcopy(example)
            invalid.pop("scores")
            for schema in (original, converted, wire):
                self.assertFalse(jsonschema.Draft202012Validator(schema).is_valid(invalid))

    def test_unresolved_reference_is_rejected_not_silently_erased(self):
        with self.assertRaises(ValueError):
            inline_schema({"$ref": "#/$defs/missing"})

    def test_global_budget_and_only_approved_extra_job_attempts(self):
        repair = {"extra_attempt_limits": {"approved.json": 6}, "total_request_ceiling": 444}
        row = {"attempts": [{}, {}, {}]}
        self.assertFalse(available(row, "other.json", repair, 56))
        self.assertTrue(available(row, "approved.json", repair, 443))
        self.assertFalse(available(row, "approved.json", repair, 444))
        row["attempts"] *= 2
        self.assertFalse(available(row, "approved.json", repair, 100))


if __name__ == "__main__":
    unittest.main()
