# test_graph_route_cosmos_response_contracts.py
"""
Owner-runtime contracts for the route modules touched by Graph remediation.
Version: 0.261.456
Implemented in: 0.261.456

The Cosmos inventory fingerprints entire modules. These regressions exercise the
nine unchanged storage consumers whose source-only reviews are invalidated by the
Graph helper edits. Existing SDK-default containers supply real CosmosDict point
responses; query projections stay plain JSON. No storage implementation, shared
double, or domain validator is changed.
"""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cosmos import exceptions
from azure.cosmos._cosmos_responses import CosmosDict
from flask import Flask, jsonify
from werkzeug.datastructures import MultiDict

from collaboration_models import (
    COLLABORATION_KIND,
    get_collaboration_user_state_doc_id,
    normalize_collaboration_user,
)
from functions_stats_windows import (
    build_stats_date_series,
    resolve_bounded_stats_time_window,
    stats_window_response_payload,
    timestamp_to_stats_date_key,
)
from test_file_sync_azure_blob_storage import load_functions
from test_public_workspace_membership_writer_safety import WS_ID, _exec_nested_handlers, _workspace
from test_support.m365 import CosmosContainer
from test_user_profile_idor_authorization import prepare_context


@pytest.fixture(autouse=True)
def flask_json_context():
    with Flask("graph_route_cosmos_contracts").app_context():
        yield


def sdk_profile_module():
    context, module = prepare_context()
    module.exceptions = exceptions
    module.jsonify = jsonify
    module.normalize_collaboration_user = normalize_collaboration_user
    module.get_collaboration_user_state_doc_id = get_collaboration_user_state_doc_id
    return context, module


def user_info_handler(module):
    return _exec_nested_handlers(
        "route_backend_users.py", "register_route_backend_users", {"api_get_user_info"}, module.__dict__,
    )["api_get_user_info"]


def test_authorized_profile_point_response_preserves_sdk_fields_and_etag():
    _, module = sdk_profile_module()
    container = CosmosContainer("id")
    saved = container.create_item(body={
        "id": "actor-user", "display_name": "Actor User", "email": "actor@example.test",
        "settings": {"profileImage": "data:image/png;base64,test"},
    })
    module.cosmos_user_settings_container = container
    actor, target, document = module._read_authorized_user_profile_document("actor-user")

    assert actor == target == "actor-user"
    assert type(document) is CosmosDict
    assert document["_etag"] == saved["_etag"]
    assert type(document["settings"]) is dict
    assert document["settings"]["profileImage"] == "data:image/png;base64,test"


def test_user_info_route_consumes_sdk_point_response_without_graph_fallback():
    _, module = sdk_profile_module()
    container = CosmosContainer("id")
    saved = container.create_item(body={
        "id": "actor-user", "display_name": "Actor User", "email": "actor@example.test",
    })
    module.cosmos_user_settings_container = container
    module.get_valid_access_token = Mock(side_effect=AssertionError("Unexpected Graph fallback"))
    handler = user_info_handler(module)
    response, status = handler("actor-user")
    payload = response.get_json()
    retained = container.read_item(item="actor-user", partition_key="actor-user")

    assert status == 200
    assert payload["id"] == "actor-user"
    assert payload["displayName"] == "Actor User"
    assert payload["email"] == "actor@example.test"
    assert retained["_etag"] == saved["_etag"]
    module.get_valid_access_token.assert_not_called()


@pytest.mark.parametrize("status, allowed", (("accepted", True), ("pending", True), ("removed", False)))
def test_collaboration_profile_relationship_consumes_sdk_member_point_response(status, allowed):
    _, module = sdk_profile_module()
    container = CosmosContainer("user_id")
    conversation_id = "conversation-1"
    for user_id, membership_status in (("actor-user", "accepted"), ("target-user", status)):
        container.create_item(body={
            "id": get_collaboration_user_state_doc_id(user_id, conversation_id),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "conversation_kind": COLLABORATION_KIND,
            "membership_status": membership_status,
        })
    module.cosmos_collaboration_user_state_container = container
    result = module._has_collaboration_profile_relationship("actor-user", "target-user")
    member = container.read_item(
        item=get_collaboration_user_state_doc_id("target-user", conversation_id),
        partition_key="target-user",
    )

    assert result is allowed
    assert type(member) is CosmosDict
    assert member["membership_status"] == status
    assert member["_etag"]


def test_shared_document_profile_relationship_consumes_scalar_query_projection():
    _, module = sdk_profile_module()
    query = Mock(return_value=iter(["shared-document-id"]))
    module.cosmos_user_documents_container = SimpleNamespace(query_items=query)
    result = module._has_shared_document_profile_relationship("actor-user", "target-user")
    parameters = {item["name"]: item["value"] for item in query.call_args.kwargs["parameters"]}

    assert result is True
    assert parameters["@actor_user_id"] == "actor-user"
    assert parameters["@target_user_id"] == "target-user"
    assert query.call_args.kwargs["enable_cross_partition_query"] is True


