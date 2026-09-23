#!/usr/bin/env python3
"""
Functional tests for immutable-target public workspace document management.
Version: 0.261.133
Implemented in: 0.261.133

The real public management/access/policy modules and the scoped management route
family run in the isolated Flask app built by the M3A read fixture. The workspace
is always taken from the path, so a stale active-workspace preference can never
redirect a write. Shared document primitives (create/update/delete/download) are
lightweight seams; the group suite covers their internals. No Azure writes, model
calls, or network access occur.
"""

from copy import deepcopy
from io import BytesIO
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Blueprint, jsonify, make_response

from test_public_document_read_apis import (  # noqa: F401  (environment is a fixture)
    MissingRecord,
    PublicReadOnlyContainer,
    document,
    environment,
    get,
    login,
    workspace,
)
from test_support.agent_delegation import module_stub
from test_support.versioning import assert_app_version_at_least


ROOT = "/api/public-workspaces/public-a/documents"


class StoreFailure(Exception):
    def __init__(self, status_code=500):
        self.status_code = status_code
        super().__init__("PRIVATE-PROVIDER-DIAGNOSTIC")


class DocumentMutationPropagationError(Exception):
    """Stand-in matching the class the management module imports and re-checks."""


class DocumentRevisionDeleteError(Exception):
    def __init__(self, message="delete failed", *, deleted_document_ids=None):
        super().__init__(message)
        self.deleted_document_ids = deleted_document_ids or []


class MutablePublicContainer(PublicReadOnlyContainer):
    """The workspace-scoped read stub extended with conditional writes."""

    def __init__(self, records=None):
        super().__init__(records)
        self.writes = []
        self.before_write = None
        self.serial = 0

    def change(self, item, **changes):
        self.serial += 1
        self.records[item] = {**deepcopy(self.records[item]), **changes, "_etag": f"etag-{item}-{self.serial}"}

    def _before(self, operation, item, body=None):
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

    def replace_item(self, item, body, *, etag=None, match_condition=None):
        self._before("replace", item, body)
        if item not in self.records:
            raise MissingRecord()
        if etag is not None and self.records[item].get("_etag") != etag:
            raise StoreFailure(412)
        return self._save("replace", item, body)

    def create_item(self, body):
        self._before("create", body["id"], body)
        if body["id"] in self.records:
            raise StoreFailure(409)
        return self._save("create", body["id"], body)

    def upsert_item(self, body):
        self._before("upsert", body["id"], body)
        return self._save("upsert", body["id"], body)

    def delete_item(self, item, partition_key, **kwargs):
        self._before("delete", item)
        if item not in self.records:
            raise MissingRecord()
        del self.records[item]
        self.writes.append(("delete", item, None))

    def patch_item(self, item, partition_key, patch_operations, filter_predicate):
        self._before("patch", item, patch_operations)
        expected = json.loads(filter_predicate.split(" = ", 1)[1])
        if self.records[item].get("_etag") != expected:
            raise StoreFailure(412)
        updated = deepcopy(self.records[item])
        for operation in patch_operations:
            parts = [part.replace("~1", "/").replace("~0", "~") for part in operation["path"].split("/")[1:]]
            parent = updated
            for part in parts[:-1]:
                parent = parent.setdefault(part, {})
            if operation["op"] == "remove":
                parent.pop(parts[-1], None)
            elif operation["op"] == "add" and len(parts) == 1:
                updated[parts[-1]] = deepcopy(operation["value"])
            else:
                parent[parts[-1]] = deepcopy(operation["value"])
        return self._save("patch", item, updated)


