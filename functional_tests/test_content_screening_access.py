# test_content_screening_access.py
"""
Behavioral regression tests for authoritative document quarantine access.
Version: 0.261.141
Implemented in: 0.261.106
Same-name revision location ownership added in: 0.261.141

Uses fake Cosmos/Blob containers, injected canonical storage, and a local Flask
test client. No Azure resources, credentials, or application startup are used.
"""

import asyncio
from collections import Counter
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Blueprint, Flask, Response, jsonify
from werkzeug.test import Client

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

# Resolve the application package only after configuring the standalone path.
from content_screening import access
from content_screening.contracts import (
    ContentUnit,
    DocumentHeldError,
    ScreeningConflictError,
    ScreeningValidationError,
    content_fingerprint,
    hash_payload,
    metadata_fingerprint,
    subject_from_document,
)


def fake_module(name, **values):
    module = ModuleType(name)
    module.__dict__.update(values)
    return module


class MissingDocument(Exception):
    status_code = 404


class FakeContainer:
    def __init__(self, documents=None):
        self.documents = documents if documents is not None else {}
        self.reads = Counter()
        self.failure = None

    def read_item(self, item, partition_key):
        self.reads[item] += 1
        if self.failure:
            raise self.failure
        if item not in self.documents:
            raise MissingDocument()
        return deepcopy(self.documents[item])

    def query_items(self, query, parameters=None, **kwargs):
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        if "@path" in values:
            return [
                deepcopy(document) for document in self.documents.values()
                if document.get("blob_path") == values["@path"]
                or document.get("archived_blob_path") == values["@path"]
                or document.get("file_name") == values.get("@file_name")
            ]
        return [deepcopy(document) for document in self.documents.values()]


