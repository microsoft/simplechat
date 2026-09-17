# test_content_screening_reviews.py
"""
Functional tests for scoped content review, canonical edits and decision binding.
Version: 0.261.106
Implemented in: 0.261.106

Uses unittest and conditional in-memory stores; no Azure services are contacted.
"""

import copy
import hashlib
import importlib.util
import logging
import sys
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
from functools import partial
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

from content_screening import access, jobs, permissions, reviews, service
from content_screening.contracts import (
    ContentUnit,
    DocumentHeldError,
    ScreeningConfigurationError,
    ScreeningConflictError,
    ScreeningError,
    ScreeningValidationError,
    Subject,
    content_fingerprint,
    hash_payload,
    subject_from_document,
)


POLICY = {"enabled": True, "rules": [{"id": "required"}], "ai_checks": []}
PRIVATE_TEXT = "private-evidence-canary"


def module(name, **values):
    value = types.ModuleType(name)
    value.__dict__.update(values)
    return value


class MemoryStore:
    def __init__(self):
        self.records = {}
        self.documents = {}
        self.sequence = 0
        self.events = []

    def version(self, value):
        self.sequence += 1
        return {**copy.deepcopy(value), "_etag": str(self.sequence)}

    def get_scan(self, scan_id):
        return copy.deepcopy(self.records.get(scan_id))

    def create(self, record):
        if record["id"] in self.records:
            raise ScreeningConflictError()
        value = self.version(record)
        self.records[value["id"]] = value
        return copy.deepcopy(value)

    def replace(self, record, etag):
        if self.records[record["id"]]["_etag"] != etag:
            raise ScreeningConflictError()
        value = self.version(record)
        self.records[value["id"]] = value
        return copy.deepcopy(value)

    def read_document(self, subject):
        value = copy.deepcopy(self.documents.get(subject.document_id))
        if not value:
            raise ScreeningConflictError(code="screening_source_missing")
        if subject_from_document(value) != subject:
            raise ScreeningConflictError()
        return value

    def update_document(self, subject, updates, *, etag):
        value = self.read_document(subject)
        if value["_etag"] != etag:
            raise ScreeningConflictError()
        self.documents[subject.document_id] = self.version({**value, **updates})
        return self.read_document(subject)

    def append_event(self, subject, action, actor_id, **kwargs):
        self.events.append({"subject": subject.to_dict(), "action": action, "actor_id": actor_id, **kwargs})

    def query(self, kind, scope_key=None, *, filters=None, continuation=None, page_size=50):
        items = [
            copy.deepcopy(value) for value in self.records.values()
            if value["kind"] == kind and (scope_key is None or value.get("scope_key") == scope_key)
            and all(value.get(key) == expected for key, expected in (filters or {}).items())
        ]
        start = int(continuation or 0)
        return {
            "items": items[start:start + page_size],
            "continuation": str(start + page_size) if len(items) > start + page_size else None,
        }