@pytest.fixture
def management(environment):
    env = environment
    patch = env.scoped_monkeypatch
    env.settings.update({
        "enable_extract_meta_data": True, "enable_enhanced_extraction": True, "max_file_size_mb": 1,
    })
    env.downloads = True

    env.source = MutablePublicContainer(env.source.records)
    env.workspace_container = MutablePublicContainer(env.workspaces)
    for workspace_id, record in env.workspaces.items():
        record.setdefault("_etag", f"ws-etag-{workspace_id}")
    # A single-revision current document that every operation can target.
    env.source.records["document-a"] = document(
        "document-a", file_name="document-a.pdf", revision_family_id="document-a",
        blob_container="public-documents", blob_path="public-a/document-a.pdf",
    )
    env.source.records["document-b"] = document(
        "document-b", file_name="document-b.pdf", revision_family_id="document-b",
        blob_container="public-documents", blob_path="public-a/document-b.pdf",
    )

    blobs = {("public-documents", record["blob_path"]): b"SOURCE"
             for record in env.source.records.values() if record.get("blob_path")}
    env.blobs = blobs

    patch.setattr(env.config, "cosmos_public_documents_container", env.source, raising=False)
    patch.setattr(env.config, "cosmos_public_workspaces_container", env.workspace_container, raising=False)
    patch.setattr(env.access, "cosmos_public_documents_container", env.source, raising=False)

    with env.client.session_transaction() as state:
        state["user"] = {"oid": "owner", "roles": ["User"]}
    env.user_settings.reset_mock()

    env.queue = SimpleNamespace(jobs=[], failure=None)

    def submit_stored(key, function, **kwargs):
        if env.queue.failure:
            raise env.queue.failure
        env.queue.jobs.append((key, function, kwargs))
        return SimpleNamespace()

    env.executor = SimpleNamespace(submit_stored=submit_stored)
    env.app.extensions["executor"] = env.executor

    env.propagation_fail = False

    def fake_allowed_file(name):
        return "." in name and name.rsplit(".", 1)[-1].lower() in {"pdf", "png", "txt", "csv", "docx"}

    def fake_create_document(**kwargs):
        document_id = kwargs["document_id"]
        env.source.create_item({
            "id": document_id, "document_id": document_id,
            "public_workspace_id": kwargs["public_workspace_id"], "user_id": kwargs["user_id"],
            "file_name": kwargs["file_name"], "title": kwargs["file_name"], "version": 1,
            "revision_family_id": document_id, "is_current_version": True,
            "status": kwargs.get("status", "Queued for processing"), "percentage_complete": 0,
            "blob_container": "public-documents", "blob_path": f"{kwargs['public_workspace_id']}/{kwargs['file_name']}",
        })

    def fake_update_document(*, document_id, user_id, public_workspace_id, strict=False,
                             expected_etag=None, operation_guard=None, **changes):
        if operation_guard:
            operation_guard()
        current = env.source.read_item(document_id, document_id)
        saved = env.source.replace_item(
            document_id, {**current, **changes}, etag=expected_etag, match_condition="match",
        )
        if env.propagation_fail:
            raise DocumentMutationPropagationError("chunk propagation incomplete")
        return saved

    def fake_delete_document_revision(*, user_id, document_id, public_workspace_id,
                                      delete_mode, family_documents=None, strict=False, operation_guard=None):
        if operation_guard:
            operation_guard()
        family = family_documents or [env.source.records[document_id]]
        targets = [member["id"] for member in family] if delete_mode == "all_versions" else [document_id]
        for target in targets:
            if target in env.source.records:
                env.source.delete_item(target, target)
        return {"deleted_document_ids": targets, "promoted_document_id": None}

    def fake_download(document_item, *, user_id, public_workspace_id, metadata_reader):
        metadata_reader(document_id=document_item["id"], user_id=user_id, group_id=None,
                        public_workspace_id=public_workspace_id)
        response = make_response(env.blobs.get(("public-documents", document_item.get("blob_path")), b"SOURCE"))
        response.headers["Content-Disposition"] = f"attachment; filename=\"{document_item.get('file_name')}\""
        return response

    def fake_zip_download(documents, name, *, user_id, public_workspace_id, metadata_reader):
        for document_item in documents:
            metadata_reader(document_id=document_item["id"], user_id=user_id, group_id=None,
                            public_workspace_id=public_workspace_id)
        response = make_response(b"ZIP")
        response.headers["Content-Disposition"] = f"attachment; filename=\"{name}\""
        return response

    def fake_blob_exists(container, path):
        return (container, path) in env.blobs

    def fake_blob_storage_info(document_item, prefer_archived=False):
        return document_item.get("blob_container"), document_item.get("blob_path")

    functions_documents = sys.modules["functions_documents"]
    updates = {
        "allowed_file": fake_allowed_file, "create_document": fake_create_document,
        "update_document": fake_update_document, "delete_document_revision": fake_delete_document_revision,
        "build_document_download_response": fake_download,
        "build_documents_zip_download_response": fake_zip_download,
        "process_document_upload_background": Mock(), "process_metadata_extraction_background": Mock(),
        "process_document_reprocess_extraction_background": Mock(),
        "DocumentMutationPropagationError": DocumentMutationPropagationError,
        "DocumentRevisionDeleteError": DocumentRevisionDeleteError,
        "get_document_blob_storage_info": fake_blob_storage_info,
        "_blob_exists": fake_blob_exists,
    }
    for name, value in updates.items():
        setattr(functions_documents, name, value)
    env.document_helpers.update(updates)

    file_sync = module_stub(
        "functions_file_sync",
        FILE_SYNC_SCOPE_PUBLIC="public",
        FILE_SYNC_DELETE_ACTIONS={"delete_only", "ignore_remote"},
        build_synced_document_delete_guard=Mock(return_value=None),
        apply_synced_document_delete_action=Mock(),
    )
    patch.setitem(sys.modules, "functions_file_sync", file_sync)
    patch.setitem(sys.modules, "utils_cache", module_stub(
        "utils_cache", invalidate_public_workspace_search_cache=Mock(),
    ))
    patch.setitem(sys.modules, "functions_activity_logging", module_stub(
        "functions_activity_logging", log_document_metadata_update_transaction=Mock(),
    ))
    patch.setitem(sys.modules, "content_screening.service", module_stub(
        "content_screening.service", prepare_document_upload=Mock(),
    ))
    env.settings_module = sys.modules["functions_settings"]
    env.settings_module.is_enhanced_extraction_enabled = lambda settings: settings.get("enable_enhanced_extraction", False)

    from test_public_document_read_apis import load_real_module

    env.management = load_real_module(patch, "functions_public_document_management")
    route = load_real_module(patch, "route_backend_public_document_management")
    env.route_management = route
    env.sync_guard = file_sync.build_synced_document_delete_guard
    env.sync_apply = file_sync.apply_synced_document_delete_action

    blueprint = Blueprint("backend_public_document_management", __name__)
    from functions_authentication import user_required_blueprint
    blueprint.before_request(user_required_blueprint())
    route.register_route_backend_public_document_management(blueprint)
    env.app.register_blueprint(blueprint)
    return env