class ScreeningAccessFixture(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "isolated-functional-test"
        self.units = [ContentUnit("unit-1", "Clean approved text", {"page_number": 1})]
        self.content = b"Clean approved text"
        self.document = {
            "id": "document-1",
            "user_id": "user-1",
            "version": 2,
            "file_name": "reviewed.txt",
            "title": "Reviewed title",
            "abstract": "Reviewed abstract",
            "keywords": ["reviewed"],
            "authors": ["Reviewed author"],
            "num_chunks": 1,
            "blob_container": "user-documents",
            "blob_path": "user-1/original.txt",
            "content_screening": {
                "state": "cleared",
                "source_revision": "2",
                "scan_id": "scan-1",
                "content_fingerprint": content_fingerprint(self.units),
                "canonical_ref": {"name": "canonical-1"},
                "finding_count": 0,
                "availability_generation": 1,
                "active_blob": {
                    "container": "user-documents",
                    "path": "user-1/document-1/screened/scan-1/reviewed.txt",
                    "etag": "approved-etag",
                    "content_hash": hashlib.sha256(self.content).hexdigest(),
                },
            },
        }
        self.documents = {"document-1": self.document}
        self.personal = FakeContainer(self.documents)
        self.groups = FakeContainer()
        self.public = FakeContainer()
        self.scans = FakeContainer()
        self.seed_release(self.document)
        self.conversations = FakeContainer({"conversation-1": {"id": "conversation-1", "user_id": "user-1"}})
        self.messages = FakeContainer()
        self.memberships = {("user-1", "group-1")}
        self.workspace_ids = {"workspace-1"}
        self.blob_requests = []
        self.after_blob_read = None
        self.unit_reads = 0
        self.config = fake_module(
            "config",
            CLIENTS={"storage_account_office_docs_client": SimpleNamespace(get_blob_client=self.blob_client)},
            cosmos_user_documents_container=self.personal,
            cosmos_group_documents_container=self.groups,
            cosmos_public_documents_container=self.public,
            cosmos_content_screening_container=self.scans,
            cosmos_conversations_container=self.conversations,
            cosmos_messages_container=self.messages,
            storage_account_user_documents_container_name="user-documents",
            storage_account_group_documents_container_name="group-documents",
            storage_account_public_documents_container_name="public-documents",
            storage_account_personal_chat_container_name="personal-chat",
        )
        self.modules = {
            "config": self.config,
            "functions_authentication": fake_module("functions_authentication", get_current_user_id=lambda: "user-1"),
            "agent_execution_context": fake_module("agent_execution_context", execution_user_id=lambda: None),
            "functions_group": fake_module("functions_group", assert_group_role=self.assert_group_role),
            "functions_public_workspaces": fake_module(
                "functions_public_workspaces",
                find_public_workspace_by_id=lambda workspace_id: {"id": workspace_id} if workspace_id in self.workspace_ids else None,
                get_user_visible_public_workspace_ids_from_settings=lambda _user: [],
            ),
            "functions_collaboration": fake_module(
                "functions_collaboration", build_conversation_participation_context=self.authorize_conversation,
            ),
            "functions_documents": fake_module(
                "functions_documents",
                get_document_blob_storage_info=lambda document, **_kwargs: (document["blob_container"], document["blob_path"]),
                normalize_document_revision_families=lambda **_kwargs: False,
            ),
            "functions_settings": fake_module("functions_settings", get_settings=lambda: {"enable_content_screening": False}),
            "content_screening.storage": fake_module(
                "content_screening.storage", ScreeningStorage=lambda: SimpleNamespace(read_json=self.read_units),
            ),
        }
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)

    def seed_release(self, document):
        """Store an independent completed scan, not a self-authorizing marker."""
        marker = document["content_screening"]
        policy = {"test_policy": "approved"}
        marker["policy_fingerprint"] = hash_payload(policy)
        self.scans.documents[marker["scan_id"]] = {
            "id": marker["scan_id"], "kind": "scan",
            "subject": subject_from_document(document).to_dict(),
            "state": marker["state"], "coverage_complete": True, "result_status": "pass",
            "policy": policy, "policy_fingerprint": marker["policy_fingerprint"],
            "content_fingerprint": marker["content_fingerprint"],
            "units_ref": deepcopy(marker["canonical_ref"]),
            "publication": {
                "active_blob": deepcopy(marker["active_blob"]),
                "metadata_fingerprint": metadata_fingerprint(document),
                "content_fingerprint": marker["content_fingerprint"],
            },
        }

    def assert_group_role(self, user_id, group_id, allowed_roles):
        if (user_id, group_id) not in self.memberships:
            raise PermissionError("Membership revoked.")
        self.assertIn("Owner", allowed_roles)
        self.assertIn("Admin", allowed_roles)
        return "User"

    def authorize_conversation(self, user_id, conversation):
        if conversation["user_id"] != user_id:
            raise PermissionError("Conversation not authorized.")
        return {}

    def read_units(self, reference, subject):
        self.unit_reads += 1
        self.assertEqual(reference, {"name": "canonical-1"})
        self.assertEqual(subject.document_id, "document-1")
        return [unit.to_dict() for unit in self.units]

    def blob_client(self, container, blob):
        self.blob_requests.append((container, blob))

        def download_blob(**arguments):
            self.assertEqual(arguments.get("etag"), "approved-etag")

            def readall():
                if self.after_blob_read:
                    self.after_blob_read()
                return self.content
            return SimpleNamespace(readall=readall)
        return SimpleNamespace(download_blob=download_blob)

    def hold(self):
        self.document["content_screening"]["state"] = "pending_review"

    def search_result(self, text="Clean approved text", **changes):
        return {
            "id": "document-1_1", "document_id": "document-1", "version": 2,
            "user_id": "user-1", "chunk_text": text, "chunk_sequence": 1,
            "file_name": "old.txt", "title": "OLD_PRIVATE_TITLE",
            "chunk_summary": "OLD_PRIVATE_SUMMARY", "chunk_keywords": ["OLD_PRIVATE_KEYWORD"],
            **changes,
        }


