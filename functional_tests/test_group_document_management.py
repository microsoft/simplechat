# test_group_document_management.py
"""
Functional tests for immutable-target group document management.
Version: 0.261.168
Implemented in: 0.261.129
A tag vocabulary conflict answers one coded sentence, from the pre-check or a lost patch: 0.261.166
New tags are defined before any document carries them, so a conflict writes no document: 0.261.168

Real Flask routes, management/access/policy modules, conditional document writes,
revision deletion and canonical downloads run against isolated storage, queues,
search and provider seams. No Azure writes, model calls or deployment occur.
"""

import ast
import importlib
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
from io import BytesIO
import json
import logging
import mimetypes
import os
from pathlib import Path
import sys
import tempfile
import traceback
from types import SimpleNamespace
from unittest.mock import Mock
import uuid
import zipfile

import pytest
from azure.cosmos.exceptions import CosmosAccessConditionFailedError
from flask import jsonify, make_response
from werkzeug.utils import secure_filename

from test_group_document_read_apis import (
    MissingRecord,
    ReadOnlyContainer,
    document,
    environment,
    get,
)
from test_support.agent_delegation import APP_ROOT, execute_functions
from test_support.versioning import assert_app_version_at_least


ROOT = "/api/groups/group-a/documents"


class StoreFailure(Exception):
    def __init__(self, status_code=500):
        self.status_code = status_code
        super().__init__("PRIVATE-PROVIDER-DIAGNOSTIC")


class MutableContainer(ReadOnlyContainer):
    def __init__(self, records):
        super().__init__(records)
        self.writes = []
        self.attempts = []
        self.before_write = None
        self.serial = 0

    def query_items(self, query, parameters=None, **kwargs):
        result = super().query_items(query, parameters, **kwargs)
        values = {item["name"]: item["value"] for item in parameters or []}
        if "COUNT(1)" in query:
            return result
        for parameter, field in (("@document_id", "id"), ("@file_name", "file_name")):
            if parameter in values:
                result = [item for item in result if item.get(field) == values[parameter]]
        return result

    def change(self, item, **changes):
        self.serial += 1
        self.records[item] = {**deepcopy(self.records[item]), **changes, "_etag": f"etag-{item}-{self.serial}"}

    def _before(self, operation, item, body=None):
        self.attempts.append((operation, item, deepcopy(body)))
        if self.before_write:
            self.before_write(operation, item, body)
        if self.failure:
            raise self.failure

    def _save(self, operation, item, body):
        self.serial += 1
        saved = {**deepcopy(body), "_etag": f"etag-{item}-{self.serial}"}
        self.records[item] = saved
        self.writes.append((operation, item, deepcopy(saved)))
        return deepcopy(saved)

    def replace_item(self, item, body, *, etag, match_condition):
        self._before("replace", item, body)
        if item not in self.records:
            raise MissingRecord()
        if self.records[item].get("_etag") != etag:
            raise StoreFailure(412)
        return self._save("replace", item, body)

    def upsert_item(self, body):
        self._before("upsert", body["id"], body)
        return self._save("upsert", body["id"], body)

    def create_item(self, body):
        self._before("create", body["id"], body)
        if body["id"] in self.records:
            raise StoreFailure(409)
        return self._save("create", body["id"], body)

    def delete_item(self, item, partition_key, **kwargs):
        self._before("delete", item)
        if item not in self.records:
            raise MissingRecord()
        if kwargs.get("etag") is not None and kwargs["etag"] != self.records[item].get("_etag"):
            raise StoreFailure(412)
        del self.records[item]
        self.writes.append(("delete", item, None))

    def patch_item(self, item, partition_key, patch_operations, filter_predicate):
        self._before("patch", item, patch_operations)
        expected = json.loads(filter_predicate.split(" = ", 1)[1])
        if self.records[item].get("_etag") != expected:
            # What the SDK raises when the service answers a failed filter predicate with 412
            # (test_group_document_sdk_conditions.py pins that against the real pipeline).
            raise CosmosAccessConditionFailedError(status_code=412, message="PRIVATE-PROVIDER-DIAGNOSTIC")
        updated = deepcopy(self.records[item])
        for operation in patch_operations:
            parts = [part.replace("~1", "/").replace("~0", "~") for part in operation["path"].split("/")[1:]]
            parent = updated
            for part in parts[:-1]:
                parent = parent[part]
            if operation["op"] == "remove":
                parent.pop(parts[-1])
            else:
                parent[parts[-1]] = deepcopy(operation["value"])
        return self._save("patch", item, updated)


class BlobStore:
    def __init__(self):
        self.records = {}
        self.probes = []
        self.downloads = []
        self.metadata_writes = []
        self.deleted = []
        self.after_download = None
        self.metadata_failure = None
        self.delete_failure = None

    def put(self, path, content=b"source bytes", container="group-documents"):
        self.records[(container, path)] = {"content": content, "etag": f"blob-{path}", "metadata": {"keep": "value"}}

    def get_blob_client(self, container, blob):
        key = (container, blob)

        def exists():
            self.probes.append(key)
            return key in self.records

        def download_blob(**kwargs):
            self.downloads.append(key)
            if key not in self.records:
                raise MissingRecord()
            if kwargs.get("etag") and kwargs["etag"] != self.records[key]["etag"]:
                raise StoreFailure(412)

            def readall():
                content = self.records[key]["content"]
                if self.after_download:
                    self.after_download()
                return content

            return SimpleNamespace(readall=readall, chunks=lambda: iter([readall()]))

        def set_blob_metadata(metadata, **kwargs):
            if self.metadata_failure:
                raise self.metadata_failure
            if kwargs.get("etag") != self.records[key]["etag"]:
                raise StoreFailure(412)
            self.records[key]["metadata"] = deepcopy(metadata)
            self.metadata_writes.append((key, deepcopy(metadata)))

        def properties():
            if key not in self.records:
                raise MissingRecord()
            return SimpleNamespace(etag=self.records[key]["etag"], metadata=deepcopy(self.records[key]["metadata"]))

        def delete_blob(**kwargs):
            if self.delete_failure:
                raise self.delete_failure
            if kwargs.get("etag") is not None and kwargs["etag"] != self.records[key]["etag"]:
                raise StoreFailure(412)
            del self.records[key]
            self.deleted.append(key)

        return SimpleNamespace(
            exists=exists, download_blob=download_blob,
            get_blob_properties=properties, delete_blob=delete_blob,
            set_blob_metadata=set_blob_metadata,
        )


class Queue:
    def __init__(self):
        self.jobs = []
        self.failure = None

    def submit_stored(self, key, function, **kwargs):
        if self.failure:
            raise self.failure
        self.jobs.append((key, function, kwargs))
        return SimpleNamespace()


