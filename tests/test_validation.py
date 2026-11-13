"""T04–T08: saved mock replies must pass completion, schema and evidence gates.

This specifies an internal mock envelope, not a provider's native protocol:
completed + exactly one extraction object or JSON output_text, with optional
refusal/incomplete details. Step 8 will translate the real provider protocol.
Schema-only cases deliberately isolate schema rules from source semantics.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import unittest
from unittest import mock

from access_intake.exports import read_export
from access_intake.providers import MockProvider


ROOT = Path(__file__).resolve().parents[1]
MOCKS = ROOT / "tests" / "mock_responses"
SCALARS = {
    "request_id", "request_date", "kind", "requester", "team", "system",
    "environment", "permission", "business_purpose", "start_date", "end_date", "manager",
}


def saved(name):
    return json.loads((MOCKS / f"{name}.json").read_text(encoding="utf-8"))


class ReplyValidationContract(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for attribute in ("socket", "create_connection"):
            stack.enter_context(mock.patch.object(
                socket, attribute, side_effect=AssertionError("T04–T08 must stay offline")
            ))
        original_getitem = os._Environ.__getitem__

        def forbid_key(environ, key):
            if key == "API_KEY":
                raise AssertionError("T04–T08 must not read API_KEY")
            return original_getitem(environ, key)

        stack.enter_context(mock.patch.object(os._Environ, "__getitem__", forbid_key))
        self.document = read_export(ROOT / "materials" / "requests" / "IT-001.json")

    def run_reply(self, name, document=None):
        from access_intake.extraction import extract_document

        provider = MockProvider(MOCKS, schedule=[name])
        result = extract_document(document or self.document, provider, attempt_id="test-attempt-003")
        self.assertEqual(provider.call_count, 1)
        return result

    def assert_error(self, result, category, document=None):
        document = document or self.document
        self.assertEqual(result["document_id"], document.document_id)
        self.assertEqual(result["source_sha256"], document.source_hash)
        self.assertEqual(result["attempt_id"], "test-attempt-003")
        self.assertEqual(result["response_source"], "mock")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["owner"], "IT Service Desk")
        self.assertEqual(result["next_action"], "retry-extraction")
        self.assertIsNone(result["extraction"])
        error = result["error"]
        self.assertEqual(error["category"], category)
        self.assertEqual(error["document_id"], document.document_id)
        self.assertEqual(error["attempt_id"], "test-attempt-003")
        self.assertIsInstance(error["explanation"], str)
        self.assertTrue(error["explanation"].strip())
        self.assertEqual(error["retry_command"],
                         f"python3 -m access_intake retry {document.document_id}")

    def test_t04_all_schema_properties_types_enums_and_extras(self):
        from access_intake.validation import ValidationError, validate_schema

        cases = saved("schema-matrix")["cases"]
        # Check matrix coverage against the specified fourteen-property contract.
        self.assertEqual({c["field"] for c in cases if c["name"].startswith("missing ")},
                         SCALARS | {"supporting_quotes", "issues"})
        self.assertEqual({c["field"] for c in cases if "wrong integer" in c["name"]}, SCALARS)
        for case in cases:
            with self.subTest(case=case["name"]):
                if case["valid"]:
                    validate_schema(case["extraction"])
                else:
                    with self.assertRaises(ValidationError) as caught:
                        validate_schema(case["extraction"])
                    self.assertEqual(caught.exception.category, "schema")

    def test_t04_valid_b1_reply_can_proceed_without_a_business_route_assertion(self):
        result = self.run_reply("schema-valid")
        self.assertIsNone(result["error"])
        self.assertEqual(result["response_source"], "mock")
        self.assertEqual(result["extraction"]["request_id"], "IT-001")
        self.assertEqual(result["extraction"]["requester"], "Maya Chen")
        self.assertEqual(result["extraction"]["permission"], "read")
        self.assertEqual(result["extraction"]["start_date"], "2026-10-23")
        self.assertEqual(result["extraction"]["end_date"], "2026-11-06")
        self.assertEqual(result["extraction"]["issues"], [])

    def test_t04_schema_failure_is_an_actionable_extraction_error(self):
        self.assert_error(self.run_reply("malformed-schema-001"), "schema")

    def test_t05_exact_evidence_rejects_invented_normalized_and_altered_quotes(self):
        self.assertIsNone(self.run_reply("evidence-valid")["error"])
        for name in ("evidence-invented", "evidence-normalized", "evidence-whitespace"):
            with self.subTest(reply=name):
                self.assert_error(self.run_reply(name), "evidence")

    def test_t05_quotes_compare_with_decoded_newlines(self):
        document = read_export(ROOT / "tests" / "fixtures" / "exports" / "IT-001-newline.json")
        result = self.run_reply("evidence-newline-valid", document)
        self.assertIsNone(result["error"])
        self.assertIn("My manager is Priya Shah.\nDashboard notes follow.",
                      result["extraction"]["supporting_quotes"])
        self.assert_error(self.run_reply("evidence-newline-escaped", document), "evidence", document)

    def test_t05_conflicting_alternatives_need_both_quotes_and_explanation(self):
        document = read_export(ROOT / "materials" / "requests" / "IT-004.json")
        result = self.run_reply("conflict-valid-004", document)
        self.assertIsNone(result["error"])
        self.assertIsNone(result["extraction"]["environment"])
        for name, category in (
            ("conflict-missing-evidence", "evidence"),
            ("conflict-missing-staging", "evidence"),
            ("conflict-missing-issue", "semantic"),
            ("conflict-selected-alternative", "semantic"),
        ):
            with self.subTest(reply=name):
                self.assert_error(self.run_reply(name, document), category, document)

    def test_t05_every_null_scalar_needs_a_relevant_explanation(self):
        from access_intake.validation import ValidationError, validate_extraction

        cases = saved("missing-explanation-matrix")["cases"]
        self.assertEqual({c["field"] for c in cases}, SCALARS)
        for case in cases:
            with self.subTest(case=case["name"]):
                extraction = case["reply"]["extraction"]
                if case["valid"]:
                    validate_extraction(self.document, extraction)
                else:
                    with self.assertRaises(ValidationError) as caught:
                        validate_extraction(self.document, extraction)
                    self.assertEqual(caught.exception.category, "semantic")
        # Human-readable, grouped wording is allowed; issue prose is not an enum.
        self.assertIsNone(self.run_reply("missing-dates-grouped")["error"])

    def test_t05_resolved_dates_use_the_required_representation(self):
        from access_intake.validation import ValidationError, validate_extraction

        for case in saved("date-format-matrix")["cases"]:
            with self.subTest(field=case["field"], value=case["reply"]["extraction"][case["field"]]):
                with self.assertRaises(ValidationError) as caught:
                    validate_extraction(self.document, case["reply"]["extraction"])
                self.assertEqual(caught.exception.category, "semantic")

    def test_t05_override_evidence_and_issue_cannot_be_discarded(self):
        document = read_export(ROOT / "materials" / "requests" / "IT-006.json")
        # Q-16 permission remains unresolved: these cases assert only omissions.
        for name, category in (("override-missing-evidence", "evidence"),
                               ("override-missing-issue", "semantic")):
            with self.subTest(reply=name):
                self.assert_error(self.run_reply(name, document), category, document)

    def test_t06_malformed_replies_have_distinct_diagnostics(self):
        for name, category in (
            ("malformed-json-001", "malformed_json"),
            ("malformed-envelope-list", "malformed_envelope"),
            ("malformed-envelope-null", "malformed_envelope"),
            ("malformed-no-status", "malformed_envelope"),
            ("malformed-status", "malformed_envelope"),
            ("malformed-no-extraction", "malformed_envelope"),
            ("malformed-output-text", "malformed_json"),
            ("malformed-extraction-type", "schema"),
            ("malformed-ambiguous-output", "malformed_envelope"),
        ):
            with self.subTest(reply=name):
                self.assert_error(self.run_reply(name), category)

    def test_t06_completed_json_text_is_parsed_then_validated(self):
        result = self.run_reply("complete-output-text")
        self.assertIsNone(result["error"])
        self.assertEqual(result["extraction"]["request_id"], "IT-001")
        self.assertEqual(result["extraction"]["manager"], "Priya Shah")

    def test_t06_timeout_and_provider_exception_are_safe_actionable_errors(self):
        from access_intake.extraction import extract_document

        for failure, category in ((TimeoutError("private provider diagnostic"), "timeout"),
                                  (RuntimeError("private provider diagnostic"), "provider_error")):
            with self.subTest(category=category):
                provider = MockProvider(MOCKS, schedule=[failure])
                result = extract_document(self.document, provider, attempt_id="test-attempt-003")
                self.assert_error(result, category)
                self.assertNotIn("private provider diagnostic", json.dumps(result))
                self.assertEqual(provider.call_count, 1)  # No hidden retry loop.

    def test_t07_refusal_blocks_even_plausible_extraction_before_validation(self):
        from access_intake import validation

        for name in ("refusal-001", "refusal-with-extraction"):
            with self.subTest(reply=name), mock.patch.object(
                validation, "validate_extraction", side_effect=AssertionError("refusal reached extraction validation")
            ) as gate:
                self.assert_error(self.run_reply(name), "refusal")
                gate.assert_not_called()

    def test_t08_incomplete_blocks_truncated_and_complete_text_before_validation(self):
        from access_intake import validation

        for name in ("incomplete-001", "incomplete-with-extraction", "incomplete-with-complete-text"):
            with self.subTest(reply=name), mock.patch.object(
                validation, "validate_extraction", side_effect=AssertionError("incomplete response reached extraction validation")
            ) as gate:
                self.assert_error(self.run_reply(name), "incomplete")
                gate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