def test_collaboration_suggestions_consume_sdk_settings_and_plain_directory_rows():
    _, module = sdk_profile_module()
    container = CosmosContainer("id")
    container.create_item(body={"id": "actor-user", "settings": {"recentCollaborators": []}})
    container.create_item(body={
        "id": "target-user", "display_name": "Target User", "email": "target@example.test",
    })
    module.cosmos_user_settings_container = container
    module.get_user_settings = lambda user_id: container.read_item(item=user_id, partition_key=user_id)
    module.request = SimpleNamespace(args=MultiDict({"query": "target"}))
    handler = _exec_nested_handlers(
        "route_backend_users.py", "register_route_backend_users", {"api_collaboration_suggestions"}, module.__dict__,
    )["api_collaboration_suggestions"]
    response, status = handler()
    payload = response.get_json()
    query_rows = list(container.query_items(query="SELECT * FROM c", enable_cross_partition_query=True))

    assert status == 200
    assert payload == {"results": [{
        "user_id": "target-user", "display_name": "Target User",
        "email": "target@example.test", "source": "local",
    }]}
    assert all(type(row) is dict for row in query_rows)


def public_owner_namespace():
    container = CosmosContainer("id")
    container.create_item(body=_workspace(
        name="Public % # One",
        metrics={"document_metrics": {"total_documents": 2, "storage_account_size": 100, "ai_search_size": 50}},
    ))
    workspace = container.read_item(item=WS_ID, partition_key=WS_ID)
    namespace = load_functions(
        "route_backend_public_workspaces.py",
        {"is_user_in_admins", "_member_user_id"},
        {
            "jsonify": jsonify,
            "find_public_workspace_by_id": Mock(return_value=workspace),
            "get_current_user_info": lambda: {"userId": "owner"},
            "request": SimpleNamespace(args=MultiDict()),
            "debug_print": Mock(),
            "is_debug_enabled": lambda: False,
            "resolve_bounded_stats_time_window": resolve_bounded_stats_time_window,
            "build_stats_date_series": build_stats_date_series,
            "stats_window_response_payload": stats_window_response_payload,
            "timestamp_to_stats_date_key": timestamp_to_stats_date_key,
        },
    )
    return container, namespace


def public_handler(name, namespace):
    return _exec_nested_handlers(
        "route_backend_public_workspaces.py", "register_route_backend_public_workspaces", {name}, namespace,
    )[name]


def test_public_discovery_consumes_plain_workspace_query_rows():
    container, namespace = public_owner_namespace()
    namespace["cosmos_public_workspaces_container"] = container
    handler = public_handler("discover_public_workspaces", namespace)
    response, status = handler()
    payload = response.get_json()
    rows = list(container.query_items(query="SELECT * FROM c", enable_cross_partition_query=True))

    assert status == 200
    assert payload == [{"id": WS_ID, "name": "Public % # One", "description": ""}]
    assert type(rows[0]) is dict


def test_public_file_count_consumes_scalar_count_with_sdk_workspace():
    _, namespace = public_owner_namespace()
    query = Mock(return_value=iter([2]))
    namespace["cosmos_public_documents_container"] = SimpleNamespace(query_items=query)
    handler = public_handler("api_public_file_count", namespace)
    response, status = handler(WS_ID)
    payload = response.get_json()

    assert status == 200
    assert payload == {"fileCount": 2}
    assert query.call_args.kwargs["parameters"] == [{"name": "@wsId", "value": WS_ID}]


def test_public_activity_consumes_plain_activity_rows_with_sdk_workspace():
    _, namespace = public_owner_namespace()
    row = {"id": "activity-1", "timestamp": "2026-01-01T12:00:00Z", "activity_type": "document_creation"}
    query = Mock(return_value=iter([row]))
    namespace["cosmos_activity_logs_container"] = SimpleNamespace(query_items=query)
    handler = public_handler("api_public_workspace_activity", namespace)
    response, status = handler(WS_ID)
    payload = response.get_json()

    assert status == 200
    assert payload == [row]
    assert query.call_args.kwargs["parameters"] == [{"name": "@wsId", "value": WS_ID}]


def test_public_stats_consume_sdk_workspace_and_plain_activity_projections():
    _, namespace = public_owner_namespace()
    token_row = {"timestamp": "2026-01-01T12:00:00Z", "usage": {"total_tokens": 25}}
    document_row = {"timestamp": "2026-01-01T12:00:00Z"}
    query = Mock(side_effect=[iter([token_row]), iter([document_row]), iter([document_row]), iter([token_row])])
    namespace["cosmos_activity_logs_container"] = SimpleNamespace(query_items=query)
    namespace["request"] = SimpleNamespace(args=MultiDict({"start_date": "2026-01-01", "end_date": "2026-01-02"}))
    handler = public_handler("api_public_workspace_stats", namespace)
    response, status = handler(WS_ID)
    payload = response.get_json()

    assert status == 200
    assert payload["totalDocuments"] == 2
    assert payload["totalTokens"] == 25
    assert payload["storage"] == {"ai_search_size": 50, "storage_account_size": 100}
    assert payload["documentActivity"] == {"labels": ["1/1", "1/2"], "uploads": [1, 0], "deletes": [1, 0]}
    assert payload["tokenUsage"] == {"labels": ["1/1", "1/2"], "data": [25, 0]}
    assert query.call_count == 4


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