class AuthoritativeAvailabilityTests(ScreeningAccessFixture):
    def test_stale_positive_record_and_disabled_toggle_do_not_release_hold(self):
        snapshot = deepcopy(self.document)
        self.hold()
        with self.assertRaises(DocumentHeldError):
            access.assert_document_available(snapshot, user_id="user-1")
        self.assertEqual(self.personal.reads["document-1"], 1)

    def test_legacy_record_still_works_without_screening_dependencies(self):
        del self.document["content_screening"]
        with patch.object(access, "_load_active_units", side_effect=AssertionError("No private read for legacy")):
            result = access.assert_document_available("document-1", user_id="user-1")
        self.assertEqual(result["title"], "Reviewed title")
        self.assertIsNot(result, self.document)

    def test_nonterminal_malformed_and_wrong_revision_markers_fail_closed(self):
        original = deepcopy(self.document["content_screening"])
        markers = [None, [], {}, {"state": "cleared"}, {"state": ["cleared"]}]
        markers.extend({**original, "state": state} for state in (
            "pending_scan", "scanning", "scan_error", "incomplete", "pending_review",
            "remediating", "publishing", "rejected", "deleting", "deleted", "unknown",
        ))
        markers.extend([
            {**original, "source_revision": "1"},
            {**original, "scan_id": {"secret": "not-an-identifier"}},
            {**original, "content_fingerprint": True},
            {**original, "review_required": True},
        ])
        for marker in markers:
            with self.subTest(marker=marker):
                self.document["content_screening"] = marker
                with self.assertRaises(DocumentHeldError):
                    access.assert_document_available("document-1", user_id="user-1")
                self.assertFalse(access.public_document_payload(self.document)["content_screening"]["available"])

    def test_metadata_failure_is_safe_and_never_uses_the_supplied_record(self):
        self.personal.failure = RuntimeError("SECRET provider credentials")
        with self.assertRaises(DocumentHeldError) as failure:
            access.assert_document_available(self.document, user_id="user-1")
        self.assertNotIn("SECRET", str(failure.exception))

    def test_caught_reader_failure_cannot_enable_a_model_fallback(self):
        def failed_reader(**_arguments):
            raise RuntimeError("SECRET provider configuration")

        with self.app.test_request_context():
            try:
                access.assert_document_available("document-1", "user-1", metadata_reader=failed_reader)
            except DocumentHeldError:
                pass
            with self.assertRaises(DocumentHeldError):
                access.assert_current_request_sources_available("user-1")

    def test_personal_and_current_group_membership_authorization_are_required(self):
        with self.assertRaises(PermissionError):
            access.assert_document_available("document-1", user_id="other-user")
        group_document = {**self.document, "group_id": "group-1"}
        self.groups.documents["document-1"] = group_document
        self.seed_release(group_document)
        access.assert_document_available("document-1", user_id="user-1", group_id="group-1")
        self.memberships.clear()
        with self.assertRaises(PermissionError):
            access.assert_document_available("document-1", user_id="user-1", group_id="group-1")

    def test_shared_group_access_requires_an_approved_share_and_fresh_membership(self):
        document = {**self.document, "group_id": "owner-group", "shared_group_ids": ["group-1,approved"]}
        self.groups.documents["document-1"] = document
        self.seed_release(document)
        access.assert_document_available("document-1", user_id="user-1", group_id="owner-group")
        document["shared_group_ids"] = ["group-1,pending"]
        with self.assertRaises(PermissionError):
            access.assert_document_available("document-1", user_id="user-1", group_id="owner-group")

    def test_public_scope_existence_is_checked_without_an_admin_bypass(self):
        self.public.documents["document-1"] = {**self.document, "public_workspace_id": "workspace-1"}
        self.seed_release(self.public.documents["document-1"])
        access.assert_document_available("document-1", user_id="user-1", public_workspace_id="workspace-1")
        self.workspace_ids.clear()
        with self.assertRaises(PermissionError):
            access.assert_document_available("document-1", user_id="user-1", public_workspace_id="workspace-1")

    def test_search_reads_once_per_unique_source_and_strips_stale_metadata(self):
        results = access.filter_available_results([self.search_result(), self.search_result()], "user-1")
        self.assertEqual(len(results), 2)
        self.assertEqual(self.personal.reads["document-1"], 1)
        self.assertEqual(self.unit_reads, 1)
        self.assertEqual(results[0]["title"], "Reviewed title")
        self.assertEqual(results[0]["chunk_summary"], "")
        self.assertEqual(results[0]["chunk_keywords"], ["reviewed"])
        self.assertIn(access.PROVENANCE_FIELD, results[0])

    def test_search_drops_unversioned_cache_and_same_version_removed_text(self):
        self.assertEqual(access.filter_available_results([self.search_result()], "user-1", cached=True), [])
        self.assertEqual(access.filter_available_results([self.search_result("REMOVED PRIVATE TEXT")], "user-1"), [])
        cached = access.filter_available_results([self.search_result()], "user-1")
        self.document["content_screening"]["availability_generation"] += 1
        self.assertEqual(access.filter_available_results(cached, "user-1", cached=True), [])

    def test_cache_provenance_cannot_authorize_a_different_source_id(self):
        forged = self.search_result(document_id="other-document")
        forged[access.PROVENANCE_FIELD] = access.document_provenance(self.document)
        self.assertEqual(access.filter_available_results([forged], "user-1", cached=True), [])

    def test_broad_search_can_use_another_document_while_one_is_held(self):
        self.hold()
        self.documents["legacy"] = {"id": "legacy", "version": 1, "user_id": "user-1"}
        with self.app.test_request_context():
            results = access.filter_available_results(
                [self.search_result(), {"document_id": "legacy", "chunk_text": "legacy", "version": 1}],
                "user-1",
            )
            self.assertEqual([result["document_id"] for result in results], ["legacy"])
            access.assert_current_request_sources_available("user-1")

    def test_explicit_ordered_chunks_reject_stale_and_partial_content(self):
        chunks = access.assert_document_chunks_available(
            [self.search_result()], "document-1", user_id="user-1", expected_chunk_count=1,
        )
        self.assertEqual(chunks[0]["chunk_text"], "Clean approved text")
        for candidate, expected in (([self.search_result("REMOVED")], 1), ([], 1)):
            with self.subTest(candidate=candidate):
                with self.assertRaises((DocumentHeldError, ScreeningConflictError)):
                    access.assert_document_chunks_available(
                        candidate, "document-1", user_id="user-1", expected_chunk_count=expected,
                    )

    def test_missing_or_tampered_canonical_content_is_not_ordinary_knowledge(self):
        self.units = [ContentUnit("unit-1", "tampered")]
        self.assertEqual(access.filter_available_results([self.search_result("tampered")], "user-1"), [])
        with self.assertRaises(ScreeningConflictError):
            access.assert_document_chunks_available([self.search_result()], "document-1", user_id="user-1")

    def test_historical_version_cannot_borrow_a_current_approval(self):
        with self.assertRaises(ScreeningConflictError):
            access.assert_document_available({"document_id": "document-1", "version": 1}, "user-1")

    def test_held_metadata_is_status_only_and_dai_projection_is_refreshed(self):
        stale = deepcopy(self.document)
        del stale["content_screening"]
        self.document["private_findings"] = ["PRIVATE EVIDENCE"]
        self.hold()
        payload = access.public_documents_payload([stale], "user-1")[0]
        self.assertEqual(payload["content_screening"]["state"], "pending_review")
        self.assertFalse(payload["content_screening"]["available"])
        for field in ("abstract", "title", "keywords", "authors", "blob_path", "private_findings"):
            self.assertNotIn(field, payload)
        self.assertNotIn("canonical_ref", payload["content_screening"])

    def test_mutations_reject_nested_and_camel_case_state_fields(self):
        for payload in (
            {"content_screening": None}, {"metadata": {"contentScreening": {"state": "cleared"}}},
            {"availability_generation": 10}, {"patch": [{"screening_state": "cleared"}]},
            {"scan_id": "forged"}, {"content_fingerprint": "forged"}, {"active_blob": {}},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ScreeningValidationError):
                    access.reject_screening_fields(payload)
        access.reject_screening_fields({"title": "The phrase content_screening is ordinary text"})

    def test_active_manifest_is_the_only_download_source(self):
        document, content = access.read_available_document_bytes("document-1", user_id="user-1")
        self.assertEqual(content, self.content)
        self.assertEqual(self.blob_requests, [("user-documents", document["content_screening"]["active_blob"]["path"])])
        del self.document["content_screening"]["active_blob"]
        with self.assertRaises(DocumentHeldError):
            access.read_available_document_bytes("document-1", user_id="user-1")
        self.assertEqual(len(self.blob_requests), 1)

    def test_hold_during_download_suppresses_the_bytes(self):
        self.after_blob_read = self.hold
        with self.assertRaises(DocumentHeldError):
            access.read_available_document_bytes("document-1", user_id="user-1")

    def test_private_container_and_nonactive_original_are_never_native_sources(self):
        for blob_name in ("original", "reviewed.txt", "report.csv", "safe.xlsx", "nested/preview.png"):
            with self.subTest(blob_name=blob_name):
                with self.assertRaises(DocumentHeldError):
                    access.assert_blob_available("content-screening", blob_name, user_id="user-1")
        with self.assertRaises(DocumentHeldError):
            access.assert_blob_available("user-documents", "user-1/original.txt", user_id="user-1")

    def test_workspace_linked_chat_source_maps_to_active_derivative(self):
        self.messages.documents["file-1"] = {
            "workspace_document_id": "document-1",
            "blob_path": "user-1/conversation-1/original.txt",
            "blob_container": "personal-chat",
        }
        resolved = access.resolve_available_blob_location(
            "personal-chat", "user-1/conversation-1/original.txt", user_id="user-1",
        )
        self.assertEqual(resolved[1], self.document["content_screening"]["active_blob"]["path"])
        self.hold()
        with self.assertRaises(DocumentHeldError):
            access.resolve_available_blob_location(
                "personal-chat", "user-1/conversation-1/original.txt", user_id="user-1",
            )

    def test_model_checks_reused_evidence_before_and_after_each_call(self):
        evidence = {access.PROVENANCE_FIELD: access.document_provenance(self.document)}
        invocations = []

        def invoke():
            invocations.append(True)
            self.hold()
            return "must never reach the caller"

        guarded = access.guard_model_callable(invoke, evidence, "user-1")
        with self.assertRaises(DocumentHeldError):
            guarded()
        with self.assertRaises(DocumentHeldError):
            guarded()
        self.assertEqual(len(invocations), 1)

    def test_unversioned_historical_context_cannot_borrow_a_new_clearance(self):
        with self.assertRaises(ScreeningConflictError):
            access.assert_evidence_available({"document_id": "document-1"}, "user-1", cached=True)
        access.assert_evidence_available(
            {
                "document_ids": ["document-1"],
                "screening_sources": [{access.PROVENANCE_FIELD: access.document_provenance(self.document)}],
            },
            "user-1", cached=True,
        )

    def test_internal_native_staging_is_not_an_ordinary_blob_tool_source(self):
        with self.assertRaises(DocumentHeldError):
            access.assert_blob_available(
                "personal-chat", "user-1/conversation-1/generated/tabular_runs/run-1/input/rows.json",
                user_id="user-1",
            )

    def test_caught_explicit_hold_cannot_fall_back_to_model_knowledge(self):
        self.hold()
        with self.app.test_request_context():
            try:
                access.assert_document_available("document-1", user_id="user-1")
            except DocumentHeldError:
                pass
            with self.assertRaises(DocumentHeldError):
                access.assert_current_request_sources_available()

    def test_sk_automatic_tool_continuations_recheck_the_source(self):
        evidence = {access.PROVENANCE_FIELD: access.document_provenance(self.document)}
        calls = []

        class Service:
            async def _inner_get_chat_message_contents(inner_self, *_args):
                calls.append(True)
                self.hold()
                return "not released"

        service = access.guard_chat_service(
            Service(), source_validator=lambda: access.assert_evidence_available(evidence, "user-1"),
        )
        with self.assertRaises(DocumentHeldError):
            asyncio.run(service._inner_get_chat_message_contents())
        with self.assertRaises(DocumentHeldError):
            asyncio.run(service._inner_get_chat_message_contents())
        self.assertEqual(len(calls), 1)