@pytest.fixture
def management(environment):
    env = environment
    patch = env.scoped_monkeypatch
    env.settings.update({
        "enable_extract_meta_data": True, "enable_enhanced_extraction": True,
        "enable_enhanced_citations": True, "max_file_size_mb": 1,
    })
    env.source = MutableContainer(env.source.records)
    env.group_container = MutableContainer(env.groups)
    env.blobs = BlobStore()
    for record in env.source.records.values():
        record.update(blob_container="group-documents", blob_path=f"{record['group_id']}/{record['file_name']}")
        env.blobs.put(record["blob_path"])
    env.queue = Queue()
    env.app.extensions["executor"] = env.queue
    with env.client.session_transaction() as state:
        state["user"] = {"oid": "owner", "roles": ["User"]}
    env.user_settings.reset_mock()
    for module in (env.config, env.real_groups, env.group_access, env.management, env.helper):
        if hasattr(module, "cosmos_group_documents_container"):
            patch.setattr(module, "cosmos_group_documents_container", env.source)
        if hasattr(module, "cosmos_groups_container"):
            patch.setattr(module, "cosmos_groups_container", env.group_container)
    clients = {"storage_account_office_docs_client": env.blobs}
    patch.setattr(env.config, "CLIENTS", clients, raising=False)
    env.chunk_writes = []
    env.deleted_chunks = []
    env.visibility = []
    env.index_updates = Mock(return_value={"success": True})
    env.index_deletes = Mock(return_value={"success": True})

    def chunk_update(**kwargs):
        env.chunk_writes.append(deepcopy(kwargs))

    def metadata_rescan(document_item, updates, actor_id):
        current = env.source.read_item(document_item["id"], document_item["id"])
        changed = {**current, **updates, SCREENING_FIELD: {
            **current[SCREENING_FIELD], "state": "pending_scan", "scan_id": f"rescan-{current['id']}",
        }}
        return env.source.replace_item(
            current["id"], changed, etag=document_item["_etag"], match_condition="match",
        )

    def prepare_delete(document_item, actor_id):
        marker = {**document_item[SCREENING_FIELD], "state": "deleting"}
        env.source.change(document_item["id"], content_screening=marker)
        env.scans.records[marker["scan_id"]]["state"] = "deleting"

    # The application modules are loaded only after the base fixture's network
    # and bootstrap seams are active; real shared mutation definitions run below.
    from content_screening.contracts import (
        CONTENT_METADATA_FIELDS, SCREENING_FIELD, DocumentHeldError, ScreeningConflictError,
        ScreeningError, ScreeningValidationError, document_is_available, require_document_available,
        subject_from_document,
    )

    namespace = env.document_helpers
    namespace.update({
        "os": os, "json": json, "datetime": datetime, "timezone": timezone,
        "tempfile": tempfile, "uuid": uuid, "traceback": traceback, "logging": logging,
        "partial": partial, "mimetypes": mimetypes, "BytesIO": BytesIO, "zipfile": zipfile,
        "make_response": make_response, "jsonify": jsonify, "secure_filename": secure_filename,
        "CLIENTS": clients, "get_settings": lambda: env.settings, "log_event": env.logs,
        "cosmos_group_documents_container": env.source,
        "cosmos_user_documents_container": env.personal, "cosmos_public_documents_container": ReadOnlyContainer(),
        "MatchConditions": env.index.MatchConditions, "CosmosResourceNotFoundError": MissingRecord,
        "SCREENING_FIELD": SCREENING_FIELD, "ScreeningConflictError": ScreeningConflictError,
        "ScreeningError": ScreeningError, "ScreeningValidationError": ScreeningValidationError,
        "DocumentHeldError": DocumentHeldError, "document_is_available": document_is_available,
        "require_document_available": require_document_available, "subject_from_document": subject_from_document,
        "CONTENT_METADATA_FIELDS": CONTENT_METADATA_FIELDS,
        "public_document_payload": env.access.public_document_payload,
        "read_available_document_bytes": env.access.read_available_document_bytes,
        "current_extraction": lambda _document_id: None, "is_publication": lambda *_args: False,
        "queue_metadata_rescan": metadata_rescan,
        "add_file_task_to_file_processing_log": Mock(),
        "calculate_processing_percentage": lambda item: item.get("percentage_complete", 0),
        "get_all_chunks": lambda document_id, user_id, group_id=None, public_workspace_id=None: [{"id": f"{document_id}-chunk"}],
        "update_chunk_metadata": chunk_update,
        "sync_document_access_index_for_document_fail_open": env.index_updates,
        "delete_document_access_index_for_document_fail_open": env.index_deletes,
        "delete_document_chunks": lambda document_id, **kwargs: env.deleted_chunks.append((document_id, kwargs)),
        "set_document_chunk_visibility": lambda item, active: env.visibility.append((item["id"], active)),
        "_promote_document_blob_to_current_alias": Mock(),
        "require_xsd_ingestion_capability": lambda *_args, **_kwargs: None,
        "initial_document_marker": lambda _item: None,
        "ALLOWED_EXTENSIONS": {"pdf", "png", "txt", "csv", "docx"},
        "prepare_document_deletion": prepare_delete,
        "assert_group_document_source_writable": importlib.import_module(
            "functions_group_document_projection_fence"
        ).assert_group_document_source_writable,
    })
    execute_functions("functions_documents.py", {
        "_get_blob_service_client", "_blob_exists", "_get_documents_container",
        "_upsert_document_and_sync_access_index", "update_document", "propagate_tags_to_blob_metadata",
        "get_document_metadata", "get_document_record", "get_document", "_build_carried_forward_metadata", "create_document",
        "delete_document", "delete_document_revision", "_get_document_family_items_from_document",
        "get_document_blob_delete_targets", "delete_from_blob_storage",
        "_sanitize_download_file_name", "_get_download_content_type", "_get_document_download_entry",
        "build_document_download_response", "build_documents_zip_download_response",
        "allowed_file", "ensure_list", "_update_document_for_job",
    }, namespace)
    for name in (
        "update_document", "create_document", "delete_document_revision", "allowed_file",
        "build_document_download_response", "build_documents_zip_download_response",
    ):
        patch.setattr(env.management, name, namespace[name])
        patch.setattr(env.route, name, namespace[name], raising=False)
    patch.setattr(env.group_access, "_blob_exists", namespace["_blob_exists"])
    patch.setattr(sys.modules["functions_documents"], "get_document_blob_storage_info", namespace["get_document_blob_storage_info"])
    patch.setattr(sys.modules["functions_documents"], "get_document", namespace["get_document"], raising=False)
    patch.setattr(env.group_access, "is_group_workspace_file_download_enabled",
                  lambda _settings, group: env.downloads and not group.get("disable_file_downloads", False))
    patch.setattr(env.management, "prepare_document_upload", Mock())
    patch.setattr(env.management, "log_document_metadata_update_transaction", Mock())
    patch.setattr(env.management, "invalidate_group_search_cache", Mock())
    env.sync_guard = Mock(return_value=None)
    env.sync_apply = Mock()
    patch.setattr(env.management, "build_synced_document_delete_guard", env.sync_guard)
    patch.setattr(env.management, "apply_synced_document_delete_action", env.sync_apply)
    env.process_upload = Mock()
    env.process_extract = Mock()
    env.process_reprocess = Mock()
    patch.setattr(env.management, "process_document_upload_background", env.process_upload)
    patch.setattr(env.management, "process_metadata_extraction_background", env.process_extract)
    patch.setattr(env.management, "process_document_reprocess_extraction_background", env.process_reprocess)
    yield env
    for _key, _function, kwargs in env.queue.jobs:
        if kwargs.get("temp_file_path"):
            Path(kwargs["temp_file_path"]).unlink(missing_ok=True)