class MemoryEvidence:
    def __init__(self):
        self.items = {}
        self.reads = 0

    def write(self, subject, key, value):
        self.items[(subject.key, key)] = copy.deepcopy(value)
        return {"private_ref": key, "subject": subject.key}

    def read_json(self, reference, subject):
        self.reads += 1
        if reference["subject"] != subject.key:
            raise ScreeningConflictError()
        return copy.deepcopy(self.items[(subject.key, reference["private_ref"])])

    def write_json(self, subject, scan_id, name, payload):
        return self.write(subject, f"{scan_id}:{name}", payload)

    def read_bytes(self, reference, subject):
        value = self.read_json(reference, subject)
        if not isinstance(value, bytes):
            raise ScreeningConflictError()
        return value


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.repository = MemoryStore()
        self.storage = MemoryEvidence()
        self.roles = {}
        self.public_roles = {}
        self.group_calls = []
        self.approvals = module(
            "functions_approvals",
            create_content_screening_approval=Mock(return_value={"id": "approval"}),
            resolve_content_screening_approval=Mock(),
        )
        group = module("functions_group", assert_group_role=self.group_role)
        public = module(
            "functions_public_workspaces",
            find_public_workspace_by_id=lambda scope: {"id": scope},
            get_user_role_in_public_workspace=lambda workspace, actor: self.public_roles.get((workspace["id"], actor)),
        )
        self.stack.enter_context(patch.dict(sys.modules, {
            "functions_group": group, "functions_public_workspaces": public,
            "functions_approvals": self.approvals,
        }))
        self.stack.enter_context(patch.object(service, "get_effective_policy", return_value=POLICY))
        self.publisher = self.stack.enter_context(patch.object(service, "publish_scan", side_effect=self.publish))
        self.units = [ContentUnit("unit", f"😀 {PRIVATE_TEXT} tail", {"kind": "page", "page_number": 1})]
        self.subject = Subject("personal", "owner", "document", "1")
        self.scan = self.seed("scan", self.subject, self.units)

    def group_role(self, actor, scope, *, allowed_roles):
        self.group_calls.append((actor, scope, allowed_roles))
        role = self.roles.get((scope, actor))
        if role not in allowed_roles:
            raise PermissionError()
        return role

    def seed(self, scan_id, subject, units, *, findings=True, candidate_of=None):
        field = {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}[subject.scope_type]
        fingerprint = content_fingerprint(units)
        result = {
            "status": "findings" if findings else "pass",
            "content_fingerprint": fingerprint, "policy_fingerprint": hash_payload(POLICY),
            "units_total": len(units), "error_code": None,
            "findings": [{
                "finding_id": "finding", "rule_id": "required", "unit_id": units[0].unit_id,
                "category": "pii", "severity": "high", "reason": PRIVATE_TEXT,
                "evidence": PRIVATE_TEXT, "start": 2, "end": 2 + len(PRIVATE_TEXT), "source": "deterministic",
            }] if findings else [],
            "detectors": [{
                "status": "findings" if findings else "pass",
                "required_units": len(units), "completed_units": len(units),
                "required_windows": len(units), "completed_windows": len(units),
            }],
        }
        scan = self.repository.create({
            "id": scan_id, "partition_key": scan_id, "kind": "scan",
            "scope_key": subject.scope_key, "subject": subject.to_dict(),
            "policy": POLICY, "policy_fingerprint": hash_payload(POLICY),
            "content_fingerprint": fingerprint, "state": "pending_review",
            "units_ref": self.storage.write(subject, f"{scan_id}-units", [unit.to_dict() for unit in units]),
            "result_ref": self.storage.write(subject, f"{scan_id}-result", result),
            "source_ref": self.storage.write(subject, f"{scan_id}-original", PRIVATE_TEXT.encode("utf-8")),
            "original_file_name": "document.txt",
            "review_required": True, "coverage_complete": True,
            "result_status": result["status"], "finding_count": len(result["findings"]),
            "units_total": len(units), "approval_id": "approval",
            "parent_scan_id": candidate_of, "sanitized": bool(candidate_of),
        })
        self.repository.documents[subject.document_id] = self.repository.version({
            "id": subject.document_id, field: subject.scope_id, "version": subject.source_revision,
            "file_name": PRIVATE_TEXT,
            "content_screening": {
                "scan_id": scan_id, "source_revision": subject.source_revision,
                "content_fingerprint": fingerprint, "state": "pending_review", "review_required": True,
            },
        })
        return scan

    def publish(self, scan_id, actor_id, **kwargs):
        scan = self.repository.get_scan(scan_id)
        self.assertEqual(scan["state"], "publishing")
        self.assertEqual(self.repository.documents[scan["subject"]["document_id"]]["content_screening"]["state"], "publishing")
        decision = scan["review_decision"]
        self.assertEqual(decision["actor_id"], actor_id)
        self.assertEqual(decision["scan_id"], scan_id)
        self.assertEqual(decision["content_fingerprint"], scan["content_fingerprint"])
        self.assertEqual(decision["policy_snapshot_hash"], hash_payload(POLICY))
        state = "approved_with_flags" if decision["action"] == "approve_with_flags" else "cleared"
        return self.repository.replace({**scan, "state": state}, scan["_etag"])

    def decide(self, action="approve_with_flags", **kwargs):
        return reviews.decide_review(
            self.scan["id"], "owner", self.scan["_etag"], action, "Reviewed the exact content.",
            acknowledge_flags=kwargs.pop("acknowledge_flags", True),
            repository=self.repository, storage=self.storage, **kwargs,
        )

    def release_for_download(self, scan_id="scan", subject=None):
        subject = subject or self.subject
        content = b"Released clean derivative"
        active_blob = {
            "container": f"{subject.scope_type}-documents",
            "path": f"{subject.scope_id}/{subject.document_id}/screened/{scan_id}/clean.txt",
            "etag": "active-blob-etag", "content_hash": hashlib.sha256(content).hexdigest(),
        }
        current = self.repository.get_scan(scan_id)
        scan = self.repository.replace({
            **current, "state": "cleared", "sanitized": True,
            "publication": {"active_blob": active_blob},
        }, current["_etag"])
        document = self.repository.read_document(subject)
        document = self.repository.update_document(subject, {
            "file_name": "reviewed.txt",
            "content_screening": {
                **document["content_screening"], "state": "cleared",
                "policy_fingerprint": scan["policy_fingerprint"],
                "canonical_ref": scan["units_ref"], "sanitized": True,
                "active_blob": active_blob,
            },
        }, etag=document["_etag"])
        return scan, document, content

    def test_original_attachment_uses_only_the_exact_reviewer_source_reference(self):
        with patch.object(self.storage, "read_bytes", wraps=self.storage.read_bytes) as read:
            content, name = reviews.read_review_attachment(
                "scan", "owner", "original", repository=self.repository, storage=self.storage,
            )
        self.assertEqual(content, PRIVATE_TEXT.encode("utf-8"))
        self.assertEqual(name, "original-document.txt")
        read.assert_called_once_with(self.scan["source_ref"], self.subject)
        summary = reviews.get_review("scan", "owner", repository=self.repository)
        self.assertEqual(summary["downloads"]["original"]["url"],
                         "/api/content-screening/reviews/scan/downloads/original")
        self.assertIsNone(summary["downloads"]["clean"])
        self.assertIn("download_original", summary["allowed_actions"])
        self.assertNotIn(PRIVATE_TEXT, str(summary))

    def test_original_attachment_is_not_granted_to_other_personal_users(self):
        for actor in ("admin", "unrelated", "shared-reader"):
            with self.subTest(actor=actor), self.assertRaises(permissions.ScreeningPermissionError):
                reviews.read_review_attachment(
                    "scan", actor, "original", repository=self.repository, storage=self.storage,
                )
        self.assertEqual(self.storage.reads, 0)

    def test_original_download_rechecks_current_group_and_public_review_roles(self):
        for scope_type, roles in (("group", self.roles), ("public", self.public_roles)):
            subject = Subject(scope_type, "workspace", f"{scope_type}-doc", "1")
            scan = self.seed(f"{scope_type}-scan", subject, self.units)
            for role in ("Owner", "Admin", "DocumentManager"):
                with self.subTest(scope=scope_type, role=role):
                    roles[("workspace", "reviewer")] = role
                    content, _name = reviews.read_review_attachment(
                        scan["id"], "reviewer", "original", repository=self.repository, storage=self.storage,
                    )
                    self.assertEqual(content, PRIVATE_TEXT.encode())
            roles[("workspace", "reviewer")] = "User"
            reads = self.storage.reads
            with self.assertRaises(permissions.ScreeningPermissionError):
                reviews.read_review_attachment(
                    scan["id"], "reviewer", "original", repository=self.repository, storage=self.storage,
                )
            self.assertEqual(self.storage.reads, reads)

    def test_original_role_revoked_during_blob_read_never_returns_bytes(self):
        subject = Subject("group", "team", "team-doc", "1")
        self.seed("team-scan", subject, self.units)
        self.roles[("team", "reviewer")] = "DocumentManager"
        read = self.storage.read_bytes

        def revoke(reference, source):
            content = read(reference, source)
            self.roles[("team", "reviewer")] = "User"
            return content

        with patch.object(self.storage, "read_bytes", side_effect=revoke):
            with self.assertRaises(permissions.ScreeningPermissionError):
                reviews.read_review_attachment(
                    "team-scan", "reviewer", "original", repository=self.repository, storage=self.storage,
                )
        self.assertEqual(self.storage.reads, 1)

    def test_original_source_change_during_read_is_not_returned(self):
        read = self.storage.read_bytes

        def replace_source(reference, subject):
            content = read(reference, subject)
            scan = self.repository.get_scan("scan")
            self.repository.replace({
                **scan, "source_ref": self.storage.write(subject, "replacement", b"Replacement"),
            }, scan["_etag"])
            return content

        with patch.object(self.storage, "read_bytes", side_effect=replace_source):
            with self.assertRaises(ScreeningConflictError):
                reviews.read_review_attachment(
                    "scan", "owner", "original", repository=self.repository, storage=self.storage,
                )

    def test_released_clean_attachment_uses_active_access_not_original_storage(self):
        _scan, document, expected = self.release_for_download()
        with patch.object(access, "read_available_document_bytes", return_value=(document, expected)) as read:
            content, name = reviews.read_review_attachment(
                "scan", "owner", "clean", repository=self.repository, storage=self.storage,
            )
        read.assert_called_once_with(
            document, user_id="owner", group_id=None, public_workspace_id=None, purpose="download",
        )
        self.assertEqual((content, name), (expected, "clean-reviewed.txt"))
        self.assertEqual(self.storage.reads, 0)
        summary = reviews.get_review("scan", "owner", repository=self.repository)
        self.assertEqual(set(summary["downloads"]), {"original", "clean"})
        self.assertTrue(all(summary["downloads"].values()))
        self.assertNotIn("active-blob-etag", str(summary))
        with self.assertRaises(permissions.ScreeningPermissionError):
            reviews.read_review_attachment("scan", "other", "original",
                                           repository=self.repository, storage=self.storage)

    def test_clean_attachment_rejects_held_historical_or_incomplete_manifest_without_fallback(self):
        with patch.object(access, "read_available_document_bytes") as read:
            with self.assertRaises(permissions.ScreeningNotFoundError):
                reviews.read_review_attachment("scan", "owner", "clean",
                                               repository=self.repository, storage=self.storage)
            self.release_for_download()
            marker = self.repository.documents["document"]["content_screening"]
            original = copy.deepcopy(marker)
            for change in (
                {"scan_id": "new-scan"}, {"state": "pending_review"},
                {"content_fingerprint": "new-content"}, {"source_revision": "2"},
                {"canonical_ref": {"other": "units"}}, {"active_blob": None},
                {"active_blob": {**original["active_blob"], "etag": "changed"}},
            ):
                with self.subTest(change=change):
                    self.repository.documents["document"]["content_screening"] = {**original, **change}
                    with self.assertRaises(permissions.ScreeningNotFoundError):
                        reviews.read_review_attachment("scan", "owner", "clean",
                                                       repository=self.repository, storage=self.storage)
            read.assert_not_called()
        self.assertEqual(self.storage.reads, 0)

    def test_clean_read_conflicts_and_post_read_source_changes_never_fall_back(self):
        _scan, document, content = self.release_for_download()
        with patch.object(access, "read_available_document_bytes", side_effect=ScreeningConflictError()):
            with self.assertRaises(ScreeningConflictError):
                reviews.read_review_attachment("scan", "owner", "clean",
                                               repository=self.repository, storage=self.storage)

        def replace_after_read(*_args, **_kwargs):
            self.repository.documents["document"] = self.repository.version({
                **document,
                "content_screening": {**document["content_screening"], "scan_id": "replacement"},
            })
            return document, content

        with patch.object(access, "read_available_document_bytes", side_effect=replace_after_read):
            with self.assertRaises(ScreeningConflictError):
                reviews.read_review_attachment("scan", "owner", "clean",
                                               repository=self.repository, storage=self.storage)
        self.assertEqual(self.storage.reads, 0)

    def test_clean_download_rechecks_group_and_public_reviewer_after_active_read(self):
        for scope_type, roles in (("group", self.roles), ("public", self.public_roles)):
            with self.subTest(scope=scope_type):
                subject = Subject(scope_type, "team", f"{scope_type}-document", "1")
                scan_id = f"{scope_type}-scan"
                self.seed(scan_id, subject, self.units)
                _scan, document, content = self.release_for_download(scan_id, subject)
                roles[("team", "reviewer")] = "DocumentManager"

                def revoke_after_read(*_args, **_kwargs):
                    roles[("team", "reviewer")] = "User"
                    return document, content

                with patch.object(access, "read_available_document_bytes", side_effect=revoke_after_read) as read:
                    with self.assertRaises(permissions.ScreeningPermissionError):
                        reviews.read_review_attachment(scan_id, "reviewer", "clean",
                                                       repository=self.repository, storage=self.storage)
                    read.assert_called_once_with(
                        document, user_id="reviewer",
                        group_id="team" if scope_type == "group" else None,
                        public_workspace_id="team" if scope_type == "public" else None,
                        purpose="download",
                    )
        self.assertEqual(self.storage.reads, 0)

    def test_clean_candidate_original_uses_retained_parent_ref_even_after_release(self):
        candidate = self.seed("candidate", self.subject, [ContentUnit("clean", "Reviewed")],
                              findings=False, candidate_of="scan")
        self.repository.records[candidate["id"]]["source_ref"] = copy.deepcopy(self.scan["source_ref"])
        self.release_for_download(candidate["id"])
        with patch.object(self.storage, "read_bytes", wraps=self.storage.read_bytes) as read:
            content, _name = reviews.read_review_attachment(
                "candidate", "owner", "original", repository=self.repository, storage=self.storage,
            )
            self.assertEqual(content, PRIVATE_TEXT.encode())
            read.assert_called_once_with(self.scan["source_ref"], self.subject)
        with self.assertRaises(permissions.ScreeningPermissionError):
            reviews.read_review_attachment("candidate", "admin", "original",
                                           repository=self.repository, storage=self.storage)

    def test_unavailable_evidence_keeps_only_metadata_decisions(self):
        self.repository.records["scan"].update({
            "units_ref": None, "result_ref": None, "source_ref": None, "state": "scan_error",
        })
        summary = reviews.get_review("scan", "owner", repository=self.repository)
        self.assertEqual(summary["allowed_actions"], ["reject", "delete"])
        self.assertEqual(summary["evidence"], {"units_available": False, "findings_available": False})
        self.assertEqual(summary["downloads"], {"original": None, "clean": None})
        self.assertEqual(self.decide("reject")["state"], "rejected")
        self.assertEqual(self.storage.reads, 0)

    def test_deletion_metadata_and_retry_are_scoped_after_source_record_is_missing(self):
        self.repository.records["scan"].update({
            "state": "deleting", "deletion_started_at": "2026-09-16T15:00:00+00:00", "deleted_by": "owner",
        })
        self.repository.documents.pop("document")
        summary = reviews.get_review("scan", "owner", repository=self.repository)
        self.assertEqual(summary["allowed_actions"], ["delete"])
        self.assertFalse(any(summary["evidence"].values()))
        approval = {
            "id": "approval", "group_id": self.subject.scope_key, "status": "pending",
            "metadata": {"scan_id": "scan", "subject": self.subject.to_dict()},
        }
        self.assertTrue(permissions.can_review_approval(approval, "owner", repository=self.repository))
        self.assertFalse(permissions.can_review_approval(approval, "other", repository=self.repository))
        for actor, kind in (("owner", "original"), ("owner", "clean"), ("other", "original")):
            with self.subTest(actor=actor, kind=kind), self.assertRaises(
                (permissions.ScreeningPermissionError, ScreeningConflictError)
            ):
                reviews.read_review_attachment("scan", actor, kind,
                                               repository=self.repository, storage=self.storage)
        with self.assertRaises(permissions.ScreeningPermissionError):
            reviews.get_review("scan", "other", repository=self.repository)
        with patch.object(service, "delete_screened_document", return_value={
            **self.repository.get_scan("scan"), "state": "deleted",
        }) as delete:
            self.assertEqual(self.decide("delete")["state"], "deleted")
            delete.assert_called_once()
        self.assertEqual(self.storage.reads, 0)
        self.repository.records["scan"]["state"] = "pending_review"
        self.assertFalse(permissions.can_review_approval(approval, "owner", repository=self.repository))
        with self.assertRaises(ScreeningConflictError):
            reviews.get_review("scan", "owner", repository=self.repository)

    def test_missing_source_deletion_recovery_requires_recorded_actor_and_operation(self):
        self.repository.documents.pop("document")
        recorded = {"deleted_by": "owner", "deletion_started_at": "2026-09-16T15:00:00+00:00"}
        for state in ("deleting", "deleted"):
            for invalid in (
                {"deleted_by": None}, {"deleted_by": ""}, {"deleted_by": 7},
                {"deletion_started_at": None}, {"deletion_started_at": ""},
                {"deletion_started_at": "not-a-time"}, {"deletion_started_at": "2026-09-16T15:00:00"},
            ):
                with self.subTest(state=state, invalid=invalid):
                    self.repository.records["scan"].update({**recorded, **invalid, "state": state})
                    with self.assertRaises(ScreeningConflictError):
                        reviews.get_review("scan", "owner", repository=self.repository)
                    with patch.object(service, "delete_screened_document") as delete:
                        with self.assertRaises(ScreeningConflictError):
                            self.decide("delete")
                        delete.assert_not_called()
            self.repository.records["scan"].update({**recorded, "state": state})
            summary = reviews.get_review("scan", "owner", repository=self.repository)
            self.assertEqual(summary["allowed_actions"], ["delete"] if state == "deleting" else [])
            self.assertFalse(any(summary["downloads"].values()))
            self.assertFalse(any(summary["evidence"].values()))
        self.assertEqual(self.storage.reads, 0)

    def test_missing_source_pending_or_rejected_reviews_have_no_recovery_bypass(self):
        self.repository.documents.pop("document")
        for state in ("pending_review", "rejected", "scan_error", "incomplete", "publishing"):
            with self.subTest(state=state):
                self.repository.records["scan"].update({
                    "state": state, "deleted_by": "owner",
                    "deletion_started_at": "2026-09-16T15:00:00+00:00",
                })
                with self.assertRaises(ScreeningConflictError):
                    reviews.get_review("scan", "owner", repository=self.repository)
                for action in ("reject", "delete"):
                    with patch.object(service, "delete_screened_document") as delete:
                        with self.assertRaises(ScreeningConflictError):
                            self.decide(action)
                        delete.assert_not_called()
        self.assertEqual(self.storage.reads, 0)

    def test_owner_can_self_review_but_admin_has_no_private_evidence_override(self):
        self.assertEqual(reviews.get_review("scan", "owner", repository=self.repository)["id"], "scan")
        for actor in ("another-owner", "all-workspaces-admin"):
            with self.subTest(actor=actor), self.assertRaises(permissions.ScreeningPermissionError):
                reviews.get_review_units("scan", actor, repository=self.repository, storage=self.storage)
        self.assertEqual(self.storage.reads, 0)

    def test_ensure_review_requires_explicit_delivery_ack_without_persisting_it(self):
        before = self.repository.get_scan("scan")
        document = copy.deepcopy(self.repository.documents["document"])
        for acknowledgement in (None, False, "true", 1, True):
            with self.subTest(acknowledgement=acknowledgement):
                self.approvals.create_content_screening_approval.return_value = {
                    "id": "approval", "notifications_complete": acknowledgement,
                }
                result = reviews.ensure_review(self.scan, "owner", repository=self.repository)
                self.assertIs(result["notifications_complete"], acknowledgement is True)
                self.assertEqual(self.repository.get_scan("scan"), before)
                self.assertEqual(self.repository.documents["document"], document)

    def test_group_roles_are_revalidated_and_read_members_cannot_review(self):
        subject = Subject("group", "team", "team-doc", "1")
        self.seed("team-scan", subject, self.units)
        self.roles[("team", "manager")] = "DocumentManager"
        reviews.get_review("team-scan", "manager", repository=self.repository)
        self.assertEqual(self.group_calls[-1][1], "team")
        self.assertEqual(self.group_calls[-1][2], ("Owner", "Admin", "DocumentManager"))
        self.roles[("team", "manager")] = "User"
        with self.assertRaises(permissions.ScreeningPermissionError):
            reviews.get_review("team-scan", "manager", repository=self.repository)

    def test_public_owner_admin_and_document_manager_only(self):
        subject = Subject("public", "public-space", "public-doc", "1")
        self.seed("public-scan", subject, self.units)
        for role in ("Owner", "Admin", "DocumentManager", "User", None):
            self.public_roles[("public-space", "reviewer")] = role
            if role in permissions.REVIEW_ROLES:
                reviews.get_review("public-scan", "reviewer", repository=self.repository)
            else:
                with self.assertRaises(permissions.ScreeningPermissionError):
                    reviews.get_review("public-scan", "reviewer", repository=self.repository)

    def test_approval_binding_checks_the_exact_scan_and_scope(self):
        approval = {
            "id": "approval", "group_id": self.subject.scope_key,
            "status": "pending",
            "metadata": {"scan_id": "scan", "subject": self.subject.to_dict()},
        }
        self.assertTrue(permissions.can_review_approval(approval, "owner", repository=self.repository))
        self.assertFalse(permissions.can_review_approval(approval, "admin", repository=self.repository))
        approval["metadata"]["subject"]["document_id"] = "another-document"
        self.assertFalse(permissions.can_review_approval(approval, "owner", repository=self.repository))

    def test_scan_summaries_and_queues_omit_evidence_paths_policies_and_reasons(self):
        summary = reviews.get_review("scan", "owner", repository=self.repository)
        self.assertNotIn(PRIVATE_TEXT, str(summary))
        self.assertFalse({"policy", "source_ref", "units_ref", "result_ref", "file_name"} & set(summary))
        queue = reviews.list_reviews("owner", repository=self.repository)
        self.assertEqual(len(queue["items"]), 1)
        self.assertNotIn(PRIVATE_TEXT, str(queue))
        self.assertEqual(reviews.list_reviews("admin", repository=self.repository)["items"], [])

    def test_indexed_snapshot_coverage_never_implies_original_file_inspection(self):
        self.repository.records["scan"].update({"coverage_source": "indexed_snapshot", "source_ref": None})
        summary = reviews.get_review("scan", "owner", repository=self.repository)
        self.assertEqual(summary["coverage_mode"], "indexed_snapshot")
        self.assertIs(summary["original_retained"], False)

    def test_etag_and_hash_conflicts_do_not_read_or_modify_content(self):
        with self.assertRaises(ScreeningConflictError):
            reviews.preview_remediation("scan", "owner", "stale", [], repository=self.repository, storage=self.storage)
        self.assertEqual(self.storage.reads, 0)
        with self.assertRaises(ScreeningConflictError):
            reviews.apply_edits(self.units, [{"action": "remove_unit", "unit_id": "unit", "content_hash": "stale"}])

    def test_unicode_offsets_and_multiple_spans_use_original_canonical_text(self):
        unit = ContentUnit("unicode", "😀 first first final")
        edited, _removed, _warnings = reviews.apply_edits([unit], [
            {"action": "remove_span", "unit_id": "unicode", "content_hash": unit.content_hash, "start": 2, "end": 7},
            {"action": "remove_span", "unit_id": "unicode", "content_hash": unit.content_hash, "start": 8, "end": 13},
        ])
        self.assertEqual(edited[0].text, "😀   final")
        for start, end in ((True, 2), (1, 100), (3, 2)):
            with self.assertRaises(ScreeningValidationError):
                reviews.apply_edits([unit], [{
                    "action": "remove_span", "unit_id": "unicode", "content_hash": unit.content_hash,
                    "start": start, "end": end,
                }])

    def test_page_removal_excludes_linked_and_unlocated_supplements(self):
        units = [
            ContentUnit("page1", "remove", {"kind": "page", "page_number": 1}),
            ContentUnit("page2", "keep", {"kind": "page", "page_number": 2}),
            ContentUnit("linked", "remove", {"kind": "figure", "page_number": 1}),
            ContentUnit("overlap", "remove", {"kind": "figure", "page_numbers": [1, 2]}),
            ContentUnit("unlocated", "remove", {"kind": "vision"}),
            ContentUnit("metadata", "remove", {"kind": "metadata"}),
        ]
        edited, removed, warnings = reviews.apply_edits(units, [{
            "action": "remove_unit", "unit_id": "page1", "content_hash": units[0].content_hash,
        }])
        self.assertEqual([unit.unit_id for unit in edited], ["page2"])
        self.assertEqual(len(removed), 5)
        self.assertTrue(any("Unlocated" in warning for warning in warnings))

    def test_synthetic_number_is_not_treated_as_a_physical_page(self):
        units = [
            ContentUnit("synthetic", "remove segment", {"kind": "chunk", "page_number": 1}),
            ContentUnit("physical", "keep physical page", {"kind": "page", "page_number": 1}),
        ]
        edited, removed, _warnings = reviews.apply_edits(units, [{
            "action": "remove_unit", "unit_id": "synthetic", "content_hash": units[0].content_hash,
        }])
        self.assertEqual(removed, ["synthetic"])
        self.assertEqual([unit.unit_id for unit in edited], ["physical"])

    def test_cell_replacement_removes_linked_formula_and_retains_cell_identity(self):
        locator = {"kind": "table_cell", "sheet_index": 0, "sheet": "Sheet", "row": 1, "column": 2, "value_type": "number"}
        cell = ContentUnit("cell", "12345", locator)
        formula = ContentUnit("formula", "=PRIVATE()", {**locator, "kind": "table_formula"})
        edited, removed, _warnings = reviews.apply_edits([cell, formula], [{
            "action": "replace_cell", "unit_id": "cell", "content_hash": cell.content_hash, "text": "removed",
        }])
        self.assertEqual(removed, ["formula"])
        self.assertEqual(edited[0].locator, {**locator, "value_type": "text"})
        self.assertEqual(edited[0].text, "removed")
        with self.assertRaises(ScreeningValidationError):
            reviews.apply_edits([formula], [{
                "action": "replace_cell", "unit_id": "formula", "content_hash": formula.content_hash, "text": "x",
            }])

    def test_oversized_units_are_fully_accessible_through_bounded_windows(self):
        units = [ContentUnit("large", "😀" * (reviews.MAX_PAGE_CHARACTERS + 7))]
        self.seed("large-scan", self.subject, units)
        first = reviews.get_review_units("large-scan", "owner", repository=self.repository, storage=self.storage)
        second = reviews.get_review_units(
            "large-scan", "owner", continuation=first["continuation"],
            repository=self.repository, storage=self.storage,
        )
        self.assertEqual(len(first["items"][0]["text"]), reviews.MAX_PAGE_CHARACTERS)
        self.assertEqual(second["items"][0]["text_offset"], reviews.MAX_PAGE_CHARACTERS)
        self.assertEqual(first["items"][0]["text"] + second["items"][0]["text"], units[0].text)
        self.assertEqual(second["items"][0]["content_hash"], units[0].content_hash)

    def test_preview_shows_late_edits_instead_of_only_the_first_document_page(self):
        units = [ContentUnit(f"unit-{index}", f"Text segment {index}") for index in range(80)]
        scan = self.seed("many-units", self.subject, units)
        preview = reviews.preview_remediation("many-units", "owner", scan["_etag"], [{
            "action": "remove_span", "unit_id": units[-1].unit_id, "content_hash": units[-1].content_hash,
            "start": 0, "end": 5,
        }], repository=self.repository, storage=self.storage)
        self.assertEqual([unit["unit_id"] for unit in preview["units"]], ["unit-79"])
        self.assertEqual(preview["units"][0]["text"], "segment 79")
        self.assertEqual(preview["total_units"], 80)
        self.assertFalse(preview["preview_truncated"])
        self.assertEqual(self.repository.get_scan("many-units")["_etag"], scan["_etag"])

    def test_approve_with_flags_requires_acknowledgement_and_retains_exact_decision(self):
        with self.assertRaises(ScreeningValidationError):
            self.decide(acknowledge_flags=False)
        result = self.decide()
        self.assertEqual(result["state"], "approved_with_flags")
        self.assertTrue(result["warning"])
        self.assertEqual(result["decision"]["reason"], "Reviewed the exact content.")
        self.publisher.assert_called_once()
        with self.assertRaises(ScreeningConflictError):
            self.decide()

    def test_incomplete_error_and_changed_policy_cannot_be_approved(self):
        for change in ({"coverage_complete": False}, {"state": "scan_error"}, {"result_status": "incomplete"}):
            original = self.repository.get_scan("scan")
            self.repository.records["scan"] = {**original, **change}
            with self.subTest(change=change), self.assertRaises(DocumentHeldError):
                self.decide()
            self.repository.records["scan"] = original
        with patch.object(service, "get_effective_policy", return_value={"changed": True}):
            with self.assertRaises(ScreeningConflictError):
                self.decide()
        self.publisher.assert_not_called()

    def test_scan_complete_flag_cannot_override_missing_detector_coverage(self):
        result = self.storage.items[(self.subject.key, "scan-result")]
        result["detectors"][0]["completed_units"] = 0
        with self.assertRaises(DocumentHeldError):
            self.decide()
        self.publisher.assert_not_called()

    def test_late_role_revocation_stops_publication_after_the_conditional_hold(self):
        subject = Subject("group", "team", "team-doc", "1")
        scan = self.seed("team-scan", subject, self.units)
        self.roles[("team", "manager")] = "DocumentManager"
        original = self.repository.append_event

        def revoke(*args, **kwargs):
            original(*args, **kwargs)
            self.roles[("team", "manager")] = "User"

        with patch.object(self.repository, "append_event", side_effect=revoke):
            with self.assertRaises(permissions.ScreeningPermissionError):
                reviews.decide_review(
                    "team-scan", "manager", scan["_etag"], "approve_with_flags", "Reviewed.",
                    acknowledge_flags=True, repository=self.repository, storage=self.storage,
                )
        self.assertEqual(self.repository.documents["team-doc"]["content_screening"]["state"], "scan_error")
        self.publisher.assert_not_called()

    def test_concurrent_document_replacement_cannot_receive_an_old_decision(self):
        original = self.storage.read_json
        changed = False

        def replace_document(reference, subject):
            nonlocal changed
            result = original(reference, subject)
            if not changed:
                changed = True
                document = self.repository.documents["document"]
                self.repository.documents["document"] = self.repository.version({
                    **document,
                    "content_screening": {**document["content_screening"], "scan_id": "new-scan", "state": "scanning"},
                })
            return result

        with patch.object(self.storage, "read_json", side_effect=replace_document):
            with self.assertRaises(ScreeningConflictError):
                self.decide()
        self.assertEqual(self.repository.documents["document"]["content_screening"]["scan_id"], "new-scan")
        self.publisher.assert_not_called()

    def test_approve_clean_requires_a_complete_candidate_rescan(self):
        self.scan = self.seed("clean-original", self.subject, self.units, findings=False)
        with self.assertRaises(DocumentHeldError):
            self.decide("approve_clean")
        self.scan = self.seed("candidate", self.subject, self.units, findings=False, candidate_of="scan")
        result = self.decide("approve_clean")
        self.assertEqual(result["state"], "cleared")

    def test_stalled_publication_retry_reuses_only_the_exact_prior_decision(self):
        self.decide()
        scan = self.repository.get_scan("scan")
        decision = copy.deepcopy(scan["review_decision"])
        old = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        self.scan = self.repository.replace({
            **scan, "state": "publishing", "review_operation_started_at": old,
            "lease": {"owner": "lost-worker", "expires_at": old},
        }, scan["_etag"])
        result = self.decide("retry_publication")
        self.assertEqual(result["state"], "approved_with_flags")
        self.assertEqual(self.repository.get_scan("scan")["review_decision"], decision)
        self.approvals.resolve_content_screening_approval.assert_called_with(
            self.repository.get_scan("scan"), "owner", "approve_with_flags",
        )

    def test_transient_publication_failure_preserves_expired_lease_and_exact_retry(self):
        expired = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        failed_snapshot = {}

        def fail_after_partial_publication(scan_id, actor_id, **_kwargs):
            scan = self.repository.get_scan(scan_id)
            self.assertEqual(scan["review_decision"]["actor_id"], actor_id)
            failed_snapshot.update(self.repository.replace({
                **scan, "state": "publishing",
                "lease": {"owner": "partial-publisher", "expires_at": expired},
                "error_code": "screening_publication_failed",
            }, scan["_etag"]))
            raise ScreeningError(code="screening_publication_failed")

        self.publisher.side_effect = fail_after_partial_publication
        with self.assertRaises(ScreeningError):
            self.decide()
        self.assertEqual(self.repository.get_scan("scan"), failed_snapshot)
        self.assertEqual(self.repository.documents["document"]["content_screening"]["state"], "publishing")
        self.assertTrue(failed_snapshot["review_required"])
        self.assertTrue(failed_snapshot["coverage_complete"])
        summary = reviews.get_review("scan", "owner", repository=self.repository)
        self.assertIn("retry_publication", summary["allowed_actions"])
        self.assertFalse({"approve_with_flags", "approve_clean"} & set(summary["allowed_actions"]))
        self.assertIsNone(summary["downloads"]["clean"])
        self.approvals.resolve_content_screening_approval.assert_not_called()

        self.scan = self.repository.get_scan("scan")
        self.publisher.side_effect = self.publish
        result = self.decide("retry_publication")
        self.assertEqual(result["state"], "approved_with_flags")
        self.assertEqual(self.repository.get_scan("scan")["review_decision"], failed_snapshot["review_decision"])
        self.assertEqual(self.publisher.call_count, 2)

    def test_incomplete_or_active_publication_cannot_be_retried_as_approval(self):
        with self.assertRaises(ScreeningConflictError):
            self.decide("retry_publication")
        self.decide()
        scan = self.repository.get_scan("scan")
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        self.scan = self.repository.replace({
            **scan, "state": "publishing", "lease": {"owner": "live-worker", "expires_at": future},
        }, scan["_etag"])
        with self.assertRaises(ScreeningConflictError):
            self.decide("retry_publication")
        self.scan = self.repository.replace({**self.scan, "state": "scan_error"}, self.scan["_etag"])
        with self.assertRaises(ScreeningConflictError):
            self.decide("retry_publication")

    def test_failed_remediation_returns_to_a_recoverable_hold(self):
        with patch.object(service, "create_candidate_scan", side_effect=ScreeningConfigurationError()):
            with self.assertRaises(ScreeningConfigurationError):
                reviews.remediate_review("scan", "owner", self.scan["_etag"], [{
                    "action": "remove_span", "unit_id": "unit", "content_hash": self.units[0].content_hash,
                    "start": 2, "end": 2 + len(PRIVATE_TEXT),
                }], repository=self.repository, storage=self.storage)
        self.assertEqual(self.repository.documents["document"]["content_screening"]["state"], "scan_error")
        summary = reviews.get_review("scan", "owner", repository=self.repository)
        self.assertIn("remediate", summary["allowed_actions"])
        self.assertNotIn("approve_with_flags", summary["allowed_actions"])

    def test_remediation_rescans_all_surviving_units_and_never_publishes(self):
        self.units.append(ContentUnit("tail", "Last unit must also be rescanned."))
        self.repository.records.pop("scan")
        self.scan = self.seed("scan", self.subject, self.units)
        seen = []

        def candidate(scan_id, units, actor, **kwargs):
            self.assertEqual(self.repository.documents["document"]["content_screening"]["state"], "remediating")
            seen.extend(units)
            return self.seed("candidate", self.subject, units, findings=False, candidate_of=scan_id)

        with patch.object(service, "create_candidate_scan", side_effect=candidate):
            result = reviews.remediate_review("scan", "owner", self.scan["_etag"], [{
                "action": "remove_span", "unit_id": "unit", "content_hash": self.units[0].content_hash,
                "start": 2, "end": 2 + len(PRIVATE_TEXT),
            }], repository=self.repository, storage=self.storage)
        self.assertEqual(result["state"], "pending_review")
        self.assertEqual([unit.unit_id for unit in seen], ["unit", "tail"])
        self.assertNotIn(PRIVATE_TEXT, seen[0].text)
        self.publisher.assert_not_called()

    def test_real_candidate_engine_checks_the_tail_and_never_auto_publishes(self):
        """Isolate complete engine coverage; the API suite verifies durable enqueueing."""
        from content_screening.policies import compose_policy, default_policy

        policy = default_policy()
        policy.update({"enabled": True, "rules": [{
            "id": "sensitive", "name": "Sensitive", "type": "literal", "values": [PRIVATE_TEXT],
            "enabled": True, "severity": "high", "category": "sensitive",
        }]})
        effective = compose_policy(policy)
        units = [*self.units, ContentUnit("tail", PRIVATE_TEXT)]
        self.repository.records.pop("scan")
        self.scan = self.seed("scan", self.subject, units)
        self.repository.records["scan"].update({
            "policy": effective, "policy_fingerprint": hash_payload(effective),
        })
        self.storage.items[(self.subject.key, "scan-result")]["policy_fingerprint"] = hash_payload(effective)
        enqueue = Mock()
        inline_candidate = partial(service.create_candidate_scan, run_inline=True)
        with patch.object(service, "create_candidate_scan", inline_candidate), \
                patch.object(jobs, "enqueue_document_scan", enqueue), patch.object(service, "_settings", return_value={
            "enable_content_screening": True, "enable_enhanced_citations": True,
        }), patch.object(service, "validate_screening_configuration"), \
                patch.object(service, "get_effective_policy", return_value=effective), \
                patch.object(service, "_log"):
            result = reviews.remediate_review("scan", "owner", self.scan["_etag"], [{
                "action": "remove_span", "unit_id": "unit", "content_hash": units[0].content_hash,
                "start": 2, "end": 2 + len(PRIVATE_TEXT),
            }], repository=self.repository, storage=self.storage)
        enqueue.assert_not_called()
        self.assertEqual((result["state"], result["outcome"]), ("pending_review", "findings"))
        candidate = self.repository.get_scan(result["id"])
        evidence = self.storage.read_json(candidate["result_ref"], self.subject)
        self.assertTrue(any(finding["unit_id"] == "tail" for finding in evidence["findings"]))
        self.assertTrue(result["coverage"]["complete"])
        self.publisher.assert_not_called()

    def test_reject_stays_held_and_delete_revokes_before_trusted_deletion(self):
        result = self.decide("reject")
        self.assertEqual(result["state"], "rejected")
        self.assertEqual(self.repository.documents["document"]["content_screening"]["state"], "rejected")
        self.scan = self.repository.get_scan("scan")

        def delete(scan_id, actor, **kwargs):
            self.assertEqual(self.repository.documents["document"]["content_screening"]["state"], "deleting")
            self.repository.documents.pop("document")
            current = self.repository.get_scan(scan_id)
            return self.repository.replace({**current, "state": "deleted", "source_ref": None}, current["_etag"])

        with patch.object(service, "delete_screened_document", side_effect=delete):
            deleted = self.decide("delete")
        self.assertEqual(deleted["state"], "deleted")
        self.publisher.assert_not_called()

    def test_failed_delete_can_be_retried_without_releasing_content(self):
        with patch.object(service, "delete_screened_document", side_effect=RuntimeError("unavailable")):
            with self.assertRaises(RuntimeError):
                self.decide("delete")
        self.assertEqual(self.repository.documents["document"]["content_screening"]["state"], "deleting")
        self.scan = self.repository.get_scan("scan")

        def finish_delete(scan_id, actor_id, **kwargs):
            scan = self.repository.get_scan(scan_id)
            return self.repository.replace({**scan, "state": "deleted"}, scan["_etag"])

        with patch.object(service, "delete_screened_document", side_effect=finish_delete):
            self.assertEqual(self.decide("delete")["state"], "deleted")
        self.publisher.assert_not_called()