class BlobLocationRevisionTests(ScreeningAccessFixture):
    """A shared file name must never resolve a stored location to another revision."""

    MISSING = object()

    def setUp(self):
        super().setUp()
        self.documents.clear()

    def revision(self, document_id, version, *, current=MISSING, blob_path=None, archived_blob_path=None, **changes):
        row = {
            "id": document_id, "user_id": "user-1", "file_name": "report.csv", "version": version,
            "revision_family_id": "family-1", "blob_container": "user-documents", **changes,
        }
        if current is not self.MISSING:
            row["is_current_version"] = current
        if blob_path:
            row["blob_path"] = blob_path
        if archived_blob_path:
            row["archived_blob_path"] = archived_blob_path
        self.documents[document_id] = row
        return row

    def resolve(self, path, container="user-documents"):
        return access.assert_blob_available(container, path, user_id="user-1")["id"]

    def test_current_alias_is_not_claimed_by_an_archived_same_name_revision(self):
        # The archived row is returned first, as the production query did.
        archived = "user-1/family-1/revision-1/report.csv"
        self.revision(
            "revision-1", 1, current=False, blob_path=archived, archived_blob_path=archived,
            blob_path_mode="archived_revision",
        )
        self.revision("revision-2", 2, current=True, blob_path="user-1/report.csv")
        self.assertEqual(self.resolve("user-1/report.csv"), "revision-2")
        self.assertEqual(self.resolve(archived), "revision-1")

    def test_promoted_revision_owns_the_alias_and_keeps_its_archived_path(self):
        own_archive = "user-1/family-1/revision-1/report.csv"
        newer_archive = "user-1/family-1/revision-2/report.csv"
        self.revision("revision-2", 2, current=False, blob_path=newer_archive, archived_blob_path=newer_archive)
        self.revision(
            "revision-1", 1, current=True, blob_path="user-1/report.csv", archived_blob_path=own_archive,
        )
        self.assertEqual(self.resolve("user-1/report.csv"), "revision-1")
        self.assertEqual(self.resolve(own_archive), "revision-1")
        self.assertEqual(self.resolve(newer_archive), "revision-2")

    def test_archived_revision_alone_cannot_claim_the_current_alias(self):
        archived = "user-1/family-1/revision-1/report.csv"
        self.revision("revision-1", 1, current=False, blob_path=archived, archived_blob_path=archived)
        with self.assertRaises(DocumentHeldError):
            access.assert_blob_available("user-documents", "user-1/report.csv", user_id="user-1")

    def test_legacy_rows_without_stored_paths_keep_resolving(self):
        self.revision("legacy-1", 1)
        self.assertEqual(self.resolve("user-1/report.csv"), "legacy-1")
        self.revision("legacy-2", 2, blob_path="user-1/family-1/legacy-2/report.csv")
        self.assertEqual(self.resolve("user-1/report.csv"), "legacy-1")

    def test_unarchived_older_revision_sharing_the_alias_yields_to_the_current_one(self):
        self.revision("revision-1", 1, current=False, blob_path="user-1/report.csv")
        self.revision("revision-2", 2, current=True, blob_path="user-1/report.csv")
        self.assertEqual(self.resolve("user-1/report.csv"), "revision-2")

    def test_unnormalized_legacy_family_resolves_the_newest_revision(self):
        self.revision("legacy-2", 2, upload_date="2024-02-01T00:00:00")
        self.revision("legacy-1", 1, upload_date="2024-01-01T00:00:00")
        self.assertEqual(self.resolve("user-1/report.csv"), "legacy-2")

    def test_indistinguishable_owners_of_one_location_are_denied(self):
        self.revision("revision-a", 1, current=True, blob_path="user-1/report.csv", revision_family_id="family-a")
        self.revision("revision-b", 1, current=True, blob_path="user-1/report.csv", revision_family_id="family-b")
        with self.assertRaises(DocumentHeldError):
            access.assert_blob_available("user-documents", "user-1/report.csv", user_id="user-1")

    def test_group_revisions_use_the_group_scope(self):
        archived = "group-1/family-1/revision-1/report.csv"
        for row in (
            self.revision("revision-1", 1, current=False, blob_path=archived, archived_blob_path=archived),
            self.revision("revision-2", 2, current=True, blob_path="group-1/report.csv"),
        ):
            row["group_id"] = "group-1"
            row["blob_container"] = "group-documents"
            self.groups.documents[row["id"]] = self.documents.pop(row["id"])
        self.assertEqual(self.resolve("group-1/report.csv", "group-documents"), "revision-2")
        self.assertEqual(self.resolve(archived, "group-documents"), "revision-1")