def invoke(env, operation):
    if operation == "upload":
        return env.client.post(f"{ROOT}/upload", data={"file": (BytesIO(b"%PDF test file"), "fresh.pdf")})
    if operation == "edit_metadata":
        return env.client.patch(f"{ROOT}/document-a", json={"title": "Changed title"})
    if operation == "delete":
        return env.client.delete(f"{ROOT}/document-a?delete_mode=current_only")
    if operation == "bulk_delete":
        return env.client.post(f"{ROOT}/bulk-delete", json={"document_ids": ["document-a"], "delete_mode": "current_only"})
    if operation == "download":
        return env.client.get(f"{ROOT}/document-a/download")
    if operation == "batch_download":
        return env.client.post(f"{ROOT}/download", json={"document_ids": ["document-a"]})
    if operation == "extract_metadata":
        return env.client.post(f"{ROOT}/extract_metadata", json={"document_ids": ["document-a"]})
    if operation == "reprocess":
        return env.client.post(f"{ROOT}/reprocess_extraction", json={"document_ids": ["document-a"], "extraction_mode": "read"})
    if operation == "create_tag":
        return env.client.post(f"{ROOT}/tags", json={"tag_name": "new-tag", "color": "#abc"})
    if operation == "rename_tag":
        return env.client.patch(f"{ROOT}/tags/reference", json={"new_name": "renamed"})
    if operation == "recolour_tag":
        return env.client.patch(f"{ROOT}/tags/reference", json={"color": "#123456"})
    if operation == "delete_tag":
        return env.client.delete(f"{ROOT}/tags/reference")
    if operation == "tag_documents":
        return env.client.post(f"{ROOT}/bulk-tag", json={"document_ids": ["document-a"], "action": "add_tags", "tags": ["new-tag"]})
    raise AssertionError(operation)


OPERATIONS = (
    "upload", "edit_metadata", "delete", "bulk_delete", "download", "batch_download",
    "extract_metadata", "reprocess", "create_tag", "rename_tag", "recolour_tag", "delete_tag", "tag_documents",
)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_successful_operations_use_the_path_not_active_preferences(management, operation):
    env = management
    before_other = deepcopy(env.source.records["document-b"])
    response = invoke(env, operation)
    assert response.status_code in {200, 201, 202}, response.get_data(as_text=True)
    assert env.source.records["document-b"] == before_other
    env.user_settings.assert_not_called()
    assert all(kwargs.get("group_id") == "group-a" for _key, _function, kwargs in env.queue.jobs)
    assert all(write.get("group_id") == "group-a" for write in env.chunk_writes)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("status", ["locked", "upload_disabled", "inactive", "unknown"])
def test_every_operation_respects_group_status(management, operation, status):
    env = management
    env.groups["group-a"]["status"] = status
    response = invoke(env, operation)
    permitted = operation in {"download", "batch_download"} and status in {"locked", "upload_disabled"}
    permitted = permitted or status == "upload_disabled" and operation in {"delete", "bulk_delete", "reprocess"}
    if permitted:
        assert response.status_code in {200, 202}, response.get_data(as_text=True)
    else:
        assert response.status_code == 403, response.get_data(as_text=True)
        assert env.source.writes == []
        assert env.group_container.writes == []
        assert env.queue.jobs == []
        assert env.blobs.downloads == []


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("actor", ["owner", "admin", "manager", "reader", "stranger"])
def test_every_operation_requires_a_current_content_manager(management, operation, actor):
    env = management
    with env.client.session_transaction() as state:
        state["user"] = {"oid": actor, "roles": ["User"]}
    response = invoke(env, operation)
    if actor in {"owner", "admin", "manager"}:
        assert response.status_code in {200, 201, 202}, response.get_data(as_text=True)
    else:
        assert response.status_code == 403
        assert not env.source.writes and not env.group_container.writes and not env.queue.jobs


def test_metadata_receipt_preserves_omitted_fields_and_source_identity(management):
    env = management
    before = deepcopy(env.source.records["document-a"])
    response = env.client.patch(f"{ROOT}/document-a", json={"title": "Renamed", "authors": ["Writer"]})
    body = response.get_json()
    stored = env.source.records["document-a"]
    assert response.status_code == 200
    assert body == {
        "message": "Group document metadata updated.", "document_id": "document-a", "group_id": "group-a",
        "updated_fields": ["authors", "title"], "status": "updated",
    }
    for field in ("user_id", "group_id", "id", "abstract", "tags", "keywords", "document_classification"):
        assert stored[field] == before[field]
    assert stored["title"] == "Renamed" and stored["authors"] == ["Writer"]


@pytest.mark.parametrize("payload", [
    {"title": "must not save", "tags": ["bad/tag"]},
    {"title": "must not save", "authors": [3]},
    {"title": "must not save", "keywords": {}},
    {"title": 3}, {"group_id": "group-b"}, {"user_id": "another"},
    {"blob_path": "group-b/private.pdf"}, {"document_actions": ["delete"]},
    {"settings": {}}, [], None, {},
])
def test_metadata_validates_the_whole_payload_before_side_effects(management, payload):
    env = management
    response = env.client.patch(f"{ROOT}/document-a", json=payload)
    assert response.status_code == 400
    assert env.source.writes == [] and env.chunk_writes == []
    assert env.group_container.writes == [] and env.blobs.metadata_writes == []
    env.index_updates.assert_not_called()


@pytest.mark.parametrize("race", ["changed", "deleted"])
def test_failed_source_cas_never_changes_projections_or_resurrects(management, race):
    env = management

    def race_after_snapshot():
        env.source.after_query = None
        if race == "changed":
            env.source.change("document-a", title="Concurrent winner")
        else:
            del env.source.records["document-a"]

    env.source.after_query = race_after_snapshot
    response = env.client.patch(f"{ROOT}/document-a", json={"title": "Rejected", "tags": ["new-tag"]})
    assert response.status_code in {404, 409}
    assert env.source.writes == []
    # The vocabulary is written before the document, so the lost document write leaves the new
    # tag's definition unused, which is a valid state; nothing else changes.
    assert [(operation, item) for operation, item, _body in env.group_container.writes] == [("patch", "group-a")]
    assert set(env.groups["group-a"]["tag_definitions"]) == {"unused", "reference", "new-tag"}
    assert env.chunk_writes == [] and env.blobs.metadata_writes == []
    env.index_updates.assert_not_called()
    if race == "changed":
        assert env.source.records["document-a"]["title"] == "Concurrent winner"
    else:
        assert "document-a" not in env.source.records