def actor(env, oid):
    with env.client.session_transaction() as state:
        state["user"] = {"oid": oid, "roles": ["User"]}


def invoke(env, operation):
    calls = {
        "upload": lambda: env.client.post(f"{ROOT}/upload", data={"file": (BytesIO(b"%PDF file"), "fresh.pdf")}),
        "edit_metadata": lambda: env.client.patch(f"{ROOT}/document-a", json={"title": "Changed title"}),
        "delete": lambda: env.client.delete(f"{ROOT}/document-a?delete_mode=current_only"),
        "bulk_delete": lambda: env.client.post(f"{ROOT}/bulk-delete", json={"document_ids": ["document-a"], "delete_mode": "current_only"}),
        "download": lambda: env.client.get(f"{ROOT}/document-a/download"),
        "batch_download": lambda: env.client.post(f"{ROOT}/download", json={"document_ids": ["document-a"]}),
        "extract_metadata": lambda: env.client.post(f"{ROOT}/extract_metadata", json={"document_ids": ["document-a"]}),
        "reprocess": lambda: env.client.post(f"{ROOT}/reprocess_extraction", json={"document_ids": ["document-a"], "extraction_mode": "read"}),
        "create_tag": lambda: env.client.post(f"{ROOT}/tags", json={"tag_name": "new-tag", "color": "#abc"}),
        "rename_tag": lambda: env.client.patch(f"{ROOT}/tags/reference", json={"new_name": "renamed"}),
        "delete_tag": lambda: env.client.delete(f"{ROOT}/tags/reference"),
        "tag_documents": lambda: env.client.post(f"{ROOT}/bulk-tag", json={"document_ids": ["document-a"], "action": "add_tags", "tags": ["new-tag"]}),
    }
    return calls[operation]()