class DocumentApiBoundaryTests(ScreeningAccessFixture):
    def make_blueprint(self):
        blueprint = Blueprint("screening_test", __name__)
        access.register_document_api_guards(blueprint, user_resolver=lambda: "user-1")
        return blueprint

    def test_listing_is_safe_and_mutation_cannot_write_server_state(self):
        stale = deepcopy(self.document)
        del stale["content_screening"]
        blueprint = self.make_blueprint()
        writes = []
        blueprint.add_url_rule("/documents", endpoint="documents", view_func=lambda: jsonify({"documents": [stale]}))
        blueprint.add_url_rule(
            "/mutation", endpoint="mutation", view_func=lambda: (writes.append(True) or jsonify({"ok": True})), methods=["PATCH"],
        )
        self.app.register_blueprint(blueprint)
        self.hold()
        client = Client(self.app, Response)
        response = client.get("/documents")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("abstract", response.json["documents"][0])
        self.assertIn("no-store", response.headers["Cache-Control"])
        response = client.patch("/mutation", json={"content_screening": {"state": "cleared"}})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(writes, [])

    def test_response_recheck_suppresses_in_flight_content(self):
        blueprint = self.make_blueprint()

        def download():
            access.assert_document_available("document-1", user_id="user-1")
            self.hold()
            return Response(b"PRIVATE ORIGINAL")

        blueprint.add_url_rule("/download", view_func=download)
        self.app.register_blueprint(blueprint)
        response = Client(self.app, Response).get("/download")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["error_code"], "document_under_review")
        self.assertNotIn(b"PRIVATE ORIGINAL", response.data)
        self.assertIn("no-store", response.headers["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