def test_chunk_failure_is_explicit_after_the_source_cas_and_retry_repairs(management):
    env = management
    calls = []

    def fail_chunk(**kwargs):
        calls.append(deepcopy(env.source.records["document-a"]))
        raise StoreFailure()

    env.document_helpers["update_chunk_metadata"] = fail_chunk
    failed = env.client.patch(f"{ROOT}/document-a", json={"title": "Saved title"})
    assert failed.status_code == 500
    assert failed.get_json()["error"] == "document_propagation_incomplete"
    assert failed.get_json()["repair_required"] is True
    assert calls[0]["title"] == "Saved title"
    assert "PRIVATE-PROVIDER" not in failed.get_data(as_text=True)
    repaired = Mock()
    env.document_helpers["update_chunk_metadata"] = repaired
    retried = env.client.patch(f"{ROOT}/document-a", json={"title": "Saved title"})
    assert retried.status_code == 200
    repaired.assert_called_once()


@pytest.mark.parametrize("failure", ["index", "blob"])
def test_required_projection_failure_never_returns_an_updated_receipt(management, failure):
    env = management
    if failure == "index":
        env.index_updates.return_value = {"success": False}
    else:
        env.blobs.metadata_failure = StoreFailure()
    response = env.client.patch(f"{ROOT}/document-a", json={"tags": ["changed"]})
    assert response.status_code == 500
    assert response.get_json()["error"] == "document_propagation_incomplete"
    assert "status" not in response.get_json()
    assert env.source.records["document-a"]["tags"] == ["changed"]


def test_metadata_rescan_has_a_bound_queued_receipt(management):
    env = management
    env.settings["enable_content_screening"] = True
    env.seed_release(env.source.records["document-a"])
    response = env.client.patch(f"{ROOT}/document-a", json={"abstract": "Updated abstract"})
    assert response.status_code == 202, response.get_json()
    assert response.get_json()["status"] == "queued"
    assert response.get_json()["document_id"] == "document-a"
    assert response.get_json()["group_id"] == "group-a"
    assert response.get_json()["updated_fields"] == ["abstract"]
    assert env.source.records["document-a"]["content_screening"]["state"] == "pending_scan"


def test_incoming_download_uses_source_bytes_with_same_name_in_recipient(management):
    env = management
    env.source.records["shared"] = document(
        "shared", "source-group", file_name="same.pdf", shared_group_ids=["group-a,approved"],
    )
    env.blobs.put("source-group/same.pdf", b"SOURCE")
    env.blobs.put("group-a/same.pdf", b"WRONG RECIPIENT")
    env.groups["source-group"]["owner"] = {"id": "another-owner"}
    env.groups["source-group"]["admins"] = []
    env.groups["source-group"]["documentManagers"] = []
    response = env.client.get(f"{ROOT}/shared/download")
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.data == b"SOURCE"
    assert env.blobs.downloads == [("group-documents", "source-group/same.pdf")]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response.headers["Cache-Control"]


def test_download_cannot_fall_back_to_recipient_or_survive_revocation(management):
    env = management
    env.source.records["shared"] = document(
        "shared", "source-group", file_name="same.pdf", shared_group_ids=["group-a,approved"],
    )
    env.blobs.put("group-a/same.pdf", b"WRONG")
    missing = env.client.get(f"{ROOT}/shared/download")
    assert missing.status_code == 409
    assert env.blobs.downloads == []
    env.blobs.put("source-group/same.pdf", b"SOURCE")
    env.blobs.after_download = lambda: env.source.records["shared"].update(shared_group_ids=["group-b,approved"])
    revoked = env.client.get(f"{ROOT}/shared/download")
    assert revoked.status_code in {403, 404, 409}
    assert b"SOURCE" not in revoked.data
    assert all(path != "group-a/same.pdf" for _container, path in env.blobs.downloads)


def test_download_requires_both_workspace_policies_and_all_batch_members(management):
    env = management
    env.source.records["shared"] = document(
        "shared", "source-group", shared_group_ids=["group-a,approved"], blob_path="source-group/shared.pdf",
    )
    env.blobs.put("source-group/shared.pdf")
    env.groups["source-group"]["disable_file_downloads"] = True
    denied_source = env.client.get(f"{ROOT}/shared/download")
    mixed = env.client.post(f"{ROOT}/download", json={"document_ids": ["document-a", "document-b"]})
    assert denied_source.status_code == 409
    assert mixed.status_code == 404
    assert env.blobs.downloads == []


def test_actions_are_fresh_and_only_outgoing_records_probe_blobs(management):
    env = management
    for number in range(60):
        env.source.records[f"extra-{number}"] = document(f"extra-{number}", document_actions=["approve", "share"])
    facets = get(env, "/api/group_documents/facets")
    tags = get(env, "/api/group_documents/tags")
    assert facets.status_code == 200 and tags.status_code == 200
    assert env.blobs.probes == []
    listed = get(env, page_size=2)
    assert listed.status_code == 200
    assert len(env.blobs.probes) == 2
    assert all("share" not in row["document_actions"] for row in listed.get_json()["documents"])
    with env.client.session_transaction() as state:
        state["user"] = {"oid": "reader", "roles": ["User"]}
    env.blobs.probes.clear()
    reader = get(env, page_size=2)
    assert all(row["document_actions"] == [] for row in reader.get_json()["documents"])
    assert env.blobs.probes == []


@pytest.mark.parametrize("path", [
    "/api/group_documents", "/api/group_documents/document-a", "/api/group_documents/document-a/versions",
])
@pytest.mark.parametrize("with_flag", [True, False])
def test_pending_artifact_content_stays_restricted_without_a_screening_marker(management, path, with_flag):
    env = management
    pending = env.source.records["document-a"]
    pending.update(
        status="Pending approval", title="PRIVATE EXTRACTED", abstract="PRIVATE EXTRACTED",
        tags=["PRIVATE EXTRACTED"], generated_artifact_requested_by_user_id="requester",
    )
    if with_flag:
        pending["generated_artifact_promotion_status"] = "pending_approval"
    response = get(env, path)
    body = response.get_json()
    rows = body.get("documents") or body.get("versions") or [body]
    assert response.status_code == 200
    assert "PRIVATE EXTRACTED" not in response.get_data(as_text=True)
    for row in rows:
        assert row["shared_approval_status"] == "owner"
        assert row["generated_artifact_promotion_status"] == "pending_approval"
        assert row["generated_artifact_requested_by_user_id"] == "requester"
        assert row["document_actions"] == []
        assert "blob_path" not in row
    assert env.blobs.probes == []


def test_tag_persistence_is_conditional_and_never_overwrites_other_group_fields(management):
    env = management
    before = deepcopy(env.groups["group-a"])

    def concurrent_tag(operation, item, body):
        env.group_container.before_write = None
        definitions = {**env.groups[item]["tag_definitions"], "concurrent": {"color": "#ffffff"}}
        env.group_container.change(item, tag_definitions=definitions, users=[{"userId": "new-member"}])

    env.group_container.before_write = concurrent_tag
    rejected = env.client.post(f"{ROOT}/tags", json={"tag_name": "new-tag"})
    assert rejected.status_code == 409
    assert "concurrent" in env.groups["group-a"]["tag_definitions"]
    assert "new-tag" not in env.groups["group-a"]["tag_definitions"]
    assert env.groups["group-a"]["users"] == [{"userId": "new-member"}]
    assert env.groups["group-a"]["owner"] == before["owner"]
    assert env.group_container.writes == []