OPERATIONS = tuple(sorted({
    "upload", "edit_metadata", "delete", "bulk_delete", "download", "batch_download",
    "extract_metadata", "reprocess", "create_tag", "rename_tag", "delete_tag", "tag_documents",
}))


def test_implementation_version_is_present():
    assert_app_version_at_least("0.261.133")


@pytest.mark.parametrize("operation", OPERATIONS)
def test_manager_operations_use_the_path_not_active_preferences(management, operation):
    env = management
    response = invoke(env, operation)
    assert response.status_code in {200, 201, 202}, response.get_data(as_text=True)
    env.user_settings.assert_not_called()


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("oid", ["owner", "admin", "manager", "reader", "stranger"])
def test_every_operation_requires_a_content_manager(management, operation, oid):
    env = management
    actor(env, oid)
    response = invoke(env, operation)
    if oid in {"owner", "admin", "manager"}:
        assert response.status_code in {200, 201, 202}, response.get_data(as_text=True)
    else:
        assert response.status_code == 403, response.get_data(as_text=True)
        assert env.source.writes == [] and env.workspace_container.writes == [] and env.queue.jobs == []


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("status", ["locked", "upload_disabled", "inactive", "haunted"])
def test_every_operation_respects_workspace_status(management, operation, status):
    env = management
    env.workspaces["public-a"]["status"] = status
    response = invoke(env, operation)
    download = operation in {"download", "batch_download"}
    delete_like = operation in {"delete", "bulk_delete", "reprocess"}
    permitted = (
        (status == "locked" and download)
        or (status == "upload_disabled" and (download or delete_like))
    )
    if permitted:
        assert response.status_code in {200, 202}, response.get_data(as_text=True)
    else:
        assert response.status_code == 403, response.get_data(as_text=True)
        assert env.source.writes == [] and env.queue.jobs == []


def test_metadata_receipt_carries_public_workspace_id(management):
    env = management
    before = deepcopy(env.source.records["document-a"])
    response = env.client.patch(f"{ROOT}/document-a", json={"title": "Renamed", "authors": ["Writer"]})
    body = response.get_json()
    assert response.status_code == 200, body
    assert body == {
        "message": "Public document metadata updated.", "document_id": "document-a",
        "public_workspace_id": "public-a", "updated_fields": ["authors", "title"], "status": "updated",
    }
    stored = env.source.records["document-a"]
    assert stored["title"] == "Renamed" and stored["authors"] == ["Writer"]
    for field in ("user_id", "public_workspace_id", "id", "abstract"):
        assert stored[field] == before[field]


@pytest.mark.parametrize("payload", [
    {"title": 3}, {"public_workspace_id": "public-b"}, {"user_id": "someone"},
    {"blob_path": "public-b/x.pdf"}, {"document_actions": ["delete"]}, {"tags": ["bad/tag"]},
    {"authors": [3]}, {"keywords": {}}, {"settings": {}}, [], None, {},
])
def test_metadata_validates_whole_payload_before_effects(management, payload):
    env = management
    response = env.client.patch(f"{ROOT}/document-a", json=payload)
    assert response.status_code == 400, response.get_data(as_text=True)
    assert env.source.writes == []


def test_propagation_incomplete_is_a_repair_receipt(management):
    env = management
    env.propagation_fail = True
    response = env.client.patch(f"{ROOT}/document-a", json={"title": "Saved title"})
    body = response.get_json()
    assert response.status_code == 500
    assert body["error"] == "document_propagation_incomplete"
    assert body["repair_required"] is True
    assert body["public_workspace_id"] == "public-a"
    assert "PRIVATE-PROVIDER" not in response.get_data(as_text=True)


def test_tag_create_receipt_and_persistence(management):
    env = management
    response = env.client.post(f"{ROOT}/tags", json={"tag_name": "fresh", "color": "#abcdef"})
    body = response.get_json()
    assert response.status_code == 201, body
    assert body["message"] == "Public tag created."
    assert body["tag"]["name"] == "fresh"
    assert "fresh" in env.workspaces["public-a"]["tag_definitions"]


