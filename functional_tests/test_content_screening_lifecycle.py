# test_content_screening_lifecycle.py
"""
Functional tests for the content screening release boundary.
Version: 0.261.106
Implemented in: 0.261.106

Uses in-memory conditional repositories and protected artifacts to exercise
quarantine, complete coverage, sticky findings, approval binding, and races.
"""

import copy
import sys
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# The service resolves Azure dependencies only when an operation needs them.
from content_screening import service
from content_screening.contracts import (
    ContentUnit,
    DetectorResult,
    DocumentHeldError,
    Finding,
    InspectionResult,
    ScreeningConflictError,
    ScreeningError,
    Subject,
    content_fingerprint,
    document_is_available,
    hash_payload,
)


POLICY = {"enabled": True, "rules": [{"id": "required-rule"}], "ai_checks": []}


class MemoryRepository:
    def __init__(self):
        self.sequence = 1
        self.document = {"id": "document", "user_id": "owner", "version": 1, "file_name": "document.txt", "_etag": "1"}
        self.records = {}

    def _version(self, value):
        self.sequence += 1
        return {**copy.deepcopy(value), "_etag": str(self.sequence)}

    def read_document(self, subject):
        if subject.document_id != self.document["id"] or subject.source_revision != str(self.document["version"]):
            raise ScreeningConflictError()
        return copy.deepcopy(self.document)

    def update_document(self, subject, updates, *, etag):
        self.read_document(subject)
        if self.document["_etag"] != etag:
            raise ScreeningConflictError()
        self.document = self._version({**self.document, **updates})
        return copy.deepcopy(self.document)

    def create(self, record):
        if record["id"] in self.records:
            raise ScreeningConflictError()
        self.records[record["id"]] = self._version(record)
        return copy.deepcopy(self.records[record["id"]])

    def replace(self, record, etag):
        if self.records[record["id"]]["_etag"] != etag:
            raise ScreeningConflictError()
        self.records[record["id"]] = self._version(record)
        return copy.deepcopy(self.records[record["id"]])

    def get_scan(self, scan_id):
        return copy.deepcopy(self.records.get(scan_id))


class MemoryStorage:
    def __init__(self):
        self.items = {}

    def write_json(self, subject, scan_id, name, value):
        key = (subject.key, scan_id, name)
        if key in self.items and self.items[key] != value:
            raise ScreeningConflictError()
        self.items[key] = copy.deepcopy(value)
        return {"key": key, "subject": subject.key}

    def read_json(self, reference, subject):
        if reference["subject"] != subject.key:
            raise ScreeningConflictError()
        return copy.deepcopy(self.items[reference["key"]])


class ScreeningLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.repository = MemoryRepository()
        self.storage = MemoryStorage()
        self.subject = Subject("personal", "owner", "document", "1")
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(service, "_settings", return_value={
            "enable_content_screening": True, "enable_enhanced_citations": True,
        }))
        self.stack.enter_context(patch.object(service, "validate_screening_configuration"))
        self.stack.enter_context(patch.object(service, "get_effective_policy", return_value=copy.deepcopy(POLICY)))
        self.stack.enter_context(patch.object(service, "_log"))
        self.review_requests = []
        reviews = types.ModuleType("content_screening.reviews")
        reviews.ensure_review = lambda scan, actor_id, **kwargs: self.review_requests.append(scan["id"])
        self.stack.enter_context(patch.dict(sys.modules, {"content_screening.reviews": reviews}))
        self.published = []
        self.original_publish = service.publish_scan

        def publish(scan_id, actor_id, **kwargs):
            return self.original_publish(
                scan_id, actor_id, **kwargs,
                publisher=lambda document, units, scan, actor, **options: self._publish(units),
            )

        self.stack.enter_context(patch.object(service, "publish_scan", side_effect=publish))

    def _publish(self, units):
        self.assertFalse(document_is_available(self.repository.document))
        self.published.append([unit.text for unit in units])
        return {"blob_container": "documents", "blob_path": "reviewed.txt", "file_name": "reviewed.txt", "blob_etag": "blob-version"}

    def _begin(self):
        return service.begin_scan(self.subject, "owner", repository=self.repository)

    def _result(self, units, findings=None, *, complete=True):
        findings = findings or []
        detector = DetectorResult(
            "findings" if findings else "pass", findings,
            required_units=len(units), completed_units=len(units) if complete else len(units) - 1,
            required_windows=len(units), completed_windows=len(units) if complete else len(units) - 1,
        )
        return InspectionResult(
            detector.status, content_fingerprint(units), hash_payload(POLICY),
            findings=findings, detectors=[detector.to_dict()], units_total=len(units),
        )

    def _inspect(self, scan, units, result):
        def engine(subject, content, policy, **kwargs):
            self.assertEqual(self.repository.document["content_screening"]["state"], "scanning")
            self.assertFalse(document_is_available(self.repository.document))
            return result

        return service.inspect_scan(
            scan["id"], units, "owner", repository=self.repository, storage=self.storage, engine=engine,
        )

    def test_hold_precedes_inspection_and_release_follows_complete_publication(self):
        scan = self._begin()
        self.assertFalse(document_is_available(self.repository.document))
        units = [ContentUnit("first", "First page"), ContentUnit("last", "Last page")]
        result = self._inspect(scan, units, self._result(units))
        self.assertEqual(result["state"], "cleared")
        self.assertTrue(document_is_available(self.repository.document))
        self.assertEqual(self.published, [["First page", "Last page"]])

    def test_last_page_finding_never_publishes_earlier_content(self):
        scan = self._begin()
        units = [ContentUnit("first", "Ordinary"), ContentUnit("last", "private-canary")]
        finding = Finding("required-rule", "last", "sensitive", "high", "Review", 0, 14, "private-canary")
        result = self._inspect(scan, units, self._result(units, [finding]))
        self.assertEqual(result["state"], "pending_review")
        self.assertFalse(self.published)
        self.assertEqual(self.review_requests, [scan["id"]])
        self.assertFalse(document_is_available(self.repository.document))

    def test_clean_retry_does_not_erase_an_unresolved_finding(self):
        scan = self._begin()
        units = [ContentUnit("unit", "sensitive")]
        finding = Finding("required-rule", "unit", "sensitive", "high", "Review", 0, 9, "sensitive")
        self._inspect(scan, units, self._result(units, [finding]))
        result = self._inspect(scan, units, self._result(units))
        self.assertEqual(result["state"], "pending_review")
        self.assertEqual(result["finding_count"], 1)
        self.assertFalse(self.published)

    def test_document_hold_survives_a_crash_before_scan_flag_persistence(self):
        scan = self._begin()
        self.repository.document["content_screening"]["review_required"] = True
        units = [ContentUnit("unit", "A later inspection appears clean")]
        result = self._inspect(scan, units, self._result(units))
        self.assertEqual(result["state"], "pending_review")
        self.assertTrue(result["review_required"])
        self.assertFalse(self.published)

    def test_review_notification_reconciliation_requires_bound_receipts(self):
        scan = self._begin()
        units = [ContentUnit("unit", "sensitive")]
        finding = Finding("required-rule", "unit", "sensitive", "high", "Review")
        self._inspect(scan, units, self._result(units, [finding]))
        current = self.repository.get_scan(scan["id"])
        self.repository.replace({**current, "approval_id": "approval-one"}, current["_etag"])
        reviews = sys.modules["content_screening.reviews"]
        for receipt in (None, {"id": "approval-one"}, {"id": "other", "notifications_complete": True}):
            reviews.ensure_review = lambda *args, **kwargs: receipt
            result = service.reconcile_scan_completion(scan["id"], repository=self.repository)
            self.assertTrue(result["postprocess_pending"])
            self.assertFalse(document_is_available(self.repository.document))
        reviews.ensure_review = lambda *args, **kwargs: {"id": "approval-one", "notifications_complete": True}
        result = service.reconcile_scan_completion(scan["id"], repository=self.repository)
        self.assertFalse(result["postprocess_pending"])
        self.assertTrue(result["review_notifications_complete"])
        self.assertFalse(document_is_available(self.repository.document))

    def test_incomplete_coverage_cannot_publish_a_pass(self):
        scan = self._begin()
        units = [ContentUnit("first", "one"), ContentUnit("last", "two")]
        with self.assertRaises(ScreeningError):
            self._inspect(scan, units, self._result(units, complete=False))
        self.assertFalse(self.published)
        self.assertEqual(self.repository.document["content_screening"]["state"], "scan_error")

    def test_wrong_revision_result_is_not_applied(self):
        scan = self._begin()
        units = [ContentUnit("unit", "source")]
        result = self._result(units)
        result.content_fingerprint = "a-different-revision"
        with self.assertRaises(ScreeningConflictError):
            self._inspect(scan, units, result)
        self.assertFalse(self.published)

    def test_approval_must_bind_actor_content_and_policy(self):
        scan = self._begin()
        units = [ContentUnit("unit", "sensitive")]
        finding = Finding("required-rule", "unit", "sensitive", "high", "Review")
        self._inspect(scan, units, self._result(units, [finding]))
        with self.assertRaises(DocumentHeldError):
            service.publish_scan(scan["id"], "owner", repository=self.repository, storage=self.storage)
        current = self.repository.get_scan(scan["id"])
        current["review_decision"] = {
            "action": "approve_with_flags", "actor_id": "owner", "reason": "Accepted",
            "content_fingerprint": current["content_fingerprint"],
            "policy_fingerprint": current["policy_fingerprint"],
            "policy_snapshot_hash": hash_payload(current["policy"]),
            "scan_id": current["id"], "source_revision": "1",
            "decided_at": service._timestamp(), "acknowledged_flags": True,
        }
        self.repository.replace(current, current["_etag"])
        with self.assertRaises(DocumentHeldError):
            service.publish_scan(scan["id"], "another-user", repository=self.repository, storage=self.storage)
        result = service.publish_scan(scan["id"], "owner", repository=self.repository, storage=self.storage)
        self.assertEqual(result["state"], "approved_with_flags")
        self.assertTrue(document_is_available(self.repository.document))

    def test_policy_change_does_not_release_approved_old_policy_content(self):
        scan = self._begin()
        units = [ContentUnit("unit", "sensitive")]
        finding = Finding("required-rule", "unit", "sensitive", "high", "Review")
        self._inspect(scan, units, self._result(units, [finding]))
        with patch.object(service, "get_effective_policy", return_value={"enabled": True, "new_policy": True}):
            with self.assertRaises(ScreeningConflictError):
                service.publish_scan(scan["id"], "owner", repository=self.repository, storage=self.storage)
        self.assertFalse(document_is_available(self.repository.document))


if __name__ == "__main__":
    unittest.main()