VOCABULARY_CONFLICT = {
    "error": "The group's tags or permissions changed. Refresh and retry.",
    "error_code": "vocabulary_conflict",
}


def lose_the_vocabulary_patch(env, *, removing=False):
    """A group write lands between the vocabulary pre-check and the conditional patch it guards.

    With ``removing``, only the cleanup patch that removes an old name loses; any patch before it
    lands.
    """

    def concurrent_group_write(operation, item, body):
        if operation == "patch" and (not removing or any(entry["op"] == "remove" for entry in body)):
            env.group_container.before_write = None
            env.group_container.change(item, users=[{"userId": "new-member"}])

    env.group_container.before_write = concurrent_group_write


@pytest.mark.parametrize("check", ["pre_check", "lost_patch"])
def test_either_vocabulary_check_raises_the_one_coded_conflict_and_writes_nothing(management, check):
    env = management
    snapshot = deepcopy(env.groups["group-a"])
    if check == "pre_check":
        env.group_container.change("group-a", users=[{"userId": "new-member"}])
    else:
        lose_the_vocabulary_patch(env)
    with pytest.raises(env.management.GroupDocumentOperationError) as failure:
        env.management._patch_tag_definitions("owner", "group-a", snapshot, {"new-tag": {"color": "#abcdef"}})
    assert failure.value.code == 409
    assert failure.value.payload == VOCABULARY_CONFLICT
    assert [attempt[0] for attempt in env.group_container.attempts] == ([] if check == "pre_check" else ["patch"])
    assert env.group_container.writes == []
    assert env.groups["group-a"]["tag_definitions"] == snapshot["tag_definitions"]
    assert env.groups["group-a"]["users"] == [{"userId": "new-member"}]


@pytest.mark.parametrize("operation", ["create_tag", "recolour_tag", "rename_tag"])
def test_a_lost_vocabulary_patch_answers_the_coded_conflict_and_writes_nothing(management, operation):
    env = management
    definitions = deepcopy(env.groups["group-a"]["tag_definitions"])
    documents = deepcopy(env.source.records)
    lose_the_vocabulary_patch(env)
    response = invoke(env, operation)
    assert response.status_code == 409
    assert response.get_json() == {**VOCABULARY_CONFLICT, "group_id": "group-a"}
    assert "PRIVATE-PROVIDER" not in response.get_data(as_text=True)
    assert [attempt[0] for attempt in env.group_container.attempts] == ["patch"]
    assert env.group_container.writes == []
    assert env.groups["group-a"]["tag_definitions"] == definitions
    assert env.groups["group-a"]["users"] == [{"userId": "new-member"}]
    assert env.source.writes == [] and env.source.records == documents


@pytest.mark.parametrize("operation", ["rename_tag", "delete_tag"])
def test_a_lost_vocabulary_cleanup_keeps_the_old_name_and_reports_the_coded_conflict(management, operation):
    env = management
    lose_the_vocabulary_patch(env, removing=True)
    response = invoke(env, operation)
    body = response.get_json()
    assert response.status_code == 207
    assert body["vocabulary_retained"] is True
    assert body["success"] == [{"document_id": "document-a", "tags": ["renamed"] if operation == "rename_tag" else []}]
    assert body["errors"] == [{
        "stage": "vocabulary", "group_id": "group-a",
        "error": VOCABULARY_CONFLICT["error_code"], "message": VOCABULARY_CONFLICT["error"],
    }]
    assert "PRIVATE-PROVIDER" not in response.get_data(as_text=True)
    assert "reference" in env.groups["group-a"]["tag_definitions"]
    assert env.groups["group-a"]["users"] == [{"userId": "new-member"}]


def test_a_lost_vocabulary_patch_refuses_the_metadata_save_and_writes_no_document(management):
    env = management
    before = deepcopy(env.source.records["document-a"])
    lose_the_vocabulary_patch(env)
    response = env.client.patch(f"{ROOT}/document-a", json={"title": "Refused title", "tags": ["brand-new"]})
    assert response.status_code == 409
    assert response.get_json() == {**VOCABULARY_CONFLICT, "document_id": "document-a", "group_id": "group-a"}
    assert env.source.writes == [] and env.source.records["document-a"] == before
    assert env.chunk_writes == [] and env.blobs.metadata_writes == []
    assert "brand-new" not in env.groups["group-a"]["tag_definitions"]


def add_group_document(env, identifier):
    record = document(identifier)
    record.update(blob_container="group-documents", blob_path=f"{record['group_id']}/{record['file_name']}")
    env.source.records[identifier] = record
    env.blobs.put(record["blob_path"])
    return record


def test_a_lost_vocabulary_patch_refuses_the_whole_tagging_batch_and_writes_no_document(management):
    env = management
    add_group_document(env, "document-c")
    before = deepcopy(env.source.records)
    lose_the_vocabulary_patch(env)
    response = env.client.post(f"{ROOT}/bulk-tag", json={
        "document_ids": ["document-a", "document-c"], "action": "add_tags", "tags": ["new-tag"],
    })
    assert response.status_code == 409
    assert response.get_json() == {**VOCABULARY_CONFLICT, "group_id": "group-a"}
    assert [attempt[0] for attempt in env.group_container.attempts] == ["patch"]
    assert env.source.writes == [] and env.source.records == before
    assert env.chunk_writes == [] and env.blobs.metadata_writes == []
    assert "new-tag" not in env.groups["group-a"]["tag_definitions"]


@pytest.mark.parametrize("route", ["metadata", "bulk"])
def test_new_tags_are_defined_before_any_document_carries_them(management, route):
    env = management
    add_group_document(env, "document-c")
    writes = []
    env.group_container.before_write = lambda operation, item, _body: writes.append(("group", operation, item))
    env.source.before_write = lambda operation, item, _body: writes.append(("document", operation, item))
    if route == "metadata":
        response = env.client.patch(f"{ROOT}/document-a", json={"tags": ["reference", "new-tag"]})
        tagged = ["document-a"]
    else:
        response = env.client.post(f"{ROOT}/bulk-tag", json={
            "document_ids": ["document-a", "document-c"], "action": "add_tags", "tags": ["new-tag"],
        })
        tagged = ["document-a", "document-c"]
    assert response.status_code == 200, response.get_json()
    # One vocabulary patch, and it lands before the first document write.
    assert writes[0] == ("group", "patch", "group-a")
    assert [entry for entry in writes if entry[0] == "group"] == [("group", "patch", "group-a")]
    assert {entry[2] for entry in writes if entry[0] == "document"} == set(tagged)
    assert "new-tag" in env.groups["group-a"]["tag_definitions"]
    for identifier in tagged:
        assert env.source.records[identifier]["tags"] == ["reference", "new-tag"]