def test_tag_create_rejects_duplicates(management):
    env = management
    response = env.client.post(f"{ROOT}/tags", json={"tag_name": "reference"})
    assert response.status_code == 409


def test_tag_rename_reports_vocabulary_and_carries_workspace_id(management):
    env = management
    env.source.records["document-a"]["tags"] = ["reference"]
    expected = sum(
        1 for record in env.source.records.values()
        if record.get("public_workspace_id") == "public-a"
        and record.get("is_current_version") is not False
        and "reference" in [t.lower() for t in record.get("tags") or []]
    )
    response = env.client.patch(f"{ROOT}/tags/reference", json={"new_name": "renamed", "color": "#f00"})
    body = response.get_json()
    assert response.status_code in {200, 207}, body
    assert body["message"] == "Public tag renamed."
    assert body["vocabulary_retained"] is False
    assert body["documents_updated"] == expected and expected >= 1
    assert any(entry["document_id"] == "document-a" for entry in body["success"])
    assert "renamed" in env.workspaces["public-a"]["tag_definitions"]


def test_bulk_delete_dedupes_and_reports_requested_ids(management):
    env = management
    env.source.records["older"] = document(
        "older", revision_family_id="document-a", version=0, is_current_version=False,
        file_name="document-a.pdf", blob_container="public-documents", blob_path="public-a/document-a.pdf",
    )
    response = env.client.post(f"{ROOT}/bulk-delete", json={
        "document_ids": ["document-a", "document-a", "older"], "delete_mode": "all_versions",
    })
    body = response.get_json()
    assert response.status_code == 200, body
    assert body["deleted"] == [{"document_id": "document-a"}, {"document_id": "older"}]
    assert body["deleted_count"] == 2 and body["error_count"] == 0
    assert "document-a" not in env.source.records and "older" not in env.source.records


def test_single_delete_requires_explicit_mode(management):
    env = management
    missing = env.client.delete(f"{ROOT}/document-a")
    unknown = env.client.delete(f"{ROOT}/document-a?delete_mode=all_versions&force=true")
    assert missing.status_code == 400 and unknown.status_code == 400
    assert env.source.writes == []


def test_delete_body_is_rejected(management):
    env = management
    response = env.client.delete(f"{ROOT}/document-a?delete_mode=current_only", data=b"body")
    assert response.status_code == 400
    assert env.source.writes == []


@pytest.mark.parametrize("operation", ["edit_metadata", "extract_metadata", "reprocess"])
def test_historical_revisions_are_current_revision_only(management, operation):
    env = management
    env.source.records["document-a"]["version"] = 2
    env.source.records["old"] = document(
        "old", revision_family_id="document-a", version=1, is_current_version=False,
        file_name="document-a.pdf", blob_container="public-documents", blob_path="public-a/document-a.pdf",
    )
    if operation == "edit_metadata":
        response = env.client.patch(f"{ROOT}/old", json={"title": "Not current"})
        assert response.status_code == 409
    else:
        suffix = "extract_metadata" if operation == "extract_metadata" else "reprocess_extraction"
        extra = {} if operation == "extract_metadata" else {"extraction_mode": "read"}
        response = env.client.post(f"{ROOT}/{suffix}", json={"document_ids": ["old"], **extra})
        assert response.get_json()["queued"] == []
    assert env.source.writes == [] and env.queue.jobs == []


def test_upload_rejects_disallowed_and_oversized_per_file(management):
    env = management
    response = env.client.post(f"{ROOT}/upload", data={"file": [
        (BytesIO(b"%PDF ok"), "good.pdf"), (BytesIO(b"bad"), "bad.exe"),
        (BytesIO(b"x" * (1024 * 1024 + 1)), "too-large.pdf"),
    ]})
    body = response.get_json()
    assert response.status_code == 207, body
    assert body["processed_filenames"] == ["good.pdf"]
    assert len(body["document_ids"]) == 1 and len(body["errors"]) == 2
    assert len(env.queue.jobs) == 1


