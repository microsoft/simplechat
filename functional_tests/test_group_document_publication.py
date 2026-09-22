# test_group_document_publication.py
"""
Functional tests for scoped generated-artifact publication decisions.
Version: 0.261.131
Implemented in: 0.261.131

Real Flask routes, publication adapters, canonical durable receipt functions and
revision cleanup run against conditional local stores and exact source bytes.
The shared management fixture blocks sockets and restores bootstrap seams.
No Azure, model, provider or filesystem-based artifact processing is performed.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from typing import Any, Dict, Optional
from unittest.mock import Mock
import uuid

import pytest

from test_group_document_management import MutableContainer, StoreFailure, management
from test_group_document_read_apis import MissingRecord, document, environment, get, load_real_module
from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub


ROOT = "/api/groups/group-a/documents"
BINDING = "generated_artifact_publication_binding"
PROCESSING = "generated_artifact_publication_processing"
OPERATION = "group_document_collaboration_operation"
RECEIPTS = "generated_artifact_workspace_publications"
REQUESTER = "requester"
PRIVATE = "PRIVATE-PUBLICATION-SOURCE"


class ReceiptStore(MutableContainer):
    def read_item(self, item, partition_key):
        result = super().read_item(item, partition_key)
        if partition_key != result.get("conversation_id", result["id"]):
            raise MissingRecord()
        return result

    def query_items(self, query, parameters=None, **kwargs):
        values = {item["name"]: item["value"] for item in parameters or []}
        if "@receipt" in values:
            self.queries.append((query, deepcopy(parameters), kwargs))
            return [
                {"id": item["id"]} for item in self.records.values()
                if item.get("metadata", {}).get("publication_receipt_id") == values["@receipt"]
                and item.get("notification_type") == values["@notification_type"]
            ]
        return super().query_items(query, parameters, **kwargs)


def isolate_unused_rendering_and_model_dependencies(patch):
    patch.setitem(sys.modules, "functions_generated_file_exports", module_stub(
        "functions_generated_file_exports",
        build_saved_analysis_export=Mock(side_effect=AssertionError("Publication must reuse existing artifact bytes.")),
    ))
    patch.setitem(sys.modules, "functions_workflow_context", module_stub(
        "functions_workflow_context", WorkflowContextBudgetError=RuntimeError,
        calculate_workflow_context_budget=Mock(side_effect=AssertionError("Publication must not call a model.")),
    ))


@pytest.fixture
def publication_modules(management):
    existing = set(sys.modules)
    try:
        yield management
    finally:
        for name, module in list(sys.modules.items()):
            path = getattr(module, "__file__", None)
            if name not in existing and path and Path(path).resolve().is_relative_to(APP_ROOT):
                sys.modules.pop(name, None)


@pytest.fixture
def publication(publication_modules):
    env = publication_modules
    patch = env.scoped_monkeypatch
    env.groups["group-a"]["users"].append({"userId": REQUESTER})
    env.group_container.records["group-a"]["users"] = deepcopy(env.groups["group-a"]["users"])
    env.content = b"# Exact accepted artifact\n\nExisting values: 12.3400\n"
    env.publication_state = {
        "source_allowed": True, "download_hook": None, "queue_hook": None,
        "queue_failure": False, "notification_failure": None,
    }
    env.publication_calls = {
        "create": [], "queue": [], "queue_attempts": [], "download": [], "notify": [], "cleanup": [],
    }
    env.messages = ReceiptStore({})
    env.conversations = ReceiptStore({
        "private-conversation": {
            "id": "private-conversation", "user_id": REQUESTER,
            "private_source": PRIVATE,
        },
    })
    env.notices = ReceiptStore({})
    for name, value in (
        ("cosmos_messages_container", env.messages),
        ("cosmos_conversations_container", env.conversations),
        ("cosmos_notifications_container", env.notices),
    ):
        patch.setattr(env.config, name, value, raising=False)

    # Retain the real personal-conversation authorization without importing
    # unrelated collaboration storage/bootstrap dependencies.
    conversation_helpers = {"COLLABORATION_SOURCE_KIND": "collaboration_source"}
    execute_functions("functions_collaboration.py", {
        "is_collaboration_source_conversation", "get_collaboration_conversation_for_source",
        "build_conversation_participation_context",
    }, conversation_helpers)
    patch.setitem(sys.modules, "functions_collaboration", module_stub(
        "functions_collaboration", **conversation_helpers,
    ))
    isolate_unused_rendering_and_model_dependencies(patch)
    saved = load_real_module(patch, "functions_saved_analysis")
    sources = load_real_module(patch, "functions_generated_artifact_sources")
    source_context = {
        "conversation_id": "private-conversation", "message_id": "saved-source",
        "result_sha256": "saved-source-digest",
    }

    def read_source(user_id, context):
        if user_id != REQUESTER or context != source_context or not env.publication_state["source_allowed"]:
            raise PermissionError(PRIVATE)
        return {"execution": {"status": "succeeded"}, "validation": {"status": "valid"}}, None, {}

    patch.setattr(saved, "load_saved_analysis", read_source)
    artifact = {
        "id": "private-artifact", "conversation_id": "private-conversation", "role": "file",
        "filename": "accepted.md", "file_content_source": "blob",
        "blob_container": "chat", "blob_path": "requester/private-conversation/accepted.md",
        "metadata": {
            "is_generated_chat_artifact": True,
            "generated_artifact_output_format": "markdown",
            "generated_artifact_content_sha256": hashlib.sha256(env.content).hexdigest(),
            "analysis_result_contexts": [source_context],
        },
    }
    env.messages.create_item(artifact)
    env.artifact_id = artifact["id"]

    approval_helpers = {
        "Any": Any, "Dict": Dict, "Optional": Optional,
        "APPROVAL_STATE_PENDING": "pending", "APPROVAL_STATE_APPROVED": "approved",
    }
    execute_functions("functions_generated_file_approvals.py", {
        "_clean", "_metadata_of", "get_generated_file_approval_state",
        "assert_generated_file_approval_allows_download",
    }, approval_helpers)
    patch.setitem(sys.modules, "functions_generated_file_approvals", module_stub(
        "functions_generated_file_approvals", **approval_helpers,
    ))
    lifecycle_helpers = {
        "Any": Any, "Dict": Dict,
        "has_generated_artifact_source": sources.has_generated_artifact_source,
        "authorize_generated_artifact_source": sources.authorize_generated_artifact_source,
        "authorize_analysis_artifact": saved.authorize_analysis_artifact,
        "GENERATED_CHAT_ARTIFACT_LIFECYCLE_PUBLISHED": "published",
        "GENERATED_CHAT_ARTIFACT_VALIDATION_VALIDATED": "validated",
    }
    execute_functions("functions_simplechat_operations.py", {
        "_safe_positive_int", "_generated_artifact_has_lifecycle_contract",
        "assert_generated_chat_artifact_is_published_for_user",
    }, lifecycle_helpers)

    def create_destination(**values):
        env.publication_calls["create"].append(deepcopy(values))
        return env.source.create_item(document(
            values["document_id"], values["group_id"], user_id=values["user_id"],
            file_name=values["file_name"], status=values["status"],
            title=PRIVATE, abstract=PRIVATE, authors=[PRIVATE], keywords=[PRIVATE],
            tags=[PRIVATE], content=PRIVATE, percentage_complete=0,
        ))

    def download(container, path):
        env.publication_calls["download"].append((container, path))
        if (container, path) != (artifact["blob_container"], artifact["blob_path"]):
            raise LookupError(PRIVATE)
        content = env.content
        if env.publication_state["download_hook"]:
            env.publication_state["download_hook"]()
        return content

    def queue(**values):
        env.publication_calls["queue_attempts"].append(deepcopy(values))
        current = env.source.read_item(values["document_id"], values["document_id"])
        fence = sys.modules["functions_group_document_projection_fence"]
        fence.assert_group_document_source_writable(current)
        if OPERATION in current:
            operation = current[OPERATION]
            assert operation["phase"] == "executing"
            assert fence._collaboration_context.get() == (
                current["id"], operation["id"], operation["execution_token"],
            )
        assert values["group_id"] == current["group_id"]
        assert values["owner_user_id"] == REQUESTER
        assert values["file_content_bytes"] == env.content
        env.publication_calls["queue"].append(deepcopy(values))
        if env.publication_state["queue_hook"]:
            env.publication_state["queue_hook"]()
        if env.publication_state["queue_failure"]:
            raise TimeoutError(PRIVATE)
        env.document_helpers["update_document"](
            document_id=current["id"], user_id=REQUESTER,
            group_id=current["group_id"], status="Queued for processing",
        )

    def notify(**values):
        env.publication_calls["notify"].append(deepcopy(values))
        if env.publication_state["notification_failure"] == "before":
            return None
        notice = {"id": str(uuid.uuid4()), **deepcopy(values)}
        env.notices.create_item(notice)
        if env.publication_state["notification_failure"] == "after":
            return None
        return notice

    def workspace_notice(target, kind, title, message, **values):
        return notify(group_id=target, notification_type=kind, title=title, message=message, **values)

    def cleanup_notices(**values):
        env.publication_calls["cleanup"].append(deepcopy(values))
        for key, notice in list(env.notices.records.items()):
            if (
                notice["notification_type"] in values["notification_types"]
                and all(notice["metadata"].get(field) == value
                        for field, value in values["metadata_filters"].items())
            ):
                del env.notices.records[key]

    docs = sys.modules["functions_documents"]
    patch.setattr(docs, "create_document", create_destination)
    patch.setattr(docs, "update_document", env.document_helpers["update_document"])
    patch.setattr(docs, "delete_document_revision", env.document_helpers["delete_document_revision"])
    patch.setattr(docs, "allowed_file", lambda name: name.endswith(".md"))
    operations = sys.modules["functions_simplechat_operations"]
    for name, value in lifecycle_helpers.items():
        patch.setattr(operations, name, value, raising=False)
    patch.setattr(operations, "download_blob_content", download)
    patch.setattr(operations, "queue_generated_document_processing", queue)
    patch.setattr(operations, "_write_temp_generated_file", Mock(side_effect=AssertionError(
        "Publication contract tests do not create temporary files.",
    )), raising=False)
    notifications = sys.modules["functions_notifications"]
    for name, value in (
        ("create_notification", notify), ("create_group_notification", workspace_notice),
        ("create_public_workspace_notification", Mock(side_effect=AssertionError("No public destination."))),
        ("delete_notifications_by_metadata", cleanup_notices),
    ):
        patch.setattr(notifications, name, value, raising=False)
    patch.setattr(sys.modules["functions_activity_logging"], "log_document_deletion_transaction", Mock(), raising=False)
    patch.setattr(sys.modules["utils_cache"], "invalidate_personal_search_cache", Mock(), raising=False)
    patch.setitem(sys.modules, "functions_personal_workflows", module_stub(
        "functions_personal_workflows",
        normalize_workflow_publication=Mock(side_effect=AssertionError("No workflow creation.")),
    ))
    patch.setitem(sys.modules, "functions_public_workspaces", module_stub(
        "functions_public_workspaces",
        check_public_workspace_status_allows_operation=Mock(side_effect=AssertionError("No public workspace.")),
        find_public_workspace_by_id=Mock(side_effect=AssertionError("No public workspace.")),
        get_user_role_in_public_workspace=Mock(side_effect=AssertionError("No public workspace.")),
    ))
    canonical = load_real_module(patch, "functions_artifact_publication")
    # Match the shared conditional-container fixture's transport error seam.
    patch.setattr(canonical, "CosmosResourceNotFoundError", MissingRecord)
    patch.setattr(canonical, "CosmosHttpResponseError", StoreFailure)
    for module in (env.collaboration, env.group_publication):
        patch.setattr(module, "cosmos_group_documents_container", env.source)
    patch.setattr(env.group_publication, "publication", canonical)
    patch.setattr(env.group_publication, "delete_document_revision", docs.delete_document_revision)
    patch.setattr(env.group_publication, "delete_notifications_by_metadata", cleanup_notices)
    env.canonical = canonical
    set_actor(env, "manager")
    yield env


def set_actor(env, actor):
    with env.client.session_transaction() as state:
        state["user"] = {"oid": actor, "roles": ["User"]}


def submit(env, *, legacy=False):
    result = env.canonical.publish_generated_chat_artifact_for_user(
        REQUESTER, conversation_id="private-conversation", message_id=env.artifact_id,
        destination={"workspace_scope": "group", "group_id": "group-a"},
        request_id="exact-publication-request", requester_display_name="Requester",
    )
    target = result["document"]["id"]
    env.target = target
    env.receipt_id = result["publication"]["id"]
    if not legacy:
        current = env.source.read_item(target, target)
        env.canonical.enroll_legacy_artifact_publication(
            current, operation_guard=lambda: env.group_access.require_group_document_read_context(REQUESTER, "group-a"),
        )
    return env.source.read_item(target, target)


def receipt(env):
    message = env.messages.read_item(env.artifact_id, "private-conversation")
    return message["metadata"][RECEIPTS][env.receipt_id]


def change_receipt(env, **changes):
    message = env.messages.read_item(env.artifact_id, "private-conversation")
    metadata = deepcopy(message["metadata"])
    metadata[RECEIPTS][env.receipt_id].update(deepcopy(changes))
    env.messages.change(env.artifact_id, metadata=metadata)


def after_stage_claim(env, stage, callback):
    def before_write(operation, item, body):
        candidate = body.get("metadata", {}).get(RECEIPTS, {}).get(env.receipt_id, {})
        if operation == "replace" and candidate.get("stages", {}).get(stage) == "started":
            env.messages.before_write = None
            callback()

    env.messages.before_write = before_write


def hold_destination(env, state="pending_review"):
    current = env.source.records[env.target]
    env.seed_release(current)
    marker = {**current["content_screening"], "state": state}
    env.source.change(env.target, content_screening=marker)
    env.scans.records[marker["scan_id"]]["state"] = state


def sharing(env):
    return env.client.get(f"{ROOT}/{env.target}/sharing")


def decide(env, action, *, etag=None, group_id="group-a"):
    if etag is None:
        current = env.source.read_item(env.target, env.target)
        etag = current["_etag"]
    return env.client.post(
        f"/api/groups/{group_id}/documents/{env.target}/artifact/{action}",
        json={"expected_etag": etag},
    )


def assert_receipt(response, env, action, status, state, http_status):
    value = response.get_json()
    assert response.status_code == http_status, value
    assert set(value) == {"schema_version", "group_id", "document_id", "action", "status", "state", "errors"}
    assert value["schema_version"] == 1
    assert value["group_id"] == "group-a"
    assert value["document_id"] == env.target
    assert value["action"] == f"{action}_artifact"
    assert value["status"] == status
    assert value["state"] == state
    assert isinstance(value["errors"], list)
    if status != "partial":
        assert value["errors"] == []
    assert PRIVATE not in json.dumps(value)
    return value


@pytest.mark.parametrize("action,state", [("approve", "approved"), ("reject", "rejected"), ("cancel", "cancelled")])
def test_real_scoped_decisions_preserve_exact_destination_and_durable_receipt(publication, action, state):
    env = publication
    submit(env)
    before_other = deepcopy(env.source.records["document-b"])
    if action == "cancel":
        set_actor(env, REQUESTER)
    response = decide(env, action)
    assert_receipt(response, env, action, "queued" if action == "approve" else "applied", state,
                   202 if action == "approve" else 200)
    saved = receipt(env)
    assert saved["decision"]["choice"] == state
    assert saved["decision"]["actor_user_id"] == (REQUESTER if action == "cancel" else "manager")
    assert env.source.records["document-b"] == before_other
    assert len(env.publication_calls["create"]) == 1
    assert len(env.publication_calls["queue"]) == (1 if action == "approve" else 0)
    assert len(env.publication_calls["notify"]) == (2 if action == "cancel" else 3)
    assert len(env.messages.records[env.artifact_id]["metadata"][RECEIPTS]) == 1
    if action != "approve":
        assert env.target not in env.source.records
        assert env.blobs.deleted == []
        assert [item[0] for item in env.deleted_chunks] == [env.target]
    else:
        assert env.source.records[env.target][OPERATION]["phase"] == "complete"
    if action != "cancel":
        notice = env.publication_calls["notify"][-1]
        assert notice["link_url"] == f"/v2/groups/group-a/documents?document_id={env.target}"
        assert notice["metadata"]["publication_receipt_id"] == env.receipt_id
    env.user_settings.assert_not_called()


def test_refreshed_approval_is_idempotent_but_blind_replay_is_a_conflict(publication):
    env = publication
    initial = submit(env)
    first = decide(env, "approve", etag=initial["_etag"])
    stale = decide(env, "approve", etag=initial["_etag"])
    fresh = sharing(env)
    repeated = decide(env, "approve", etag=fresh.get_json()["etag"])
    assert_receipt(first, env, "approve", "queued", "approved", 202)
    assert stale.status_code == 409
    assert_receipt(repeated, env, "approve", "unchanged", "approved", 200)
    assert len(env.publication_calls["create"]) == len(env.publication_calls["queue"]) == 1
    assert len(env.publication_calls["notify"]) == 3


def test_legacy_pending_request_enrolls_into_existing_receipt_without_a_second_copy(publication):
    env = publication
    before = submit(env, legacy=True)
    before_receipt = receipt(env)
    response = decide(env, "approve")
    assert_receipt(response, env, "approve", "queued", "approved", 202)
    current = env.source.read_item(env.target, env.target)
    saved = receipt(env)
    assert BINDING not in before
    assert "document_version" not in before_receipt
    assert current[BINDING]["receipt_id"] == before_receipt["id"]
    assert saved["document_version"] == before["version"]
    assert saved["artifact_reference"] == {
        "conversation_id": "private-conversation", "artifact_message_id": env.artifact_id,
    }
    assert len(env.messages.records[env.artifact_id]["metadata"][RECEIPTS]) == 1
    assert len(env.publication_calls["create"]) == len(env.publication_calls["queue"]) == 1


@pytest.mark.parametrize("action", ["approve", "reject", "cancel"])
@pytest.mark.parametrize("actor", ["owner", "admin", "manager", "reader", REQUESTER, "outsider"])
def test_manager_decisions_and_requester_cancel_do_not_borrow_each_others_authority(publication, action, actor):
    env = publication
    submit(env)
    set_actor(env, actor)
    before = deepcopy(env.source.records)
    response = decide(env, action)
    permitted = actor == REQUESTER if action == "cancel" else actor in {"owner", "admin", "manager"}
    saved = receipt(env)
    if permitted:
        assert response.status_code == (202 if action == "approve" else 200), response.get_json()
        assert saved["decision"]["actor_user_id"] == actor
    else:
        assert response.status_code == 403, response.get_json()
        assert "decision" not in saved
        assert env.source.records == before
        assert env.publication_calls["queue_attempts"] == []
        assert len(env.publication_calls["notify"]) == 2


@pytest.mark.parametrize("action", ["approve", "reject", "cancel"])
@pytest.mark.parametrize("status", ["active", "upload_disabled", "locked", "inactive", "unknown"])
def test_selected_destination_status_controls_publication_not_active_preferences(publication, action, status):
    env = publication
    submit(env)
    env.groups["group-a"]["status"] = status
    if action == "cancel":
        set_actor(env, REQUESTER)
    before = deepcopy(env.source.records)
    response = decide(env, action)
    allowed = status == "active" or status == "upload_disabled" and action != "approve"
    saved = receipt(env)
    if allowed:
        assert response.status_code == (202 if action == "approve" else 200), response.get_json()
        assert saved["decision"]["choice"] == {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}[action]
    else:
        assert response.status_code == 403, response.get_json()
        assert "decision" not in saved
        assert env.source.records == before
        assert env.publication_calls["queue_attempts"] == []
    env.user_settings.assert_not_called()


@pytest.mark.parametrize("actor,actions", [
    ("manager", {"inspect", "approve_artifact", "reject_artifact"}),
    (REQUESTER, {"inspect", "cancel_artifact"}),
    ("reader", {"inspect"}),
])
def test_pending_state_is_allowlisted_and_computes_actions_from_current_authority(publication, actor, actions):
    env = publication
    submit(env)
    env.source.change(env.target, document_collaboration_actions=["share", "approve_artifact", "cancel_artifact"])
    set_actor(env, actor)
    response = sharing(env)
    value = response.get_json()
    assert response.status_code == 200, value
    assert set(value) == {
        "schema_version", "group_id", "document_id", "document_version", "etag",
        "owner_group", "relationship", "actions", "recipients", "publication",
    }
    assert set(value["actions"]) == actions
    assert set(value["publication"]) == {
        "status", "is_requester", "requested_by_user_id", "requested_by_display_name", "requested_at", "actions",
    }
    assert set(value["publication"]["actions"]) == actions - {"inspect"}
    assert value["publication"]["is_requester"] is (actor == REQUESTER)
    assert value["publication"]["status"] == "pending_approval"
    serialized = json.dumps(value)
    for secret in (PRIVATE, "private-conversation", "private-artifact", "blob_path", RECEIPTS, BINDING):
        assert secret not in serialized


@pytest.mark.parametrize("surface", ["list", "detail", "versions"])
@pytest.mark.parametrize("prepared", [False, True])
def test_initial_pending_status_gap_never_exposes_extracted_content_or_management_actions(publication, surface, prepared):
    env = publication
    submit(env)
    current = env.source.records[env.target]
    current.pop("generated_artifact_promotion_status")
    current["status"] = "Pending approval"
    if not prepared:
        for key in list(current):
            if key.startswith("generated_artifact_"):
                current.pop(key)
    if surface == "list":
        response = get(env, "/api/group_documents", page_size=100)
        rows = response.get_json()["documents"]
    elif surface == "detail":
        response = get(env, f"/api/group_documents/{env.target}")
        rows = [response.get_json()]
    else:
        response = get(env, f"/api/group_documents/{env.target}/versions")
        rows = response.get_json()["versions"]
    assert response.status_code == 200, response.get_json()
    selected = [row for row in rows if row["id"] == env.target]
    assert len(selected) == 1
    row = selected[0]
    assert row["generated_artifact_promotion_status"] == "pending_approval"
    assert row["document_actions"] == []
    assert "share" not in row["document_collaboration_actions"]
    assert PRIVATE not in json.dumps(row)
    assert BINDING not in row
    assert not env.publication_calls["queue"]
    assert "blob_path" not in row


@pytest.mark.parametrize("with_flags", [False, True])
def test_historical_pending_request_never_approves_an_accessible_sibling(publication, with_flags):
    env = publication
    current = submit(env)
    sibling = document("newer-publication-revision", version=2, revision_family_id=env.target,
                       file_name=current["file_name"])
    env.source.create_item(sibling)
    if with_flags:
        env.source.change(env.target, is_current_version=False)
    else:
        env.source.records[env.target].pop("is_current_version")
        env.source.records[sibling["id"]].pop("is_current_version")
    state = sharing(env)
    response = decide(env, "approve")
    saved = receipt(env)
    assert "approve_artifact" not in state.get_json()["actions"]
    assert "reject_artifact" in state.get_json()["actions"]
    assert response.status_code == 409, response.get_json()
    assert "decision" not in saved
    assert not env.publication_calls["queue_attempts"]
    assert env.source.records[sibling["id"]]["version"] == 2


@pytest.mark.parametrize("state", ["pending_scan", "pending_review", "scan_error", "rejected", "deleting", "unknown"])
def test_screening_hold_is_not_an_artifact_approval_override(publication, state):
    env = publication
    submit(env)
    hold_destination(env, state)
    original = deepcopy(env.source.records[env.target]["content_screening"])
    view = sharing(env)
    response = decide(env, "approve")
    saved = receipt(env)
    assert "approve_artifact" not in view.get_json()["actions"]
    assert "approve_artifact" not in view.get_json()["publication"]["actions"]
    assert response.status_code == 409, response.get_json()
    assert "decision" not in saved
    assert env.source.records[env.target]["content_screening"] == original
    assert not env.publication_calls["queue_attempts"]


@pytest.mark.parametrize("when", ["before", "after_bytes", "queue_claim"])
def test_source_authorization_is_rechecked_at_the_effect_boundary(publication, when):
    env = publication
    submit(env)
    def revoke():
        env.publication_state["source_allowed"] = False
    if when == "before":
        revoke()
    elif when == "after_bytes":
        env.publication_state["download_hook"] = revoke
    else:
        after_stage_claim(env, "approval_queue", revoke)
    response = decide(env, "approve")
    saved = receipt(env)
    assert response.status_code == (207 if when == "queue_claim" else 409), response.get_json()
    assert not env.publication_calls["queue_attempts"]
    assert len(env.publication_calls["create"]) == 1
    assert len(env.publication_calls["notify"]) == 2
    if when == "queue_claim":
        assert saved["decision"]["choice"] == "approved"
        assert saved["stages"]["approval_queue"] == "started"
        assert response.get_json()["state"] == "approval_failed"
    else:
        assert "decision" not in saved
    assert PRIVATE not in json.dumps(response.get_json())


@pytest.mark.parametrize("change", ["actor_membership", "requester_membership", "upload_disabled", "locked", "screening_hold"])
def test_live_destination_guards_run_after_queue_claim_before_dispatch(publication, change):
    env = publication
    submit(env)
    def revoke():
        if change == "actor_membership":
            env.groups["group-a"]["documentManagers"] = []
        elif change == "requester_membership":
            env.groups["group-a"]["users"] = [{"userId": "reader"}]
        elif change == "screening_hold":
            hold_destination(env)
        else:
            env.groups["group-a"]["status"] = change
    after_stage_claim(env, "approval_queue", revoke)
    response = decide(env, "approve")
    saved = receipt(env)
    assert not env.publication_calls["queue_attempts"]
    assert saved["decision"]["choice"] == "approved"
    assert response.status_code in {207, 409, 403}, response.get_json()
    assert len(env.publication_calls["notify"]) == 2
    if response.status_code == 207:
        assert response.get_json()["state"] == "approval_failed"


@pytest.mark.parametrize("change", ["actor_membership", "locked"])
def test_publication_notice_rechecks_actor_authority_after_its_stage_claim(publication, change):
    env = publication
    submit(env)
    def revoke():
        if change == "actor_membership":
            env.groups["group-a"]["documentManagers"] = []
        else:
            env.groups["group-a"]["status"] = "locked"
    after_stage_claim(env, "decision_notification", revoke)
    response = decide(env, "approve")
    saved = receipt(env)
    assert len(env.publication_calls["queue"]) == 1
    assert len(env.publication_calls["notify"]) == 2
    assert saved["stages"]["decision_notification"] == "started"
    assert response.status_code in {207, 409, 403}


@pytest.mark.parametrize("phase", ["repair", "complete", "uncertain", "other-token"])
def test_canonical_dispatch_requires_the_same_executing_adapter_token(publication, phase):
    env = publication
    submit(env)
    def replace_execution():
        operation = deepcopy(env.source.records[env.target][OPERATION])
        if phase == "other-token":
            operation["execution_token"] = "another-request"
        else:
            operation["phase"] = phase
        env.source.change(env.target, **{OPERATION: operation})
    env.publication_state["download_hook"] = replace_execution
    response = decide(env, "approve")
    saved = receipt(env)
    assert "decision" not in saved
    assert env.publication_calls["queue_attempts"] == []
    assert response.status_code == 409, response.get_json()
    assert env.source.records[env.target][OPERATION].get("phase") == (
        "executing" if phase == "other-token" else phase
    )


@pytest.mark.parametrize("race", ["etag", "deleted", "historical"])
def test_destination_cas_conflicts_never_commit_a_publication_decision(publication, race):
    env = publication
    initial = submit(env)
    def before_write(operation, item, body):
        if item != env.target or OPERATION not in (body or {}):
            return
        env.source.before_write = None
        if race == "deleted":
            del env.source.records[item]
        else:
            env.source.change(item, is_current_version=race != "historical", title="Concurrent metadata")
    env.source.before_write = before_write
    response = decide(env, "approve", etag=initial["_etag"])
    saved = receipt(env)
    assert response.status_code == 409, response.get_json()
    assert "decision" not in saved
    assert not env.publication_calls["queue_attempts"]
    assert len(env.publication_calls["notify"]) == 2


def test_canonical_receipt_cas_cannot_replace_a_concurrent_opposite_decision(publication):
    env = publication
    submit(env)
    def concurrent_decision(operation, item, body):
        candidate = body["metadata"][RECEIPTS][env.receipt_id]
        if operation == "replace" and "decision" in candidate:
            env.messages.before_write = None
            change_receipt(env, decision={"choice": "rejected", "actor_user_id": "owner"})
    env.messages.before_write = concurrent_decision
    response = decide(env, "approve")
    saved = receipt(env)
    assert response.status_code == 409, response.get_json()
    assert saved["decision"]["choice"] == "rejected"
    assert not env.publication_calls["queue_attempts"]
    assert len(env.publication_calls["notify"]) == 2


def test_ambiguous_queue_acknowledgement_is_not_a_new_pending_approval_or_a_second_job(publication):
    env = publication
    submit(env)
    env.publication_state["queue_failure"] = True
    first = decide(env, "approve")
    first_view = sharing(env)
    first_saved = receipt(env)
    repeated = decide(env, "approve", etag=first_view.get_json()["etag"])
    repeated_view = sharing(env)
    current = env.source.read_item(env.target, env.target)
    env.source.change(env.target, **{
        PROCESSING: {"binding": deepcopy(current[BINDING]), "state": "running"},
    })
    reconciled = decide(env, "approve")
    final_saved = receipt(env)
    assert_receipt(first, env, "approve", "partial", "approval_failed", 207)
    assert_receipt(repeated, env, "approve", "partial", "approval_failed", 207)
    assert first_saved["decision"]["choice"] == "approved"
    assert first_saved["stages"]["approval_queue"] == "started"
    for view in (first_view, repeated_view):
        projection = view.get_json()
        assert projection["publication"]["status"] == "approval_failed"
        assert projection["publication"]["actions"] == ["approve_artifact"]
        assert "reject_artifact" not in projection["actions"]
        assert "cancel_artifact" not in projection["actions"]
    assert_receipt(reconciled, env, "approve", "unchanged", "approved", 200)
    assert final_saved["stages"]["approval_queue"] == "complete"
    assert len(env.publication_calls["create"]) == len(env.publication_calls["queue"]) == 1
    assert len(env.publication_calls["notify"]) == 3


@pytest.mark.parametrize("action", ["reject", "cancel"])
@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize("persisted", [False, True])
def test_negative_cleanup_deletes_only_the_exact_persisted_source_not_family_or_alias(
    publication, action, historical, persisted,
):
    env = publication
    current = submit(env)
    alias = f"group-a/{current['file_name']}"
    archived = f"group-a/revisions/other/{current['file_name']}"
    exact = f"group-a/revisions/{env.target}/{current['file_name']}"
    for path in (alias, archived, exact):
        env.blobs.put(path)
    sibling = document(
        "family-sibling", version=2 if historical else 1, revision_family_id=env.target,
        file_name=current["file_name"], is_current_version=historical,
        blob_container="group-documents", archived_blob_path=archived,
        blob_path=alias if historical else archived,
    )
    env.source.create_item(sibling)
    if historical:
        env.source.change(env.target, is_current_version=False)
    else:
        env.source.change(env.target, version=2, **{
            BINDING: {**current[BINDING], "document_version": 2},
        })
        change_receipt(env, document_version=2)
    if persisted:
        env.source.change(
            env.target, blob_container="group-documents",
            blob_path=exact, blob_path_mode="archived_revision",
        )
    if action == "cancel":
        set_actor(env, REQUESTER)
    response = decide(env, action)
    assert_receipt(response, env, action, "applied", "rejected" if action == "reject" else "cancelled", 200)
    assert env.target not in env.source.records
    assert "family-sibling" in env.source.records
    assert [item[0] for item in env.deleted_chunks] == [env.target]
    assert env.blobs.deleted == ([("group-documents", exact)] if persisted else [])
    assert ("group-documents", alias) in env.blobs.records
    assert ("group-documents", archived) in env.blobs.records
    assert len(env.publication_calls["create"]) == 1
    assert env.publication_calls["queue_attempts"] == []


@pytest.mark.parametrize("action", ["reject", "cancel"])
def test_negative_receipt_can_be_replayed_canonically_but_absent_scoped_target_is_not_fabricated(publication, action):
    env = publication
    original = submit(env)
    if action == "cancel":
        set_actor(env, REQUESTER)
    first = decide(env, action)
    state = "rejected" if action == "reject" else "cancelled"
    result = env.canonical.decide_artifact_publication(
        REQUESTER if action == "cancel" else "manager", original, state,
    )
    repeated = decide(env, action, etag=original["_etag"])
    view = sharing(env)
    saved = receipt(env)
    assert_receipt(first, env, action, "applied", state, 200)
    assert result["document_id"] == env.target
    assert saved["decision"]["choice"] == state
    assert repeated.status_code == view.status_code == 404
    assert len(env.publication_calls["notify"]) == (3 if action == "reject" else 2)
    assert len(env.deleted_chunks) == 1


@pytest.mark.parametrize("choice", ["approved", "rejected", "cancelled"])
def test_missing_destination_without_matching_decision_cannot_gain_an_idempotent_success(publication, choice):
    env = publication
    original = submit(env)
    del env.source.records[env.target]
    with pytest.raises(ValueError, match="destination"):
        env.canonical.decide_artifact_publication(
            REQUESTER if choice == "cancelled" else "manager", original, choice,
        )
    saved = receipt(env)
    assert "decision" not in saved
    assert len(env.publication_calls["notify"]) == 2
    assert env.publication_calls["queue_attempts"] == []


@pytest.mark.parametrize("failure", ["before", "after"])
def test_negative_notification_recovery_uses_existing_evidence_or_reports_partial(publication, failure):
    env = publication
    original = submit(env)
    env.publication_state["notification_failure"] = failure
    response = decide(env, "reject")
    saved = receipt(env)
    assert env.target not in env.source.records
    assert_receipt(response, env, "reject", "partial" if failure == "before" else "applied", "rejected",
                   207 if failure == "before" else 200)
    assert saved["stages"]["decision_notification"] == ("started" if failure == "before" else "complete")
    env.publication_state["notification_failure"] = None
    recovered = env.canonical.decide_artifact_publication("manager", original, "rejected")
    assert recovered["document_id"] == env.target
    assert len(env.publication_calls["notify"]) == 3
    assert len(env.deleted_chunks) == 1


@pytest.mark.parametrize("field,value", [
    ("receipt_id", "forged-receipt"), ("version", 2), ("document_version", 2),
    ("content_sha256", "0" * 64), ("conversation_id", "other-conversation"),
    ("artifact_message_id", "other-artifact"),
])
def test_forged_v1_destination_binding_is_unavailable_and_cannot_decide(publication, field, value):
    env = publication
    current = submit(env)
    env.source.change(env.target, **{BINDING: {**current[BINDING], field: value}})
    view = sharing(env)
    response = decide(env, "reject")
    saved = receipt(env)
    assert response.status_code == 409, response.get_json()
    assert view.get_json()["publication"]["status"] == "unavailable"
    assert view.get_json()["publication"]["actions"] == []
    assert "decision" not in saved
    assert env.target in env.source.records
    assert not env.deleted_chunks
    assert not env.publication_calls["queue_attempts"]


@pytest.mark.parametrize("tamper", [
    "request", "actor", "hash", "destination", "file_name", "document", "source_path", "uuid",
])
def test_legacy_enrollment_requires_exact_old_key_source_actor_request_destination_and_document(publication, tamper):
    env = publication
    current = submit(env, legacy=True)
    saved = receipt(env)
    if tamper == "request":
        change_receipt(env, request_id="another-request")
    elif tamper == "actor":
        change_receipt(env, actor_user_id="reader")
    elif tamper == "hash":
        change_receipt(env, content_sha256="0" * 64)
    elif tamper == "destination":
        change_receipt(env, destination={"workspace_scope": "group", "group_id": "group-b"})
    elif tamper == "file_name":
        change_receipt(env, file_name="other.md")
    elif tamper == "document":
        change_receipt(env, document_id="another-document")
    elif tamper == "source_path":
        env.source.change(env.target, generated_artifact_source_blob_path="forged/blob")
    else:
        env.target = "non-deterministic-destination"
        env.source.create_item({**current, "id": env.target})
        change_receipt(env, document_id=env.target)
    response = decide(env, "approve")
    after = receipt(env)
    assert response.status_code == 409, response.get_json()
    assert "decision" not in after
    assert BINDING not in env.source.records[env.target]
    assert len(env.publication_calls["create"]) == 1
    assert env.publication_calls["queue_attempts"] == []
    assert after["id"] == saved["id"]


@pytest.mark.parametrize("action", ["approve", "reject", "cancel"])
def test_blob_only_legacy_request_is_unverifiable_not_an_approval_or_cleanup_bypass(publication, action):
    env = publication
    submit(env, legacy=True)
    env.source.records[env.target].pop("generated_artifact_publication_receipt_id")
    if action == "cancel":
        set_actor(env, REQUESTER)
    before = deepcopy(env.source.records)
    response = decide(env, action)
    saved = receipt(env)
    assert response.status_code == 409, response.get_json()
    assert response.get_json()["error"] == "publication_unverifiable"
    assert "decision" not in saved
    assert env.source.records == before
    assert len(env.publication_calls["create"]) == 1
    assert len(env.publication_calls["notify"]) == 2
    assert env.publication_calls["queue_attempts"] == []


def test_committed_approval_with_stale_pending_metadata_is_a_repair_not_a_new_request(publication):
    env = publication
    submit(env)
    def fail_projection(operation, item, body):
        if operation == "replace" and (body or {}).get("generated_artifact_promotion_status") == "approved":
            env.source.before_write = None
            raise StoreFailure()
    env.source.before_write = fail_projection
    first = decide(env, "approve")
    current = env.source.read_item(env.target, env.target)
    state = sharing(env)
    saved = receipt(env)
    assert_receipt(first, env, "approve", "partial", "approval_failed", 207)
    assert current["generated_artifact_promotion_status"] == "pending_approval"
    assert saved["decision"]["choice"] == "approved"
    assert state.get_json()["publication"]["status"] == "approval_failed"
    assert state.get_json()["publication"]["actions"] == ["approve_artifact"]
    assert "reject_artifact" not in state.get_json()["actions"]
    retried = decide(env, "approve", etag=state.get_json()["etag"])
    assert_receipt(retried, env, "approve", "unchanged", "approved", 200)
    assert len(env.publication_calls["create"]) == len(env.publication_calls["queue"]) == 1
    assert len(env.publication_calls["notify"]) == 3


@pytest.mark.parametrize("action", ["reject", "cancel"])
def test_failed_negative_cleanup_keeps_only_the_same_recoverable_decision_action(publication, action):
    env = publication
    submit(env)
    path = f"group-a/revisions/{env.target}/accepted.md"
    env.blobs.put(path)
    env.source.change(env.target, blob_container="group-documents", blob_path=path, blob_path_mode="archived_revision")
    env.blobs.delete_failure = StoreFailure()
    if action == "cancel":
        set_actor(env, REQUESTER)
    first = decide(env, action)
    state = sharing(env)
    saved = receipt(env)
    choice = "rejected" if action == "reject" else "cancelled"
    assert_receipt(first, env, action, "partial", choice, 207)
    assert saved["decision"]["choice"] == choice
    assert state.get_json()["publication"]["status"] == choice
    assert state.get_json()["publication"]["actions"] == [f"{action}_artifact"]
    assert set(state.get_json()["actions"]) == {"inspect", f"{action}_artifact"}
    env.blobs.delete_failure = None
    retried = decide(env, action, etag=state.get_json()["etag"])
    assert_receipt(retried, env, action, "unchanged", choice, 200)
    assert env.target not in env.source.records
    assert env.blobs.deleted == [("group-documents", path)]
    assert len(env.publication_calls["create"]) == 1
    assert not env.publication_calls["queue_attempts"]
    assert len(env.publication_calls["notify"]) == (3 if action == "reject" else 2)


@pytest.mark.parametrize("action", ["reject", "cancel"])
def test_bound_negative_cleanup_does_not_require_current_access_to_the_original_content(publication, action):
    env = publication
    submit(env)
    downloads = deepcopy(env.publication_calls["download"])
    env.publication_state["source_allowed"] = False
    env.conversations.change("private-conversation", user_id="another-owner")
    if action == "cancel":
        set_actor(env, REQUESTER)
    response = decide(env, action)
    assert_receipt(response, env, action, "applied", "rejected" if action == "reject" else "cancelled", 200)
    assert env.publication_calls["download"] == downloads
    assert not env.publication_calls["queue_attempts"]


@pytest.mark.parametrize("action", ["reject", "cancel"])
def test_legacy_cleanup_can_enroll_in_an_upload_disabled_but_mutable_destination(publication, action):
    env = publication
    submit(env, legacy=True)
    env.groups["group-a"]["status"] = "upload_disabled"
    if action == "cancel":
        set_actor(env, REQUESTER)
    response = decide(env, action)
    saved = receipt(env)
    assert_receipt(response, env, action, "applied", "rejected" if action == "reject" else "cancelled", 200)
    assert saved["document_version"] == 1
    assert env.target not in env.source.records
    assert len(env.publication_calls["create"]) == 1
    assert not env.publication_calls["queue_attempts"]


@pytest.mark.parametrize("action", ["reject", "cancel"])
def test_cleanup_does_not_promote_a_stale_family_when_selected_current_revision_changes(publication, action):
    env = publication
    current = submit(env)
    older = document(
        "older-revision", revision_family_id=env.target, version=1,
        file_name=current["file_name"], is_current_version=False,
    )
    env.source.create_item(older)
    env.source.change(env.target, version=2, **{BINDING: {**current[BINDING], "document_version": 2}})
    change_receipt(env, document_version=2)
    real_delete = env.group_publication.delete_document_revision
    def became_historical(*args, **kwargs):
        env.source.change(env.target, is_current_version=False)
        env.source.create_item(document(
            "new-current", revision_family_id=env.target, version=3, file_name=current["file_name"],
        ))
        return real_delete(*args, **kwargs)
    env.scoped_monkeypatch.setattr(env.group_publication, "delete_document_revision", became_historical)
    if action == "cancel":
        set_actor(env, REQUESTER)
    response = decide(env, action)
    assert response.status_code == 207, response.get_json()
    assert env.target in env.source.records
    assert env.source.records["older-revision"]["is_current_version"] is False
    assert env.source.records["new-current"]["is_current_version"] is True
    assert env.deleted_chunks == []
    assert env.visibility == []


@pytest.mark.parametrize("action", ["reject", "cancel"])
def test_cleanup_rechecks_membership_before_deleting_chunks_or_persisted_blobs(publication, action):
    env = publication
    submit(env)
    path = f"group-a/revisions/{env.target}/accepted.md"
    env.blobs.put(path)
    env.source.change(env.target, blob_container="group-documents", blob_path=path)
    real_delete = env.group_publication.delete_document_revision
    def revoked(*args, **kwargs):
        if action == "cancel":
            env.groups["group-a"]["users"] = [{"userId": "reader"}]
        else:
            env.groups["group-a"]["documentManagers"] = []
        return real_delete(*args, **kwargs)
    env.scoped_monkeypatch.setattr(env.group_publication, "delete_document_revision", revoked)
    if action == "cancel":
        set_actor(env, REQUESTER)
    response = decide(env, action)
    assert response.status_code in {207, 403}, response.get_json()
    assert env.target in env.source.records
    assert env.blobs.deleted == env.deleted_chunks == []
    assert len(env.publication_calls["notify"]) == 2


@pytest.mark.parametrize("field,value", [
    ("actor_user_id", "reader"), ("request_id", "forged-request"),
    ("destination", {"workspace_scope": "group", "group_id": "group-b"}),
    ("file_name", "forged-name.md"), ("document_id", "forged-document"),
])
def test_v1_receipt_cannot_be_rebound_to_another_actor_request_or_destination(publication, field, value):
    env = publication
    submit(env)
    change_receipt(env, **{field: value})
    response = decide(env, "reject")
    state = sharing(env)
    saved = receipt(env)
    assert response.status_code == 409, response.get_json()
    assert state.get_json()["publication"]["status"] == "unavailable"
    assert not state.get_json()["publication"]["actions"]
    assert "decision" not in saved
    assert env.target in env.source.records
    assert not env.deleted_chunks


def test_real_legacy_hash_and_uuid_are_the_only_enrollment_identity(publication):
    env = publication
    current = submit(env, legacy=True)
    artifact = env.messages.read_item(env.artifact_id, "private-conversation")
    saved = receipt(env)
    identity = {
        "source": {
            "conversation_id": artifact["conversation_id"], "message_id": artifact["id"],
            "blob_container": artifact["blob_container"], "blob_path": artifact["blob_path"],
            "producer": None, "contexts": artifact["metadata"]["analysis_result_contexts"],
            "content_sha256": artifact["metadata"]["generated_artifact_content_sha256"],
        },
        "content_sha256": hashlib.sha256(env.content).hexdigest(),
        "destination": {"workspace_scope": "group", "group_id": "group-a"},
        "actor_user_id": REQUESTER, "request_id": "exact-publication-request",
    }
    expected_key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    expected_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"simplechat-publication:{expected_key}"))
    assert saved["id"] == expected_key
    assert current["id"] == expected_id
    env.content = b"Different artifact bytes"
    response = decide(env, "approve")
    after = receipt(env)
    assert response.status_code == 409
    assert "decision" not in after
    assert BINDING not in env.source.records[env.target]
    assert len(env.publication_calls["create"]) == 1
    assert not env.publication_calls["queue_attempts"]


def test_current_screening_release_proof_still_allows_an_ordinary_publication_approval(publication):
    env = publication
    submit(env)
    env.seed_release(env.source.records[env.target])
    state = sharing(env)
    response = decide(env, "approve")
    assert "approve_artifact" in state.get_json()["actions"]
    assert_receipt(response, env, "approve", "queued", "approved", 202)
    assert env.source.records[env.target]["content_screening"]["state"] == "cleared"
    assert len(env.publication_calls["queue"]) == 1


def test_destination_path_cannot_be_replaced_by_another_group_or_a_forged_scope_payload(publication):
    env = publication
    current = submit(env)
    before = deepcopy(env.source.records)
    wrong_group = decide(env, "approve", group_id="group-b")
    wrong_payload = env.client.post(
        f"{ROOT}/{env.target}/artifact/approve",
        json={"expected_etag": current["_etag"], "group_id": "group-b"},
    )
    wrong_query = env.client.post(
        f"{ROOT}/{env.target}/artifact/approve?group_id=group-b",
        json={"expected_etag": current["_etag"]},
    )
    assert wrong_group.status_code == 403
    assert wrong_payload.status_code == wrong_query.status_code == 400
    assert env.source.records == before
    assert not env.publication_calls["queue_attempts"]


@pytest.mark.parametrize("action", ["reject", "cancel"])
def test_archive_only_cleanup_never_invents_an_unrecorded_current_blob_alias(publication, action):
    env = publication
    current = submit(env)
    archived = f"group-a/revisions/{env.target}/{current['file_name']}"
    unrecorded_alias = f"group-a/{current['file_name']}"
    env.blobs.put(archived)
    env.blobs.put(unrecorded_alias, b"Another document's current bytes")
    env.source.change(env.target, blob_container="group-documents", archived_blob_path=archived)
    if action == "cancel":
        set_actor(env, REQUESTER)
    response = decide(env, action)
    assert_receipt(response, env, action, "applied", "rejected" if action == "reject" else "cancelled", 200)
    assert env.blobs.deleted == [("group-documents", archived)]
    assert ("group-documents", unrecorded_alias) in env.blobs.records


if __name__ == "__main__":
    # The existing canonical suites can be supplied as additional pytest paths.
    # Their optional renderer/model imports are not publication dependencies.
    artifacts = Path.cwd() / "artifacts" / f"m2c-publication-validation-{uuid.uuid4().hex}"
    artifacts.mkdir(parents=True)
    try:
        with pytest.MonkeyPatch.context() as patch:
            isolate_unused_rendering_and_model_dependencies(patch)
            network = Mock(side_effect=AssertionError("Publication validation cannot access the network."))
            patch.setattr(socket, "create_connection", network)
            patch.setattr(socket.socket, "connect", network)
            patch.setattr(tempfile, "tempdir", str(artifacts))
            result = pytest.main([
                str(Path(__file__).resolve()), *sys.argv[1:], "--basetemp", str(artifacts / "pytest"),
            ])
            network.assert_not_called()
    finally:
        shutil.rmtree(artifacts)
    sys.exit(result)