def test_tag_rename_keeps_old_vocabulary_on_partial_propagation(management):
    env = management
    env.source.records["held"] = document(
        "held", content_screening={"state": "pending_review", "scan_id": "held", "source_revision": "1"},
    )
    env.source.records["historical"] = document(
        "historical", revision_family_id="document-a", version=0, is_current_version=False,
    )
    response = env.client.patch(f"{ROOT}/tags/reference", json={"new_name": "renamed", "color": "#f00"})
    body = response.get_json()
    assert response.status_code == 207
    assert body["vocabulary_retained"] is True
    assert body["documents_updated"] == 1
    assert body["success"] == [{"document_id": "document-a", "tags": ["renamed"]}]
    assert body["errors"][0]["document_id"] == "held"
    assert {"reference", "renamed"} <= set(env.groups["group-a"]["tag_definitions"])
    assert env.source.records["historical"]["tags"] == ["reference"]
    assert env.source.records["document-b"]["tags"] == ["reference"]


def test_legacy_tag_targets_with_slashes_remain_addressable(management):
    env = management
    env.groups["group-a"]["tag_definitions"]["legacy/team"] = {"color": "#123456"}
    env.source.records["document-a"]["tags"] = ["legacy/team"]
    recolour = env.client.patch(f"{ROOT}/tags/legacy%2Fteam", json={"color": "#fff"})
    deleted = env.client.delete(f"{ROOT}/tags/legacy%2Fteam")
    assert recolour.status_code == 200
    assert recolour.get_json()["tag"] == {"name": "legacy/team", "color": "#ffffff"}
    assert deleted.status_code == 200, deleted.get_json()
    assert "legacy/team" not in env.groups["group-a"]["tag_definitions"]
    assert env.source.records["document-a"]["tags"] == []


def test_duplicate_and_overlapping_family_deletes_report_requested_ids(management):
    env = management
    env.source.records["older"] = document(
        "older", revision_family_id="document-a", version=0, is_current_version=False,
        file_name="document-a.pdf",
    )
    response = env.client.post(f"{ROOT}/bulk-delete", json={
        "document_ids": ["document-a", "document-a", "older"], "delete_mode": "all_versions",
    })
    body = response.get_json()
    assert response.status_code == 200, body
    assert body["deleted"] == [{"document_id": "document-a"}, {"document_id": "older"}]
    assert body["deleted_count"] == 2 and body["error_count"] == 0
    assert "document-a" not in env.source.records and "older" not in env.source.records
    assert len(env.deleted_chunks) == 2


def test_delete_requires_explicit_intent_and_keeps_confirmation_details(management):
    env = management
    missing = env.client.delete(f"{ROOT}/document-a")
    force = env.client.delete(f"{ROOT}/document-a?delete_mode=all_versions&force=true")
    env.source.records["document-a"].update(created_from_chat_upload=True, conversation_id="conversation-a")
    guarded = env.client.delete(f"{ROOT}/document-a?delete_mode=current_only")
    assert missing.status_code == 400 and force.status_code == 400
    assert guarded.status_code == 409
    assert guarded.get_json()["needs_confirmation"] is True
    assert guarded.get_json()["error"] == "conversation_linked_document_delete_requires_confirmation"
    assert guarded.get_json()["document_id"] == "document-a"
    assert env.source.writes == []


def test_sync_choice_is_forwarded_without_a_force_bypass(management):
    env = management
    env.sync_guard.side_effect = lambda *_args, **kwargs: None if kwargs["requested_action"] else {
        "error": "synced_document_delete_requires_action", "message": "Choose an action.",
        "file_sync": {"source_id": "sync-a", "remote_path": "/document.pdf"},
        "options": [{"action": "delete_only", "label": "Delete copy"}, {"action": "ignore_remote", "label": "Ignore source"}],
    }
    guarded = env.client.post(f"{ROOT}/bulk-delete", json={"document_ids": ["document-a"], "delete_mode": "current_only"})
    assert guarded.status_code == 207
    assert guarded.get_json()["errors"][0]["needs_confirmation"] is True
    assert guarded.get_json()["errors"][0]["file_sync"]["source_id"] == "sync-a"
    approved = env.client.delete(f"{ROOT}/document-a?delete_mode=current_only&file_sync_delete_action=ignore_remote")
    assert approved.status_code == 200
    env.sync_apply.assert_called_once_with("group", "document-a", "owner", "ignore_remote", group_id="group-a")


@pytest.mark.parametrize("operation", ["upload", "extract_metadata", "reprocess"])
def test_queued_jobs_capture_target_and_revalidate_membership(management, operation):
    env = management
    response = invoke(env, operation)
    assert response.status_code in {200, 202}
    _key, worker, args = env.queue.jobs[0]
    env.active_group = "source-group"
    worker(**args)
    processor = {"upload": env.process_upload, "extract_metadata": env.process_extract, "reprocess": env.process_reprocess}[operation]
    assert processor.call_args.kwargs["group_id"] == "group-a"
    assert processor.call_args.kwargs["user_id"] == "owner"
    env.groups["group-a"]["owner"] = {"id": "another-owner"}
    processor.reset_mock()
    with pytest.raises(Exception):
        worker(**args)
    processor.assert_not_called()
    env.user_settings.assert_not_called()


def test_upload_partial_failures_and_size_validation_are_visible(management):
    env = management
    response = env.client.post(f"{ROOT}/upload", data={"file": [
        (BytesIO(b"valid"), "good.pdf"), (BytesIO(b"bad"), "bad.exe"),
        (BytesIO(b"x" * (1024 * 1024 + 1)), "too-large.pdf"),
    ]})
    body = response.get_json()
    assert response.status_code == 207
    assert len(body["document_ids"]) == 1
    assert body["processed_filenames"] == ["good.pdf"]
    assert len(body["errors"]) == 2
    assert len(env.queue.jobs) == 1


@pytest.mark.parametrize("operation", OPERATIONS)
def test_new_routes_keep_login_app_role_and_feature_guards(management, operation):
    env = management
    with env.client.session_transaction() as state:
        state.clear()
    unauthenticated = invoke(env, operation)
    with env.client.session_transaction() as state:
        state["user"] = {"oid": "owner", "roles": []}
    no_app_role = invoke(env, operation)
    with env.client.session_transaction() as state:
        state["user"] = {"oid": "owner", "roles": ["User"]}
    env.settings["enable_group_workspaces"] = False
    disabled = invoke(env, operation)
    assert unauthenticated.status_code == 401
    assert no_app_role.status_code == 403
    assert disabled.status_code == 400
    assert env.source.writes == [] and env.group_container.writes == []
    assert env.queue.jobs == []