def test_upload_rejects_non_file_form_fields(management):
    env = management
    response = env.client.post(f"{ROOT}/upload", data={"file": (BytesIO(b"%PDF"), "a.pdf"), "title": "x"})
    assert response.status_code == 400
    assert env.queue.jobs == []


@pytest.mark.parametrize("path,payload", [
    ("/bulk-delete", {"document_ids": ["document-a"], "delete_mode": []}),
    ("/bulk-delete", {"document_ids": [], "delete_mode": "current_only"}),
    ("/bulk-tag", {"document_ids": ["document-a"], "action": {}, "tags": []}),
    ("/bulk-tag", {"document_ids": [], "action": "set_tags", "tags": []}),
    ("/bulk-tag", {"document_ids": ["document-a"], "action": "bogus", "tags": []}),
    ("/reprocess_extraction", {"document_ids": ["document-a"], "extraction_mode": []}),
    ("/reprocess_extraction", {"document_ids": ["document-a"], "extraction_mode": "bogus"}),
    ("/extract_metadata", {"document_ids": ["document-a", None]}),
    ("/download", {"document_ids": "document-a"}),
    ("/download", {}),
])
def test_malformed_batch_values_are_400_before_effects(management, path, payload):
    env = management
    response = env.client.post(f"{ROOT}{path}", json=payload)
    assert response.status_code == 400, response.get_data(as_text=True)
    assert env.source.writes == [] and env.queue.jobs == []


@pytest.mark.parametrize("path,method,payload", [
    ("/document-a", "patch", {"title": "x"}),
    ("/bulk-tag", "post", {"document_ids": ["document-a"], "action": "add_tags", "tags": ["t"]}),
    ("/bulk-delete", "post", {"document_ids": ["document-a"], "delete_mode": "all_versions"}),
    ("/extract_metadata", "post", {"document_ids": ["document-a"]}),
    ("/download", "post", {"document_ids": ["document-a"]}),
    ("/tags", "post", {"tag_name": "t"}),
])
def test_unknown_query_parameters_fail_before_effects(management, path, method, payload):
    env = management
    response = getattr(env.client, method)(f"{ROOT}{path}?public_workspace_id=public-b", json=payload)
    assert response.status_code == 400
    assert env.source.writes == [] and env.workspace_container.writes == []


def test_download_binds_to_the_requested_workspace(management):
    env = management
    response = env.client.get(f"{ROOT}/document-a/download")
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.data == b"SOURCE"


def test_unknown_workspace_is_404_not_active_fallback(management):
    env = management
    response = env.client.patch("/api/public-workspaces/no-such/documents/document-a", json={"title": "x"})
    assert response.status_code == 404
    env.user_settings.assert_not_called()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_routes_keep_login_app_role_and_feature_guards(management, operation):
    env = management
    with env.client.session_transaction() as state:
        state.clear()
    unauthenticated = invoke(env, operation)
    actor(env, "owner")
    with env.client.session_transaction() as state:
        state["user"] = {"oid": "owner", "roles": []}
    no_app_role = invoke(env, operation)
    actor(env, "owner")
    env.settings["enable_public_workspaces"] = False
    disabled = invoke(env, operation)
    assert unauthenticated.status_code == 401
    assert no_app_role.status_code == 403
    assert disabled.status_code == 400
    assert env.source.writes == [] and env.queue.jobs == []


def test_queued_jobs_capture_target_and_revalidate(management):
    env = management
    response = env.client.post(f"{ROOT}/extract_metadata", json={"document_ids": ["document-a"]})
    assert response.status_code == 202, response.get_data(as_text=True)
    key, worker, args = env.queue.jobs[0]
    assert args["workspace_id"] == "public-a" and args["user_id"] == "owner"
    worker(**args)
    processor = sys.modules["functions_documents"].process_metadata_extraction_background
    assert processor.call_args.kwargs["public_workspace_id"] == "public-a"
    env.workspaces["public-a"]["owner"] = {"userId": "someone-else"}
    env.workspaces["public-a"]["admins"] = []
    env.workspaces["public-a"]["documentManagers"] = []
    processor.reset_mock()
    with pytest.raises(Exception):
        worker(**args)
    processor.assert_not_called()
    env.user_settings.assert_not_called()