class ApprovalProjectionTests(unittest.TestCase):
    def setUp(self):
        self.records = {}
        self.notices = {}
        self.subject = Subject("personal", "owner", "document", "1")
        self.scan = {"id": "scan", "subject": self.subject.to_dict(), "state": "pending_review", "review_required": True}
        self.container = Mock()
        self.container.create_item.side_effect = self.create
        self.container.read_item.side_effect = lambda item, partition_key: copy.deepcopy(self.records[item])
        self.container.query_items.side_effect = lambda **kwargs: list(copy.deepcopy(self.records).values())
        self.container.replace_item.side_effect = self.replace
        stubs = {
            "config": module("config", cosmos_approvals_container=self.container, cosmos_groups_container=Mock()),
            "functions_appinsights": module("functions_appinsights", log_event=Mock()),
            "functions_notifications": module(
                "functions_notifications", create_notification=self.notify, delete_notifications_by_metadata=Mock(),
            ),
            "functions_group": module("functions_group", find_group_by_id=Mock()),
            "functions_settings": module("functions_settings", get_settings=lambda: {}),
            "functions_debug": module("functions_debug", debug_print=Mock()),
        }
        with patch.dict(sys.modules, stubs):
            spec = importlib.util.spec_from_file_location("screening_approval_projection_tests", APP_DIR / "functions_approvals.py")
            self.approvals = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.approvals)

    def create(self, body):
        if body["id"] in self.records:
            error = RuntimeError("private-provider-error")
            error.status_code = 409
            raise error
        self.records[body["id"]] = {**copy.deepcopy(body), "_etag": "etag"}
        return copy.deepcopy(self.records[body["id"]])

    def notify(self, **kwargs):
        receipt = {
            **kwargs, "id": hash_payload([kwargs["user_id"], kwargs["idempotency_key"]]),
            "scope": "personal", "assignment": None,
        }
        self.notices[(kwargs["user_id"], kwargs["idempotency_key"])] = copy.deepcopy(kwargs)
        return copy.deepcopy(receipt)

    def replace(self, item, body, *, etag, match_condition):
        if self.records[item]["_etag"] != etag:
            error = RuntimeError("private-provider-error")
            error.status_code = 412
            raise error
        self.records[item] = {**copy.deepcopy(body), "_etag": "replaced"}
        return copy.deepcopy(self.records[item])

    def test_review_requests_and_notices_are_idempotent_minimal_and_nonexpiring(self):
        first = self.approvals.create_content_screening_approval(self.scan, "all-workspaces-admin")
        second = self.approvals.create_content_screening_approval(self.scan, "all-workspaces-admin")
        self.assertEqual(first["id"], second["id"])
        self.assertIs(first["notifications_complete"], True)
        self.assertIs(second["notifications_complete"], True)
        self.assertEqual(len(self.records), 1)
        self.assertNotIn("notifications_complete", self.records[first["id"]])
        self.assertEqual(first["ttl"], -1)
        self.assertIsNone(first["expires_at"])
        self.assertEqual(len(self.notices), 1)
        notice = next(iter(self.notices.values()))
        self.assertEqual(notice["user_id"], "owner")
        self.assertNotIn("assignment", notice)
        self.assertIn("scope_type=personal", notice["link_url"])
        self.assertIn("scope_id=owner", notice["link_url"])
        self.assertIn("scan_id=scan", notice["link_url"])
        self.assertNotIn(PRIVATE_TEXT, str(first) + str(notice))

    def test_notification_completion_rejects_none_or_unbound_receipts(self):
        for receipt in (
            None, False, {"id": "unbound"},
            {"id": "wrong-audience", "scope": "assignment", "user_id": "owner"},
        ):
            with self.subTest(receipt=receipt), patch.object(
                self.approvals, "create_notification", return_value=receipt,
            ):
                approval = self.approvals.create_content_screening_approval(self.scan, "owner")
                self.assertIs(approval["notifications_complete"], False)
                self.assertEqual(approval["status"], "pending")
                self.assertEqual(len(self.records), 1)
                self.assertNotIn("notifications_complete", self.records[approval["id"]])

    def test_partial_notification_failure_retries_idempotently_without_skipping_other_reviewers(self):
        self.subject = Subject("group", "team", "document", "1")
        self.scan["subject"] = self.subject.to_dict()
        failed = True

        def send(**kwargs):
            if kwargs["user_id"] == "first-reviewer" and failed:
                raise RuntimeError(PRIVATE_TEXT)
            return self.notify(**kwargs)

        with patch.object(self.approvals, "reviewer_ids", return_value=["first-reviewer", "second-reviewer"]), \
                patch.object(self.approvals, "create_notification", side_effect=send):
            first = self.approvals.create_content_screening_approval(self.scan, "scanner")
            self.assertIs(first["notifications_complete"], False)
            self.assertEqual({notice["user_id"] for notice in self.notices.values()}, {"second-reviewer"})
            failed = False
            second = self.approvals.create_content_screening_approval(self.scan, "scanner")
            third = self.approvals.create_content_screening_approval(self.scan, "scanner")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["id"], third["id"])
        self.assertIs(second["notifications_complete"], True)
        self.assertIs(third["notifications_complete"], True)
        self.assertEqual(len(self.notices), 2)
        self.assertEqual(len(self.records), 1)
        self.assertNotIn(PRIVATE_TEXT, str(self.approvals.log_event.call_args_list))

    def test_no_reviewer_or_failed_reviewer_lookup_is_not_a_delivery_acknowledgement(self):
        with patch.object(self.approvals, "reviewer_ids", return_value=[]):
            approval = self.approvals.create_content_screening_approval(self.scan, "owner")
            self.assertIs(approval["notifications_complete"], False)
        with patch.object(self.approvals, "reviewer_ids", side_effect=RuntimeError(PRIVATE_TEXT)), \
                patch.object(self.approvals, "log_event", side_effect=RuntimeError("Telemetry unavailable")):
            approval = self.approvals.create_content_screening_approval(self.scan, "owner")
            self.assertIs(approval["notifications_complete"], False)
        self.assertEqual(self.notices, {})
        self.assertEqual(len(self.records), 1)

    def test_resolved_or_unknown_approval_status_cannot_fabricate_notification_acknowledgement(self):
        with patch.object(self.approvals, "create_notification", return_value=None) as notify:
            approval = self.approvals.create_content_screening_approval(self.scan, "owner")
            notify.reset_mock()
            for status in ("executed", "denied", "approved", "failed", "unknown"):
                with self.subTest(status=status):
                    self.records[approval["id"]]["status"] = status
                    result = self.approvals.create_content_screening_approval(self.scan, "owner")
                    self.assertIs(result["notifications_complete"], False)
                    self.assertNotIn("notifications_complete", self.records[approval["id"]])
            notify.assert_not_called()

    def test_legacy_requester_self_approval_stays_denied(self):
        legacy = {"request_type": "delete_group", "requester_id": "requester", "metadata": {}}
        self.assertFalse(self.approvals._can_user_approve(legacy, "requester", ["Admin"]))
        self.assertTrue(self.approvals._can_user_deny(legacy, "requester", ["Admin"]))
        screening = {"request_type": "content_screening_review", "requester_id": "owner", "metadata": {}}
        with patch.object(self.approvals, "can_review_approval", return_value=True) as authorize:
            self.assertTrue(self.approvals._can_user_approve(screening, "owner", ["User"]))
            authorize.assert_called_once_with(screening, "owner")
        with patch.object(self.approvals, "can_review_approval", return_value=False):
            self.assertFalse(self.approvals._can_user_view(screening, "admin", ["Admin"]))
            self.assertFalse(self.approvals._can_user_deny(screening, "owner", ["Admin"]))

    def test_generic_approve_deny_cannot_bypass_dedicated_lifecycle(self):
        approval = self.approvals.create_content_screening_approval(self.scan, "owner")
        with self.assertRaises(PermissionError):
            self.approvals.approve_request(approval["id"], approval["group_id"], "owner", "", "", approval=approval)
        with self.assertRaises(PermissionError):
            self.approvals.deny_request(approval["id"], approval["group_id"], "owner", "", "", "deny", approval=approval)
        with self.assertRaises(PermissionError):
            self.approvals.mark_approval_executed(approval["id"], approval["group_id"], True, "bypass")
        self.container.upsert_item.assert_not_called()

    def test_projection_is_conditional_and_contains_no_private_decision_reason(self):
        approval = self.approvals.create_content_screening_approval(self.scan, "owner")
        scan = {
            **self.scan, "approval_id": approval["id"], "state": "approved_with_flags",
            "review_decision": {"reason": PRIVATE_TEXT},
        }
        with patch.dict(sys.modules, {
            "azure.core": module("azure.core", MatchConditions=types.SimpleNamespace(IfNotModified="if-not-modified")),
        }):
            result = self.approvals.resolve_content_screening_approval(scan, "owner", "approve_with_flags")
            repeated = self.approvals.resolve_content_screening_approval(scan, "owner", "approve_with_flags")
        self.assertEqual(result, repeated)
        self.assertEqual(result["status"], "executed")
        self.assertEqual(self.container.replace_item.call_args.kwargs["etag"], "etag")
        self.assertEqual(self.container.replace_item.call_count, 1)
        self.assertNotIn(PRIVATE_TEXT, str(result))
        self.container.upsert_item.assert_not_called()

    def test_projection_race_never_uses_an_unconditional_upsert(self):
        approval = self.approvals.create_content_screening_approval(self.scan, "owner")
        scan = {**self.scan, "approval_id": approval["id"], "state": "rejected"}
        error = RuntimeError("private-provider-error")
        error.status_code = 412
        self.container.replace_item.side_effect = error
        with patch.dict(sys.modules, {
            "azure.core": module("azure.core", MatchConditions=types.SimpleNamespace(IfNotModified="if-not-modified")),
        }):
            with self.assertRaises(ScreeningConflictError):
                self.approvals.resolve_content_screening_approval(scan, "owner", "reject")
        self.assertEqual(self.records[approval["id"]]["status"], "pending")
        self.container.upsert_item.assert_not_called()

    def test_screening_review_never_auto_expires_but_legacy_expiry_still_runs(self):
        self.approvals.create_content_screening_approval(self.scan, "owner")
        self.records["legacy"] = {
            "id": "legacy", "group_id": "group", "request_type": "delete_group",
            "status": "pending", "expires_at": (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=4)).isoformat(),
        }
        with patch.object(self.approvals, "deny_request") as deny:
            self.assertEqual(self.approvals.auto_deny_expired_approvals(), 1)
            deny.assert_called_once()
            self.assertEqual(deny.call_args.kwargs["approval_id"], "legacy")


class NotificationCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.logs = Mock()
        self.debug = Mock()
        self.container = Mock()
        self.notification_records = {}
        self.container.create_item.side_effect = self.store_notification
        self.container.read_item.side_effect = self.read_notification
        self.stack.enter_context(patch.dict(sys.modules, {
            "config": module(
                "config", cosmos_approvals_container=Mock(), cosmos_groups_container=Mock(),
                cosmos_notifications_container=self.container,
            ),
            "functions_appinsights": module("functions_appinsights", log_event=self.logs),
            "functions_debug": module("functions_debug", debug_print=self.debug),
            "functions_settings": module("functions_settings", get_settings=lambda: {}),
            "functions_group": module("functions_group", find_group_by_id=Mock()),
            "functions_public_workspaces": module(
                "functions_public_workspaces", find_public_workspace_by_id=Mock(), get_user_public_workspaces=Mock(),
            ),
        }))
        self.notifications = self.load("functions_notifications", APP_DIR / "functions_notifications.py")
        self.approvals = self.load("functions_approvals", APP_DIR / "functions_approvals.py")

    def store_notification(self, item):
        if item["id"] in self.notification_records:
            error = RuntimeError(PRIVATE_TEXT)
            error.status_code = 409
            raise error
        self.notification_records[item["id"]] = copy.deepcopy(item)
        return copy.deepcopy(item)

    def read_notification(self, *, item, partition_key):
        record = self.notification_records[item]
        self.assertEqual(partition_key, record["user_id"])
        return copy.deepcopy(record)

    @staticmethod
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
        return value

    def test_existing_standard_notification_lifecycle_stays_unchanged(self):
        existing = self.load(
            "screening_existing_notification_regression",
            Path(__file__).parent / "test_approval_notification_routing_fix.py",
        )
        output = StringIO()
        with redirect_stdout(output):
            success = existing.test_standard_approval_notifications_and_cleanup()
        self.assertTrue(success, output.getvalue())

    def test_deterministic_notification_ids_suppress_duplicates_without_provider_logs(self):
        error = RuntimeError(PRIVATE_TEXT)
        error.status_code = 409
        self.container.create_item.side_effect = error
        result = self.notifications.create_notification(
            user_id="owner", notification_type="approval_request_pending",
            notification_id="scan-owner-notice",
        )
        self.assertEqual(result, {"id": "scan-owner-notice"})
        error.status_code = 503
        self.assertIsNone(self.notifications.create_notification(
            user_id="owner", notification_type="approval_request_pending",
            notification_id="scan-owner-notice",
        ))
        self.assertNotIn(PRIVATE_TEXT, str(self.logs.call_args_list) + str(self.debug.call_args_list))

    def test_screening_notification_cleanup_never_logs_provider_error_content(self):
        self.container.query_items.side_effect = RuntimeError(PRIVATE_TEXT)
        self.assertEqual(self.notifications.delete_notifications_by_metadata(
            metadata_filters={"approval_id": "approval"}, safe_errors=True,
        ), 0)
        self.assertNotIn(PRIVATE_TEXT, str(self.logs.call_args_list) + str(self.debug.call_args_list))

    def test_retry_key_returns_the_original_notification_and_preserves_read_state(self):
        key = "private-retry-key-canary"
        first = self.notifications.create_notification(
            user_id="owner", notification_type="approval_request_approved",
            title="Content ready", message="Ready.", metadata={"attempt": 1}, idempotency_key=key,
        )
        self.notification_records[first["id"]]["read_by"] = ["owner"]
        self.notification_records[first["id"]]["dismissed_by"] = ["owner"]
        second = self.notifications.create_notification(
            user_id="owner", notification_type="approval_request_approved",
            title="Changed title", message="Changed message.", metadata={"attempt": 2}, idempotency_key=key,
        )
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(first["id"].startswith("notification-"))
        self.assertEqual(second["title"], "Content ready")
        self.assertEqual(second["metadata"], {"attempt": 1})
        self.assertEqual(second["created_at"], first["created_at"])
        self.assertEqual(second["read_by"], ["owner"])
        self.assertEqual(second["dismissed_by"], ["owner"])
        self.assertEqual(len(self.notification_records), 1)
        self.container.read_item.assert_called_once_with(item=first["id"], partition_key="owner")
        self.assertNotIn(key, str(second) + str(self.logs.call_args_list) + str(self.debug.call_args_list))

    def test_retry_ids_are_bound_to_scope_recipient_type_and_assignment(self):
        targets = [
            {"user_id": "owner"},
            {"user_id": "another-owner"},
            {"group_id": "team"},
            {"public_workspace_id": "workspace"},
            {"assignment": {"roles": ["Admin"]}},
            {"assignment": {"personal_workspace_owner_id": "owner"}},
        ]
        identifiers = []
        for target in targets:
            first = self.notifications.create_notification(
                **target, notification_type="approval_request_approved", idempotency_key="same-event",
            )
            second = self.notifications.create_notification(
                **target, notification_type="approval_request_approved", idempotency_key="same-event",
            )
            self.assertEqual(first, second)
            identifiers.append(first["id"])
        self.assertEqual(len(set(identifiers)), len(targets))
        other_type = self.notifications.create_notification(
            user_id="owner", notification_type="approval_request_denied", idempotency_key="same-event",
        )
        self.assertNotIn(other_type["id"], identifiers)

    def test_omitting_retry_key_preserves_random_ids(self):
        first = self.notifications.create_notification(user_id="owner")
        second = self.notifications.create_notification(user_id="owner")
        self.assertNotEqual(first["id"], second["id"])
        self.assertFalse(first["id"].startswith("notification-"))
        self.container.read_item.assert_not_called()

    def test_retry_key_preserves_custom_types_without_logging_their_values(self):
        first = self.notifications.create_notification(
            user_id="owner", notification_type=PRIVATE_TEXT, idempotency_key="custom-event",
        )
        second = self.notifications.create_notification(
            user_id="owner", notification_type=PRIVATE_TEXT, idempotency_key="custom-event",
        )
        self.assertEqual(first, second)
        self.assertNotIn(PRIVATE_TEXT, str(self.logs.call_args_list) + str(self.debug.call_args_list))

    def test_invalid_or_ambiguous_retry_keys_never_write(self):
        for key in ("", " ", True, 1, {}, "x" * 513):
            with self.subTest(key_type=type(key).__name__):
                self.assertIsNone(self.notifications.create_notification(
                    user_id="owner", idempotency_key=key,
                ))
        self.assertIsNone(self.notifications.create_notification(
            user_id="owner", notification_id="explicit-id", idempotency_key="event",
        ))
        self.container.create_item.assert_not_called()

    def test_retry_storage_and_telemetry_failures_never_escape(self):
        first = self.notifications.create_notification(user_id="owner", idempotency_key="event")
        self.assertIsNotNone(first)
        self.container.read_item.side_effect = RuntimeError(PRIVATE_TEXT)
        self.logs.side_effect = RuntimeError("Telemetry unavailable")
        self.assertIsNone(self.notifications.create_notification(user_id="owner", idempotency_key="event"))
        self.container.create_item.side_effect = RuntimeError(PRIVATE_TEXT)
        self.assertIsNone(self.notifications.create_notification(user_id="owner", idempotency_key="another-event"))
        self.assertNotIn(PRIVATE_TEXT, str(self.logs.call_args_list) + str(self.debug.call_args_list))

    def test_retry_read_cannot_return_a_different_audience_record(self):
        first = self.notifications.create_notification(user_id="owner", idempotency_key="event")
        self.container.read_item.side_effect = None
        self.container.read_item.return_value = {**first, "user_id": "another-owner"}
        self.assertIsNone(self.notifications.create_notification(user_id="owner", idempotency_key="event"))

    def test_notification_failure_does_not_fail_review_creation_or_change_the_hold(self):
        repository = MemoryStore()
        subject = Subject("personal", "owner", "document", "1")
        scan = repository.create({
            "id": "scan", "partition_key": "scan", "kind": "scan",
            "subject": subject.to_dict(), "state": "pending_review", "review_required": True,
        })
        document = {
            "id": "document", "user_id": "owner", "version": "1",
            "content_screening": {"scan_id": "scan", "state": "pending_review", "review_required": True},
        }
        repository.documents["document"] = copy.deepcopy(document)
        self.approvals.cosmos_approvals_container.create_item.side_effect = lambda body: {
            **copy.deepcopy(body), "_etag": "approval-etag",
        }
        self.container.create_item.side_effect = RuntimeError(PRIVATE_TEXT)
        self.logs.side_effect = RuntimeError("Telemetry unavailable")
        result = reviews.ensure_review(scan, "owner", repository=repository)
        self.assertEqual(result["status"], "pending")
        self.assertIs(result["notifications_complete"], False)
        self.assertEqual(repository.get_scan("scan")["approval_id"], result["id"])
        self.assertEqual(repository.documents["document"], document)


if __name__ == "__main__":
    unittest.main()
