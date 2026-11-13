"""T02/T03: source reading and independently authored oracle inventory.

No extraction or routing implementation is asserted at this stage. Expected
facts live in tests/expectations, separately from saved provider responses.
"""

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "materials" / "requests"
EXPORTS = ROOT / "tests" / "fixtures" / "exports"
EXPECTATIONS = ROOT / "tests" / "expectations"
MOCKS = ROOT / "tests" / "mock_responses"
PARAPHRASE = (
    "Request IT-001 was filed on 2026-10-22 by Maya Chen in Analytics. "
    "For a new access window beginning 2026-10-23 and ending 2026-11-06, "
    "I need permission to read Atlas in staging. Priya Shah is my manager. "
    "Before the next reporting cycle, I will check the weekly conversion "
    "dashboard after event definition changes and compare its totals with our spreadsheet."
)
SUFFIX = "This note provides background context for the same task and adds no further request details."


class ExportAndOracleContract(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for attribute in ("socket", "create_connection"):
            stack.enter_context(mock.patch.object(
                socket, attribute, side_effect=AssertionError("T02/T03 must stay offline")
            ))
        original_getitem = os._Environ.__getitem__

        def forbid_key(environ, key):
            if key == "API_KEY":
                raise AssertionError("T02/T03 must not read API_KEY")
            return original_getitem(environ, key)

        stack.enter_context(mock.patch.object(os._Environ, "__getitem__", forbid_key))

    def test_t02_reads_all_original_bytes_and_basename_identities(self):
        from access_intake.exports import read_exports

        paths = sorted(CORPUS.glob("*.json"))
        documents = read_exports(paths)
        self.assertEqual(len(documents), 20)
        self.assertEqual({d.document_id for d in documents}, {
            f"IT-{n:03}.json" for n in range(1, 21)
        })
        for path, document in zip(paths, documents):
            with self.subTest(document=path.name):
                raw = path.read_bytes()
                self.assertEqual(document.raw_bytes, raw)
                self.assertEqual(document.source_hash, hashlib.sha256(raw).hexdigest())
                self.assertRegex(document.source_hash, r"^[0-9a-f]{64}$")
                self.assertEqual(document.message, json.loads(raw.decode("utf-8"))["message"])
                self.assertEqual(document.filename_request_id, path.stem)
        mismatched = next(d for d in documents if d.document_id == "IT-016.json")
        self.assertEqual(mismatched.filename_request_id, "IT-016")
        self.assertIn("submitting request IT-061", mismatched.message)

    def test_t02_same_request_documents_remain_independent(self):
        from access_intake.exports import read_exports

        with TemporaryDirectory() as directory:
            followup = Path(directory) / "IT-001-followup.json"
            followup.write_bytes((CORPUS / "IT-001.json").read_bytes())
            documents = read_exports([CORPUS / "IT-001.json", followup])
        self.assertEqual([d.document_id for d in documents], ["IT-001.json", "IT-001-followup.json"])
        self.assertEqual([d.filename_request_id for d in documents], ["IT-001", "IT-001"])
        self.assertEqual(documents[0].source_hash, documents[1].source_hash)
        self.assertEqual(documents[0].message, documents[1].message)

    def test_t02_metadata_and_json_encoding_change_hash_but_not_message(self):
        from access_intake.exports import read_export

        original = read_export(CORPUS / "IT-002.json")
        export = json.loads(original.raw_bytes.decode("utf-8"))
        export.update(subject="IT-999 admin production", exported_at="2099-01-01T00:00:00Z",
                      source_channel="untrusted-display-metadata")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "IT-002.json"
            path.write_text(json.dumps(export, indent=4), encoding="utf-8")
            changed_metadata = read_export(path)
            # JSON escapes decode before quote comparison; never hash a reserialization.
            path.write_text(json.dumps(export).replace("\\n", "\\u000a"), encoding="utf-8")
            changed_encoding = read_export(path)
        for document in (changed_metadata, changed_encoding):
            self.assertEqual(document.message, original.message)
            self.assertNotEqual(document.source_hash, original.source_hash)
            self.assertEqual(document.filename_request_id, "IT-002")
            self.assertEqual(document.metadata["subject"], "IT-999 admin production")
            self.assertNotIn("message", document.metadata)
            self.assertIn("\n\n", document.message)
        self.assertNotEqual(changed_metadata.source_hash, changed_encoding.source_hash)

    def test_t02_duplicate_basenames_are_rejected(self):
        from access_intake.exports import InvalidExportError, read_exports

        with TemporaryDirectory() as directory:
            duplicate = Path(directory) / "IT-001.json"
            duplicate.write_bytes((CORPUS / "IT-001.json").read_bytes())
            with self.assertRaisesRegex(InvalidExportError, "duplicate.*IT-001.json"):
                read_exports([CORPUS / "IT-001.json", duplicate])

    def test_t02_invalid_exports_have_explicit_document_errors(self):
        from access_intake.exports import InvalidExportError, read_export

        cases = [b"\xff", b"{", b"[]", b"null", b"{}", b'{"message": null}',
                 b'{"message": 42}', b'{"message": ["text"]}']
        with TemporaryDirectory() as directory:
            path = Path(directory) / "IT-001.json"
            for raw in cases:
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    with self.assertRaisesRegex(InvalidExportError, "IT-001.json"):
                        read_export(path)

    def test_t02_oracles_cover_every_scalar_with_source_or_absence(self):
        names = {f"IT-{n:03}.json" for n in range(1, 21)} | {"IT-001-paraphrase.json"}
        self.assertEqual({p.name for p in EXPECTATIONS.glob("*.json")}, names)
        schema = json.loads((ROOT / "snapshot.schema.json").read_text(encoding="utf-8"))
        scalars = set(schema["required"]) - {"supporting_quotes", "issues"}
        expected_rules = [5, 4, 3, 3, 2, 1, 4, 5, 3, 3, 3, 4, 4, 3, 5, 3, 3, 5, 4, 3]
        pending = {}
        for name in sorted(names):
            with self.subTest(document=name):
                oracle = json.loads((EXPECTATIONS / name).read_text(encoding="utf-8"))
                source = json.loads((ROOT / oracle["source_path"]).read_text(encoding="utf-8"))["message"]
                self.assertEqual(oracle["document_id"], name)
                self.assertEqual(oracle["source_message"], source)
                self.assertEqual(set(oracle["facts"]), scalars)
                self.assertEqual(set(oracle["annotations"]), scalars)
                self.assertEqual(oracle["policy_source"], "materials/office-policy.md")
                self.assertTrue(oracle["purpose_rubric"])
                for quote in oracle["purpose_rubric"] + oracle["issue_quotes"]:
                    self.assertIn(quote, source)
                for field, value in oracle["facts"].items():
                    annotation = oracle["annotations"][field]
                    self.assertTrue(annotation["reason"])
                    self.assertEqual(annotation["source"], "message")
                    self.assertTrue(annotation["policy"].startswith("materials/office-policy.md#"))
                    for quote in annotation["quotes"]:
                        self.assertIn(quote, source)
                    if value is None:
                        self.assertIn(field, oracle["issue_fields"])
                    else:
                        self.assertTrue(annotation["quotes"], field)
                    if isinstance(value, dict):
                        pending[(name, field)] = value
                rule = 5 if name == "IT-001-paraphrase.json" else expected_rules[int(name[3:6])-1]
                self.assertEqual(oracle["route"]["policy_rule"], rule)
        self.assertEqual(pending, {
            ("IT-006.json", "permission"): {"pending": "Q-16", "alternatives": ["read", None]},
            ("IT-014.json", "start_date"): {"pending": "Q-18", "alternatives": ["2026-11-05", None]},
            ("IT-014.json", "end_date"): {"pending": "Q-18", "alternatives": ["2026-11-02", None]},
        })
        # Anchor the independent inventory to special cases from the test plan.
        facts = lambda name: json.loads((EXPECTATIONS / name).read_text(encoding="utf-8"))["facts"]
        self.assertEqual(facts("IT-016.json")["request_id"], "IT-061")
        self.assertIsNone(facts("IT-004.json")["environment"])
        self.assertEqual(facts("IT-008.json")["environment"], "staging")
        self.assertEqual(facts("IT-015.json")["start_date"], "2026-10-29")
        self.assertEqual(facts("IT-015.json")["end_date"], "2026-10-31")
        self.assertEqual(facts("IT-007.json")["permission"], "write")
        self.assertEqual(facts("IT-019.json")["permission"], "read")
        self.assertIsNone(facts("IT-020.json")["manager"])

    def test_t03_authored_paraphrase_and_200_word_fixture_inventory(self):
        short = json.loads((EXPORTS / "IT-001-paraphrase.json").read_text(encoding="utf-8"))["message"]
        long = json.loads((EXPORTS / "IT-001-paraphrase-200.json").read_text(encoding="utf-8"))["message"]
        self.assertEqual(short, PARAPHRASE)
        self.assertEqual(len(long.split()), 200)
        self.assertEqual(long.split()[:len(short.split())], short.split())
        for index, word in enumerate(long.split()[len(short.split()):]):
            self.assertEqual(word, SUFFIX.split()[index % len(SUFFIX.split())])
        oracle = json.loads((EXPECTATIONS / "IT-001-paraphrase.json").read_text(encoding="utf-8"))
        variant = oracle["variants"]["IT-001-paraphrase-200.json"]
        self.assertEqual(variant["source_message"], long)
        self.assertEqual(variant["neutral_suffix"], SUFFIX)
        self.assertEqual(oracle["facts"], {
            "request_id": "IT-001", "request_date": "2026-10-22", "kind": "new",
            "requester": "Maya Chen", "team": "Analytics", "system": "Atlas",
            "environment": "staging", "permission": "read", "manager": "Priya Shah",
            "start_date": "2026-10-23", "end_date": "2026-11-06",
            "business_purpose": "Check the dashboard after event definition changes and compare its totals with the spreadsheet.",
        })
        self.assertEqual(oracle["route"], {"policy_rule": 5, "status": "review",
                                          "owner": "System Owner", "next_action": "review-request"})
        self.assertEqual(oracle["issue_fields"], [])
        for stem, source in (("paraphrase-001", short), ("paraphrase-200", long)):
            reply = json.loads((MOCKS / f"{stem}.json").read_text(encoding="utf-8"))
            self.assertEqual(reply["response_source"], "mock")
            self.assertEqual(reply["status"], "completed")
            self.assertEqual(reply["extraction"]["issues"], [])
            self.assertTrue(reply["extraction"]["supporting_quotes"])
            for quote in reply["extraction"]["supporting_quotes"]:
                self.assertIn(quote, source)

    def test_t03_reader_preserves_both_paraphrases_without_truncation(self):
        from access_intake.exports import read_exports

        names = ["IT-001-paraphrase.json", "IT-001-paraphrase-200.json"]
        documents = read_exports([EXPORTS / name for name in names])
        self.assertEqual([d.document_id for d in documents], names)
        self.assertEqual([d.filename_request_id for d in documents], ["IT-001", "IT-001"])
        self.assertEqual(documents[0].message, PARAPHRASE)
        expected_long = json.loads((EXPORTS / names[1]).read_text(encoding="utf-8"))["message"]
        self.assertEqual(documents[1].message, expected_long)
        self.assertEqual(len(documents[1].message.split()), 200)
        self.assertNotEqual(documents[0].source_hash, documents[1].source_hash)


if __name__ == "__main__":
    unittest.main()