@pytest.mark.parametrize("path,method,payload", [
    ("/document-a", "patch", {"title": "Changed"}),
    ("/bulk-tag", "post", {"document_ids": ["document-a"], "action": "set_tags", "tags": []}),
    ("/bulk-delete", "post", {"document_ids": ["document-a"], "delete_mode": "all_versions"}),
    ("/extract_metadata", "post", {"document_ids": ["document-a"]}),
    ("/reprocess_extraction", "post", {"document_ids": ["document-a"], "extraction_mode": "read"}),
    ("/download", "post", {"document_ids": ["document-a"]}),
    ("/tags", "post", {"tag_name": "new-tag"}),
    ("/tags/reference", "patch", {"color": "#fff"}),
])
def test_conflicting_scope_and_bad_bodies_fail_before_effects(management, path, method, payload):
    env = management
    request_method = getattr(env.client, method)
    query_conflict = request_method(f"{ROOT}{path}?group_id=group-b", json=payload)
    body_conflict = request_method(f"{ROOT}{path}", json={**payload, "group_id": "group-b"})
    assert query_conflict.status_code == 400 and body_conflict.status_code == 400
    assert env.source.writes == [] and env.group_container.writes == []
    assert env.blobs.downloads == [] and env.queue.jobs == []


@pytest.mark.parametrize("path,payload", [
    ("/bulk-delete", {"document_ids": ["document-a"], "delete_mode": []}),
    ("/bulk-delete", {"document_ids": ["document-a"], "delete_mode": "all_versions", "file_sync_delete_action": {}}),
    ("/bulk-delete", {"document_ids": ["document-a"], "delete_mode": "current_only", "conversation_linked_delete_confirmed": 1}),
    ("/bulk-tag", {"document_ids": ["document-a"], "action": {}, "tags": []}),
    ("/bulk-tag", {"document_ids": [], "action": "set_tags", "tags": []}),
    ("/reprocess_extraction", {"document_ids": ["document-a"], "extraction_mode": []}),
    ("/extract_metadata", {"document_ids": ["document-a", None]}),
    ("/download", {"document_ids": "document-a"}),
])
def test_malformed_batch_values_are_400_before_any_effect(management, path, payload):
    env = management
    response = env.client.post(f"{ROOT}{path}", json=payload)
    assert response.status_code == 400
    assert env.source.writes == [] and env.group_container.writes == []
    assert env.queue.jobs == [] and env.blobs.downloads == []


@pytest.mark.parametrize("share_status", [None, "approved", "not_approved"])
def test_recipient_access_never_authorizes_source_mutations(management, share_status):
    env = management
    env.source.records["foreign"] = document(
        "foreign", "source-group",
        shared_group_ids=[] if share_status is None else [f"group-a,{share_status}"],
    )
    metadata = env.client.patch(f"{ROOT}/foreign", json={"title": "Forbidden"})
    deletion = env.client.delete(f"{ROOT}/foreign?delete_mode=all_versions")
    tagging = env.client.post(f"{ROOT}/bulk-tag", json={
        "document_ids": ["foreign"], "action": "set_tags", "tags": [],
    })
    extraction = env.client.post(f"{ROOT}/extract_metadata", json={"document_ids": ["foreign"]})
    reprocessing = env.client.post(f"{ROOT}/reprocess_extraction", json={
        "document_ids": ["foreign"], "extraction_mode": "read",
    })
    assert metadata.status_code in {403, 404}
    assert deletion.status_code in {403, 404}
    assert tagging.get_json()["success"] == []
    assert extraction.get_json()["queued"] == [] and reprocessing.get_json()["queued"] == []
    assert env.source.writes == [] and env.group_container.writes == [] and env.queue.jobs == []


@pytest.mark.parametrize("state,can_delete", [
    ("pending_review", True), ("scan_error", True), ("incomplete", True),
    ("rejected", True), ("deleting", True),
    ("pending_scan", False), ("extracting", False), ("scanning", False),
    ("remediating", False), ("publishing", False),
])
def test_screening_cleanup_policy_matches_actions_and_delete_enforcement(management, state, can_delete):
    env = management
    source = env.source.records["document-a"]
    env.seed_release(source)
    source["content_screening"]["state"] = state
    env.scans.records["scan-document-a"]["state"] = state
    read = get(env, "/api/group_documents/document-a")
    metadata = env.client.patch(f"{ROOT}/document-a", json={"title": "Forbidden"})
    download = env.client.get(f"{ROOT}/document-a/download")
    deleted = env.client.delete(f"{ROOT}/document-a?delete_mode=current_only")
    assert read.status_code == 200
    assert read.get_json()["document_actions"] == (["delete"] if can_delete else [])
    assert metadata.status_code == 409 and download.status_code == 409
    assert deleted.status_code == (200 if can_delete else 409), deleted.get_json()


def test_current_only_delete_does_not_release_a_held_promoted_revision(management):
    env = management
    env.source.records["document-a"]["version"] = 2
    old = document("old", revision_family_id="document-a", version=1, is_current_version=False)
    env.seed_release(old)
    old["content_screening"]["state"] = "pending_review"
    env.scans.records["scan-old"]["state"] = "pending_review"
    env.source.records["old"] = old
    response = env.client.delete(f"{ROOT}/document-a?delete_mode=current_only")
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["promoted_document_id"] == "old"
    assert env.source.records["old"]["content_screening"]["state"] == "pending_review"
    assert env.visibility == [("old", False)]
    env.document_helpers["_promote_document_blob_to_current_alias"].assert_not_called()


def test_strict_blob_cleanup_failure_does_not_delete_metadata_or_claim_success(management):
    env = management
    env.blobs.delete_failure = StoreFailure()
    response = env.client.delete(f"{ROOT}/document-a?delete_mode=current_only")
    assert response.status_code == 500
    assert "document-a" in env.source.records
    assert "deleted" not in response.get_json()
    env.index_deletes.assert_not_called()


def test_strict_promotion_claims_source_before_visibility_and_keeps_exact_blob(management):
    env = management
    env.source.records["document-a"]["version"] = 2
    old = document(
        "old", revision_family_id="document-a", version=1, is_current_version=False,
        blob_path="group-a/history/old.pdf", archived_blob_path="group-a/history/old.pdf",
    )
    env.source.records["old"] = old
    env.blobs.put(old["blob_path"], b"OLD")

    def reject_promotion(operation, item, body):
        if operation == "replace" and item == "old":
            env.source.change("old", title="Concurrent old metadata")

    env.source.before_write = reject_promotion
    response = env.client.delete(f"{ROOT}/document-a?delete_mode=current_only")
    assert response.status_code == 500
    assert response.get_json()["deleted_document_ids"] == ["document-a"]
    assert env.visibility == []
    assert env.source.records["old"]["title"] == "Concurrent old metadata"
    assert env.blobs.records[("group-documents", old["blob_path"])]["content"] == b"OLD"
    env.document_helpers["_promote_document_blob_to_current_alias"].assert_not_called()


