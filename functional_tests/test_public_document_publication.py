#!/usr/bin/env python3
"""
Functional tests for immutable-target public workspace generated-artifact decisions.
Version: 0.261.148
Implemented in: 0.261.134
Decision link opens the V2 public workspace route: 0.261.148

The scoped public collaboration routes, the public publication adapter, the
shared canonical artifact-publication engine, the shared screening consume-latch
and revision cleanup all run against conditional local stores and exact source
bytes. The workspace is always taken from the path, so a stale active-workspace
preference can never redirect a publication decision. No Azure, model, provider,
or filesystem artifact processing occurs.

Coverage is deliberately focused on what the *public* wrapper owns: per-role and
per-status authorization, requester-only cancel, receipt shaping
(applied/queued/unchanged/partial), etag binding, current-revision-only
enforcement, 400 on malformed input, cross-scope isolation, the public
consume-latch identity rules (contract §5), and the read projector's inline
collaboration actions. The shared engine's own internals are exhaustively
covered by the group publication suite and are not re-tested here.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Dict, Optional
from unittest.mock import Mock
import uuid

import pytest

from test_public_document_management import (  # noqa: F401  (management is a fixture)
    MutablePublicContainer,
    StoreFailure,
    management,
)
from test_public_document_read_apis import (  # noqa: F401  (environment is a fixture)
    MissingRecord,
    document,
    environment,
    get,
    load_real_module,
)
from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub
from test_support.versioning import assert_app_version_at_least

sys.path.insert(0, str(Path(APP_ROOT)))
from functions_artifact_publication_readiness import (  # noqa: E402
    PUBLICATION_SCREENING_CONSUMPTION as CONSUMPTION,
)


ROOT = "/api/public-workspaces/public-a/documents"
BINDING = "generated_artifact_publication_binding"
PROCESSING = "generated_artifact_publication_processing"
OPERATION = "public_document_collaboration_operation"
RECEIPTS = "generated_artifact_workspace_publications"
REQUESTER = "requester"
PRIVATE = "PRIVATE-PUBLICATION-SOURCE"


class PublicReceiptStore(MutablePublicContainer):
    """A conditional container that also serves the message/notification reads
    the canonical engine performs by (id, conversation) partition key."""

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


def _isolate_rendering_and_model(patch):
    patch.setitem(sys.modules, "functions_generated_file_exports", module_stub(
        "functions_generated_file_exports",
        build_saved_analysis_export=Mock(side_effect=AssertionError("Publication must reuse existing artifact bytes.")),
    ))
    patch.setitem(sys.modules, "functions_workflow_context", module_stub(
        "functions_workflow_context", WorkflowContextBudgetError=RuntimeError,
        calculate_workflow_context_budget=Mock(side_effect=AssertionError("Publication must not call a model.")),
    ))
    patch.setitem(sys.modules, "functions_personal_workflows", module_stub(
        "functions_personal_workflows",
        normalize_workflow_publication=Mock(side_effect=AssertionError("No workflow creation.")),
    ))
    patch.setitem(sys.modules, "functions_group", module_stub(
        "functions_group",
        assert_group_role=Mock(side_effect=AssertionError("No group scope in a public decision.")),
        check_group_status_allows_operation=Mock(side_effect=AssertionError("No group scope in a public decision.")),
        find_group_by_id=Mock(side_effect=AssertionError("No group scope in a public decision.")),
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

    # The requester must be a hosting-workspace manager to publish; the deciding
    # manager ("manager") is distinct, so requester-only cancel stays meaningful.
    env.workspaces["public-a"]["documentManagers"] = ["manager", REQUESTER]
    env.workspace_container.records["public-a"]["documentManagers"] = ["manager", REQUESTER]

    env.content = b"# Exact accepted artifact\n\nExisting values: 12.3400\n"
    env.publication_state = {
        "source_allowed": True, "download_hook": None, "queue_hook": None,
        "queue_failure": False, "notification_failure": None,
    }
    env.publication_calls = {
        "create": [], "queue": [], "queue_attempts": [], "download": [], "notify": [], "cleanup": [],
    }
    env.deleted_chunks = []

    env.messages = PublicReceiptStore({})
    env.conversations = PublicReceiptStore({
        "private-conversation": {
            "id": "private-conversation", "user_id": REQUESTER, "private_source": PRIVATE,
        },
    })
    env.notices = PublicReceiptStore({})
    for name, value in (
        ("cosmos_messages_container", env.messages),
        ("cosmos_conversations_container", env.conversations),
        ("cosmos_notifications_container", env.notices),
    ):
        patch.setattr(env.config, name, value, raising=False)

    # Real personal-conversation authorization without importing unrelated
    # collaboration storage/bootstrap dependencies.
    conversation_helpers = {"COLLABORATION_SOURCE_KIND": "collaboration_source"}
    execute_functions("functions_collaboration.py", {
        "is_collaboration_source_conversation", "get_collaboration_conversation_for_source",
        "build_conversation_participation_context",
    }, conversation_helpers)
    patch.setitem(sys.modules, "functions_collaboration", module_stub(
        "functions_collaboration", **conversation_helpers,
    ))
    _isolate_rendering_and_model(patch)

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
            values["document_id"], "public-a", user_id=values["user_id"],
            file_name=values["file_name"], status=values["status"],
            title="Published artifact", abstract="Published artifact abstract",
            authors=["Publisher"], keywords=["published"],
            tags=["published"], percentage_complete=0,
            blob_container="public-documents", blob_path=f"public-a/{values['file_name']}",
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
        # Only the exact executing collaboration may write the source here.
        fence.assert_public_document_source_writable(current)
        if OPERATION in current:
            operation = current[OPERATION]
            assert operation["phase"] == "executing"
        assert values["public_workspace_id"] == current["public_workspace_id"]
        assert values["owner_user_id"] == REQUESTER
        assert values["file_content_bytes"] == env.content
        env.publication_calls["queue"].append(deepcopy(values))
        if env.publication_state["queue_hook"]:
            env.publication_state["queue_hook"]()
        if env.publication_state["queue_failure"]:
            raise TimeoutError(PRIVATE)
        env.document_helpers["update_document"](
            document_id=current["id"], user_id=REQUESTER,
            public_workspace_id=current["public_workspace_id"], status="Queued for processing",
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
        return notify(public_workspace_id=target, notification_type=kind, title=title, message=message, **values)

    def cleanup_notices(**values):
        env.publication_calls["cleanup"].append(deepcopy(values))
        for key, notice in list(env.notices.records.items()):
            if (
                notice["notification_type"] in values["notification_types"]
                and all(notice["metadata"].get(field) == value
                        for field, value in values["metadata_filters"].items())
            ):
                del env.notices.records[key]

    def delete_revision(user_id, document_id, delete_mode="all_versions", group_id=None,
                        public_workspace_id=None, *, family_documents=None, strict=False,
                        operation_guard=None, persisted_sources_only=False):
        if operation_guard:
            operation_guard()
        current = env.source.records.get(document_id)
        if current is None:
            raise MissingRecord()
        blob_key = (current.get("blob_container"), current.get("blob_path"))
        persisted = current.get("blob_path_mode") == "archived_revision"
        if operation_guard:
            operation_guard(document_id)
        if persisted and current.get("blob_path"):
            env.blobs.pop(blob_key, None)
            env.deleted_blobs.append(blob_key)
        env.source.delete_item(document_id, document_id)
        env.deleted_chunks.append((document_id,))
        return {"deleted_document_ids": [document_id], "promoted_document_id": None}

    env.deleted_blobs = []

    docs = sys.modules["functions_documents"]
    patch.setattr(docs, "create_document", create_destination)
    patch.setattr(docs, "update_document", env.document_helpers["update_document"])
    patch.setattr(docs, "delete_document_revision", delete_revision)
    patch.setattr(docs, "allowed_file", lambda name: name.endswith(".md"))
    env.document_helpers["delete_document_revision"] = delete_revision

    operations_stub = module_stub(
        "functions_simplechat_operations",
        download_blob_content=download,
        queue_generated_document_processing=queue,
        _write_temp_generated_file=Mock(side_effect=AssertionError(
            "Publication contract tests do not create temporary files.",
        )),
        **lifecycle_helpers,
    )
    patch.setitem(sys.modules, "functions_simplechat_operations", operations_stub)

    notifications = module_stub(
        "functions_notifications",
        create_notification=notify, create_group_notification=Mock(side_effect=AssertionError("No group destination.")),
        create_public_workspace_notification=workspace_notice,
        delete_notifications_by_metadata=cleanup_notices,
    )
    patch.setitem(sys.modules, "functions_notifications", notifications)
    patch.setitem(sys.modules, "utils_cache", module_stub(
        "utils_cache",
        invalidate_public_workspace_search_cache=Mock(),
        invalidate_group_search_cache=Mock(), invalidate_personal_search_cache=Mock(),
    ))
    patch.setitem(sys.modules, "functions_activity_logging", module_stub(
        "functions_activity_logging",
        log_document_metadata_update_transaction=Mock(), log_document_deletion_transaction=Mock(),
    ))

    canonical = load_real_module(patch, "functions_artifact_publication")
    patch.setattr(canonical, "CosmosResourceNotFoundError", MissingRecord)
    patch.setattr(canonical, "CosmosHttpResponseError", StoreFailure)
    env.canonical = canonical

    env.publication_module = load_real_module(patch, "functions_public_document_publication")
    env.collaboration_module = load_real_module(patch, "functions_public_document_collaboration")
    route = load_real_module(patch, "route_backend_public_document_collaboration")
    patch.setattr(env.publication_module, "publication", canonical)
    patch.setattr(env.publication_module, "delete_document_revision", delete_revision)
    patch.setattr(env.publication_module, "delete_notifications_by_metadata", cleanup_notices)
    patch.setattr(env.collaboration_module, "cosmos_public_documents_container", env.source, raising=False)

    from flask import Blueprint
    from functions_authentication import user_required_blueprint
    blueprint = Blueprint("backend_public_document_collaboration", __name__)
    blueprint.before_request(user_required_blueprint())
    route.register_route_backend_public_document_collaboration(blueprint)
    env.app.register_blueprint(blueprint)

    set_actor(env, "manager")
    yield env


def set_actor(env, actor):
    with env.client.session_transaction() as state:
        state["user"] = {"oid": actor, "roles": ["User"]}


def submit(env, *, legacy=False, request_id="exact-publication-request"):
    result = env.canonical.publish_generated_chat_artifact_for_user(
        REQUESTER, conversation_id="private-conversation", message_id=env.artifact_id,
        destination={"workspace_scope": "public", "public_workspace_id": "public-a"},
        request_id=request_id, requester_display_name="Requester",
    )
    env.target = result["document"]["id"]
    env.receipt_id = result["publication"]["id"]
    if not legacy:
        current = env.source.read_item(env.target, env.target)
        env.canonical.enroll_legacy_artifact_publication(
            current,
            operation_guard=lambda: env.access.require_public_document_read_context(REQUESTER, "public-a"),
        )
    return env.source.read_item(env.target, env.target)


def receipt(env):
    message = env.messages.read_item(env.artifact_id, "private-conversation")
    return message["metadata"][RECEIPTS][env.receipt_id]


def change_receipt(env, **changes):
    message = env.messages.read_item(env.artifact_id, "private-conversation")
    metadata = deepcopy(message["metadata"])
    metadata[RECEIPTS][env.receipt_id].update(deepcopy(changes))
    env.messages.change(env.artifact_id, metadata=metadata)


def state(env, document_id=None):
    return env.client.get(f"{ROOT}/{document_id or env.target}/publication")


def decide(env, action, *, etag=None, workspace_id="public-a", body=None):
    if body is None:
        if etag is None:
            etag = env.source.read_item(env.target, env.target)["_etag"]
        body = {"expected_etag": etag}
    return env.client.post(
        f"/api/public-workspaces/{workspace_id}/documents/{env.target}/artifact/{action}", json=body,
    )


def assert_receipt(response, env, action, status, state_value, http_status):
    value = response.get_json()
    assert response.status_code == http_status, value
    assert set(value) == {"schema_version", "public_workspace_id", "document_id", "action", "status", "state", "errors"}
    assert value["schema_version"] == 1
    assert value["public_workspace_id"] == "public-a"
    assert value["document_id"] == env.target
    assert value["action"] == f"{action}_artifact"
    assert value["status"] == status
    assert value["state"] == state_value
    assert isinstance(value["errors"], list)
    if status != "partial":
        assert value["errors"] == []
    assert PRIVATE not in json.dumps(value)
    return value


def test_implementation_version_is_present():
    assert_app_version_at_least("0.261.134")


@pytest.mark.parametrize("action,state_value", [
    ("approve", "approved"), ("reject", "rejected"), ("cancel", "cancelled"),
])
def test_real_public_decisions_preserve_exact_destination_and_durable_receipt(publication, action, state_value):
    env = publication
    submit(env)
    before_other = deepcopy(env.source.records["document-b"])
    if action == "cancel":
        set_actor(env, REQUESTER)
    response = decide(env, action)
    assert_receipt(response, env, action, "queued" if action == "approve" else "applied", state_value,
                   202 if action == "approve" else 200)
    saved = receipt(env)
    assert saved["decision"]["choice"] == state_value
    assert saved["decision"]["actor_user_id"] == (REQUESTER if action == "cancel" else "manager")
    assert env.source.records["document-b"] == before_other
    assert len(env.publication_calls["create"]) == 1
    assert len(env.publication_calls["queue"]) == (1 if action == "approve" else 0)
    if action != "approve":
        assert env.target not in env.source.records
        assert [item[0] for item in env.deleted_chunks] == [env.target]
    else:
        assert env.source.records[env.target][OPERATION]["phase"] == "complete"
    if action != "cancel":
        notice = env.publication_calls["notify"][-1]
        assert notice["link_url"] == f"/v2/public/public-a/documents?document_id={env.target}"
        assert notice["metadata"]["publication_receipt_id"] == env.receipt_id
    env.user_settings.assert_not_called()


def test_refreshed_approval_is_idempotent_but_blind_replay_is_a_conflict(publication):
    env = publication
    initial = submit(env)
    first = decide(env, "approve", etag=initial["_etag"])
    stale = decide(env, "approve", etag=initial["_etag"])
    fresh = state(env)
    repeated = decide(env, "approve", etag=fresh.get_json()["etag"])
    assert_receipt(first, env, "approve", "queued", "approved", 202)
    assert stale.status_code == 409
    assert_receipt(repeated, env, "approve", "unchanged", "approved", 200)
    assert len(env.publication_calls["create"]) == len(env.publication_calls["queue"]) == 1


@pytest.mark.parametrize("action", ["approve", "reject", "cancel"])
@pytest.mark.parametrize("actor", ["owner", "admin", "manager", "reader", REQUESTER, "outsider"])
def test_manager_decisions_and_requester_cancel_do_not_borrow_each_others_authority(publication, action, actor):
    env = publication
    submit(env)
    set_actor(env, actor)
    before = deepcopy(env.source.records)
    response = decide(env, action)
    permitted = actor == REQUESTER if action == "cancel" else actor in {"owner", "admin", "manager", REQUESTER}
    saved = receipt(env)
    if permitted:
        assert response.status_code == (202 if action == "approve" else 200), response.get_json()
        assert saved["decision"]["actor_user_id"] == actor
    else:
        assert response.status_code == 403, response.get_json()
        assert "decision" not in saved
        assert env.source.records == before
        assert env.publication_calls["queue_attempts"] == []


@pytest.mark.parametrize("action", ["approve", "reject", "cancel"])
@pytest.mark.parametrize("status", ["active", "upload_disabled", "locked", "inactive", "unknown"])
def test_selected_destination_status_controls_publication_not_active_preferences(publication, action, status):
    env = publication
    submit(env)
    env.workspaces["public-a"]["status"] = status
    env.workspace_container.records["public-a"]["status"] = status
    if action == "cancel":
        set_actor(env, REQUESTER)
    before = deepcopy(env.source.records)
    response = decide(env, action)
    allowed = status == "active" or (status == "upload_disabled" and action != "approve")
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


def test_historical_pending_request_never_approves_an_accessible_sibling(publication):
    env = publication
    current = submit(env)
    sibling = document("newer-publication-revision", version=2, revision_family_id=env.target,
                       file_name=current["file_name"])
    env.source.create_item(sibling)
    env.source.change(env.target, is_current_version=False)
    view = state(env)
    response = decide(env, "approve")
    saved = receipt(env)
    assert "approve_artifact" not in view.get_json()["actions"]
    assert "reject_artifact" in view.get_json()["actions"]
    assert response.status_code == 409, response.get_json()
    assert "decision" not in saved
    assert not env.publication_calls["queue_attempts"]
    assert env.source.records[sibling["id"]]["version"] == 2


@pytest.mark.parametrize("body,expected", [
    ({}, 400),
    ({"expected_etag": ""}, 400),
    ({"expected_etag": 42}, 400),
    ({"expected_etag": "e", "extra": "x"}, 400),
    ("not-json", 400),
])
def test_malformed_decision_bodies_are_rejected_without_a_fallback(publication, body, expected):
    env = publication
    submit(env)
    if body == "not-json":
        response = env.client.post(
            f"{ROOT}/{env.target}/artifact/approve", data="raw", content_type="text/plain",
        )
    else:
        response = decide(env, "approve", body=body)
    assert response.status_code == expected, response.get_json()
    assert "decision" not in receipt(env)
    assert env.publication_calls["queue_attempts"] == []


def test_decision_routes_reject_query_parameters(publication):
    env = publication
    submit(env)
    etag = env.source.read_item(env.target, env.target)["_etag"]
    response = env.client.post(
        f"{ROOT}/{env.target}/artifact/approve?scope=public-b", json={"expected_etag": etag},
    )
    assert response.status_code == 400, response.get_json()
    assert "decision" not in receipt(env)


def test_publication_read_rejects_query_parameters_and_body(publication):
    env = publication
    submit(env)
    assert env.client.get(f"{ROOT}/{env.target}/publication?x=1").status_code == 400
    assert env.client.get(
        f"{ROOT}/{env.target}/publication", data=b"body", content_type="application/json",
    ).status_code == 400


def test_cross_scope_document_cannot_be_decided_through_the_public_route(publication):
    env = publication
    submit(env)
    # A document that belongs to a *group*, not this public workspace, can never
    # be decided through the public collaboration route even if the id is known.
    env.source.change(env.target, public_workspace_id="other-public")
    response = decide(env, "reject")
    assert response.status_code in {403, 404}, response.get_json()
    assert "decision" not in receipt(env)
    assert env.publication_calls["queue_attempts"] == []


def test_unknown_workspace_is_not_served_by_the_publication_route(publication):
    env = publication
    submit(env)
    etag = env.source.read_item(env.target, env.target)["_etag"]
    response = env.client.post(
        f"/api/public-workspaces/ghost-ws/documents/{env.target}/artifact/reject",
        json={"expected_etag": etag},
    )
    assert response.status_code in {403, 404}, response.get_json()
    assert "decision" not in receipt(env)


def test_ambiguous_queue_acknowledgement_is_reconciled_not_a_second_job(publication):
    env = publication
    submit(env)
    env.publication_state["queue_failure"] = True
    first = decide(env, "approve")
    first_view = state(env)
    first_saved = receipt(env)
    env.publication_state["queue_failure"] = False
    current = env.source.read_item(env.target, env.target)
    env.source.change(env.target, **{
        PROCESSING: {"binding": deepcopy(current[BINDING]), "state": "running"},
    })
    reconciled = decide(env, "approve")
    final_saved = receipt(env)
    assert_receipt(first, env, "approve", "partial", "approval_failed", 207)
    assert first_saved["decision"]["choice"] == "approved"
    assert first_saved["stages"]["approval_queue"] == "started"
    projection = first_view.get_json()
    assert projection["publication"]["status"] == "approval_failed"
    assert projection["publication"]["actions"] == ["approve_artifact"]
    assert "reject_artifact" not in projection["actions"]
    assert_receipt(reconciled, env, "approve", "unchanged", "approved", 200)
    assert final_saved["stages"]["approval_queue"] == "complete"
    assert len(env.publication_calls["create"]) == len(env.publication_calls["queue"]) == 1


@pytest.mark.parametrize("actor,expected", [
    ("manager", {"inspect", "approve_artifact", "reject_artifact"}),
    (REQUESTER, {"inspect", "approve_artifact", "reject_artifact", "cancel_artifact"}),
    ("reader", {"inspect"}),
])
def test_publication_state_computes_actions_from_current_authority(publication, actor, expected):
    env = publication
    submit(env)
    set_actor(env, actor)
    response = state(env)
    value = response.get_json()
    assert response.status_code == 200, value
    assert set(value) == {
        "schema_version", "public_workspace_id", "document_id", "document_version",
        "etag", "actions", "publication",
    }
    assert set(value["actions"]) == expected
    assert set(value["publication"]["actions"]) == expected - {"inspect"}
    assert value["publication"]["is_requester"] is (actor == REQUESTER)
    assert value["publication"]["status"] == "pending_approval"
    serialized = json.dumps(value)
    for secret in (PRIVATE, "private-conversation", "private-artifact", "blob_path", RECEIPTS, BINDING):
        assert secret not in serialized


@pytest.mark.parametrize("surface", ["list", "detail", "versions"])
def test_pending_request_exposes_inline_collaboration_actions_but_no_management_actions(publication, surface):
    env = publication
    submit(env)
    set_actor(env, "manager")
    if surface == "list":
        response = get(env, ROOT, page_size=100)
        rows = response.get_json()["documents"]
    elif surface == "detail":
        response = get(env, f"{ROOT}/{env.target}")
        rows = [response.get_json()]
    else:
        response = get(env, f"{ROOT}/{env.target}/versions")
        rows = response.get_json()["versions"]
    assert response.status_code == 200, response.get_json()
    row = next(item for item in rows if item["id"] == env.target)
    assert row["generated_artifact_promotion_status"] == "pending_approval"
    assert row["document_actions"] == []
    assert set(row["document_collaboration_actions"]) >= {"inspect", "approve_artifact", "reject_artifact"}
    assert "share" not in row["document_collaboration_actions"]
    assert PRIVATE not in json.dumps(row)
    assert BINDING not in row
    assert not env.publication_calls["queue"]


# --- Contract §5: the public consume-latch stores operation identity, not a
# boolean, and a reserved scan_id is identity not admission evidence. These
# exercise the real public predicate directly, independent of screening state.

def _executing_operation(**overrides):
    operation = {
        "schema_version": 1, "id": "op-1", "action": "approve_artifact", "phase": "executing",
        "actor_user_id": REQUESTER, "actor_public_workspace_id": "public-a",
        "source_public_workspace_id": "public-a", "document_id": "doc-1", "document_version": 3,
        "execution_token": "token-1",
    }
    operation.update(overrides)
    return operation


def _latch_document(operation):
    return {
        "id": "doc-1", "version": 3, "public_workspace_id": "public-a",
        OPERATION: operation,
    }


def _latch_receipt(**overrides):
    consumption = {"operation_id": "op-1", "fingerprint": "fp"}
    consumption.update(overrides.pop("consumption", {}))
    receipt = {CONSUMPTION: consumption, "stages": {}}
    receipt.update(overrides)
    return receipt


def test_consume_latch_returns_the_operation_id_when_identity_matches(publication):
    env = publication
    retry = env.publication_module._bootstrap_retry_operation_id(
        _latch_document(_executing_operation()), _latch_receipt(), REQUESTER,
    )
    assert retry == "op-1"


@pytest.mark.parametrize("mutation", [
    {"consumption": {"operation_id": "different-op"}},
    {"consumption": {"scan_id": "reserved-scan"}},
    {"stages": {"approval_queue": "started"}},
])
def test_consume_latch_rejects_non_identity_or_progressed_receipts(publication, mutation):
    env = publication
    retry = env.publication_module._bootstrap_retry_operation_id(
        _latch_document(_executing_operation()), _latch_receipt(**mutation), REQUESTER,
    )
    assert retry is None


@pytest.mark.parametrize("operation_change", [
    {"phase": "complete"},
    {"actor_user_id": "someone-else"},
    {"source_public_workspace_id": "other-public"},
    {"action": "reject_artifact"},
])
def test_consume_latch_rejects_operations_that_are_not_the_executing_approval(publication, operation_change):
    env = publication
    retry = env.publication_module._bootstrap_retry_operation_id(
        _latch_document(_executing_operation(**operation_change)), _latch_receipt(), REQUESTER,
    )
    assert retry is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
