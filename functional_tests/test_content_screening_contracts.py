# test_content_screening_contracts.py
"""
Functional tests for revision-bound content screening contracts.
Version: 0.261.106
Implemented in: 0.261.106

These tests validate canonical source identity, evidence offsets, and fail-closed
availability without bootstrapping Flask or contacting Azure services.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# This package has no application startup side effects.
from content_screening.contracts import (
    ContentUnit,
    DocumentHeldError,
    Finding,
    ScreeningConflictError,
    ScreeningValidationError,
    Subject,
    content_fingerprint,
    document_is_available,
    normalize_units,
    public_screening_summary,
    require_document_available,
    subject_from_document,
)


class ScreeningContractTests(unittest.TestCase):
    def test_scope_and_revision_are_part_of_source_identity(self):
        personal = Subject("personal", "user-one", "document-one", "1")
        self.assertNotEqual(personal.key, Subject("personal", "user-two", "document-one", "1").key)
        self.assertNotEqual(personal.key, Subject("personal", "user-one", "document-one", "2").key)
        self.assertEqual(personal, Subject.from_dict(personal.to_dict()))
        self.assertEqual(
            subject_from_document({"id": "document-one", "user_id": "user-one"}), personal,
        )

    def test_future_subject_kinds_are_not_implicitly_enabled(self):
        with self.assertRaises(ScreeningValidationError):
            Subject("personal", "user", "document", "1", kind="message")

    def test_canonical_text_and_locators_are_fingerprinted(self):
        first = ContentUnit("unit-1", "text", {"page_number": 1})
        second = ContentUnit("unit-1", "text", {"page_number": 2})
        self.assertNotEqual(content_fingerprint([first]), content_fingerprint([second]))
        self.assertEqual(ContentUnit.from_dict(first.to_dict()), first)
        tampered = {**first.to_dict(), "text": "changed"}
        with self.assertRaises(ScreeningConflictError):
            ContentUnit.from_dict(tampered)

    def test_empty_and_ambiguous_units_are_not_clean_content(self):
        unit = ContentUnit("unit-1", "text")
        for values in ([], [ContentUnit("blank", " ")], [unit, unit]):
            with self.subTest(values=values):
                with self.assertRaises(ScreeningValidationError):
                    normalize_units(values)

    def test_offsets_reject_boolean_and_partial_ranges(self):
        for offsets in ((True, 2), (0, None), (2, 1), (-1, 1)):
            with self.subTest(offsets=offsets):
                with self.assertRaises(ScreeningValidationError):
                    Finding("rule", "unit", "pii", "high", "Review", start=offsets[0], end=offsets[1])

    def test_legacy_documents_remain_unenrolled(self):
        self.assertTrue(document_is_available({"id": "legacy"}))
        self.assertIsNone(public_screening_summary({"id": "legacy"}))

    def test_malformed_marker_and_unknown_states_fail_closed(self):
        for marker in (None, {}, {"state": "unknown"}, {"state": "cleared"}):
            document = {"version": 1, "content_screening": marker}
            with self.subTest(marker=marker):
                self.assertFalse(document_is_available(document))
                with self.assertRaises(DocumentHeldError):
                    require_document_available(document)

    def test_only_exact_cleared_revision_is_available(self):
        document = {
            "version": 2,
            "content_screening": {
                "state": "approved_with_flags",
                "source_revision": "2",
                "scan_id": "scan-1",
                "content_fingerprint": "fingerprint",
                "finding_count": 1,
                "private_original": "secret-pointer",
                "findings": ["sensitive"],
            },
        }
        self.assertTrue(document_is_available(document))
        summary = public_screening_summary(document)
        self.assertEqual(summary["finding_count"], 1)
        self.assertNotIn("private_original", summary)
        self.assertNotIn("findings", summary)
        document["version"] = 3
        self.assertFalse(document_is_available(document))
        for invalid_version in (0, False, -1, "0", "not-a-version"):
            document["version"] = invalid_version
            self.assertFalse(document_is_available(document))


if __name__ == "__main__":
    unittest.main()