@pytest.mark.parametrize("with_flags", [True, False])
def test_historical_revisions_keep_only_download_and_delete(management, with_flags):
    env = management
    old = document("old", file_name="document-a.pdf", revision_family_id="document-a", version=0, is_current_version=False)
    env.source.records["old"] = old
    if not with_flags:
        for record in (old, env.source.records["document-a"]):
            record.pop("is_current_version")
            record.pop("revision_family_id")
    response = get(env, "/api/group_documents/old")
    edit = env.client.patch(f"{ROOT}/old", json={"title": "Not current"})
    extract = env.client.post(f"{ROOT}/extract_metadata", json={"document_ids": ["old"]})
    reprocess = env.client.post(f"{ROOT}/reprocess_extraction", json={"document_ids": ["old"], "extraction_mode": "read"})
    assert response.status_code == 200
    assert response.get_json()["document_actions"] == ["delete", "download"]
    assert edit.status_code == 409
    assert extract.get_json()["queued"] == [] and reprocess.get_json()["queued"] == []
    assert env.source.writes == [] and env.queue.jobs == []


def test_selected_revision_becoming_historical_is_not_retargeted(management):
    env = management
    inspected = get(env, "/api/group_documents/document-a")
    env.source.change("document-a", is_current_version=False)
    env.source.records["replacement"] = document("replacement", revision_family_id="document-a", version=2)
    response = env.client.patch(f"{ROOT}/document-a", json={"title": "Stale draft"})
    assert inspected.status_code == 200
    assert response.status_code == 409
    assert env.source.records["replacement"]["title"] == "replacement"
    assert env.source.writes == []


@pytest.mark.parametrize("race", ["change", "delete"])
def test_storage_cas_rejection_after_the_final_read_has_no_projection_effects(management, race):
    env = management

    def reject(operation, item, body):
        env.source.before_write = None
        if race == "change":
            env.source.change(item, abstract="Concurrent winner")
        else:
            del env.source.records[item]

    env.source.before_write = reject
    response = env.client.patch(f"{ROOT}/document-a", json={"title": "Rejected writer", "tags": ["new-tag"]})
    assert response.status_code in {404, 409}
    assert env.source.writes == [] and env.chunk_writes == [] and env.blobs.metadata_writes == []
    env.index_updates.assert_not_called()


def test_tag_finalization_conflict_retains_successes_and_both_vocabularies(management):
    env = management

    def concurrent_group_edit(**kwargs):
        env.group_container.change(
            "group-a", users=[{"userId": "new-member"}],
            tag_definitions={**env.groups["group-a"]["tag_definitions"], "parallel": {"color": "#fff"}},
        )

    env.document_helpers["update_chunk_metadata"] = concurrent_group_edit
    response = env.client.patch(f"{ROOT}/tags/reference", json={"new_name": "renamed"})
    body = response.get_json()
    assert response.status_code == 207
    assert body["vocabulary_retained"] is True
    assert body["success"] == [{"document_id": "document-a", "tags": ["renamed"]}]
    assert body["errors"][0]["stage"] == "vocabulary"
    assert {"reference", "renamed", "parallel"} <= set(env.groups["group-a"]["tag_definitions"])
    assert env.groups["group-a"]["users"] == [{"userId": "new-member"}]


def test_queue_failure_is_safe_and_does_not_leave_a_success_shaped_upload(management):
    env = management
    env.queue.failure = StoreFailure()
    response = env.client.post(f"{ROOT}/upload", data={"file": (BytesIO(b"valid"), "failed.pdf")})
    assert response.status_code == 400
    assert response.get_json()["document_ids"] == []
    assert response.get_json()["errors"]
    assert "PRIVATE-PROVIDER" not in response.get_data(as_text=True)
    records = [record for record in env.source.records.values() if record["file_name"] == "failed.pdf"]
    assert len(records) == 1 and records[0]["status"] == "Error: Upload could not be queued."


def test_extract_and_reprocess_batches_report_each_target(management):
    env = management
    env.source.records["foreign"] = document("foreign", "source-group", shared_group_ids=["group-a,approved"])
    for suffix, extra in (("extract_metadata", {}), ("reprocess_extraction", {"extraction_mode": "read"})):
        response = env.client.post(f"{ROOT}/{suffix}", json={
            "document_ids": ["document-a", "document-a", "foreign", "missing"], **extra,
        })
        body = response.get_json()
        assert response.status_code == 207
        assert [item["document_id"] for item in body["queued"]] == ["document-a"]
        assert {item["document_id"] for item in body["errors"]} == {"foreign", "missing"}
    assert len(env.queue.jobs) == 2


def test_metadata_extraction_honors_explicit_group_when_personal_id_collides(management):
    env = management
    namespace = env.document_helpers
    namespace.update({
        "require_document_available": lambda _document: None,
        "detect_doc_type": Mock(side_effect=AssertionError("Explicit scope must not be rediscovered.")),
        "hybrid_search": Mock(return_value=[]),
        "_resolve_metadata_extraction_client": Mock(return_value=(
            SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"authors":[],"keywords":[]}'))],
            ))))), "fixture-model",
        )),
        "is_effectively_empty": lambda value: value in (None, "", []),
    })
    execute_functions("functions_documents.py", {"extract_document_metadata", "clean_json_codeFence"}, namespace)
    env.personal.records["document-a"] = {"id": "document-a", "user_id": "owner"}
    guard = partial(env.group_access.authorize_group_document_operation, "owner", "group-a", "document-a", "extract_metadata")
    result = namespace["extract_document_metadata"](
        "document-a", "owner", group_id="group-a", operation_guard=guard, safe_errors=True,
    )
    assert result["title"] == "document-a"
    namespace["detect_doc_type"].assert_not_called()
    assert namespace["hybrid_search"].call_args.kwargs["doc_scope"] == "group"
    assert namespace["hybrid_search"].call_args.kwargs["active_group_id"] == "group-a"
    assert not env.personal.reads


def test_worker_progress_updates_recheck_the_captured_guard_and_sanitize_errors(management):
    env = management
    guard = partial(env.group_access.authorize_group_document_operation, "owner", "group-a", "document-a", "extract_metadata")
    saved = env.document_helpers["_update_document_for_job"](
        document_id="document-a", user_id="owner", group_id="group-a",
        status="Error: AccountKey=PRIVATE", operation_guard=guard, safe_errors=True,
    )
    assert "PRIVATE" not in saved["status"]
    before = len(env.source.writes)
    env.groups["group-a"]["status"] = "locked"
    with pytest.raises(Exception):
        env.document_helpers["_update_document_for_job"](
            document_id="document-a", user_id="owner", group_id="group-a",
            title="must not save", operation_guard=guard, safe_errors=True,
        )
    assert len(env.source.writes) == before


def test_legacy_mutation_still_uses_its_active_scope(management):
    env = management
    response = env.client.patch("/api/group_documents/document-b?group_id=group-a", json={"title": "Legacy B"})
    assert response.status_code == 200, response.get_json()
    assert env.source.records["document-b"]["title"] == "Legacy B"
    assert env.source.records["document-a"]["title"] == "document-a"
    env.user_settings.assert_called()


def test_management_version():
    assert_app_version_at_least("0.261.129")


if __name__ == "__main__":
    raise SystemExit(pytest.main([str(Path(__file__).resolve()), "-q"]))
