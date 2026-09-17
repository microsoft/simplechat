# test_action_auth_execution.py
"""
Functional regressions for private action authentication execution boundaries.
Version: 0.261.107
Implemented in: 0.261.107

Execute the real route/guard functions with isolated storage and provider seams.
Authentication must happen before messages, streams, or executable plans start.
"""

import ast
import json
import logging
import time
from pathlib import Path
from importlib.metadata import version
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import werkzeug
from jsonschema import Draft7Validator
from flask import Flask, g, jsonify, request, session

from test_support.agent_delegation import execute_functions


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"


def execute_route(filename, name, namespace):
    """Extract a registrar's nested route; route policy has its own coverage."""
    tree = ast.parse((APP_ROOT / filename).read_text(encoding="utf-8"))
    routes = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(routes) == 1
    route = routes[0]
    route.decorator_list = []
    exec(compile(ast.Module(body=[route], type_ignores=[]), filename, "exec"), namespace)


class ActionCredentialsRequired(RuntimeError):
    def to_payload(self):
        return {
            "error": "Connect your personal identity.",
            "status": "credentials_required",
            "request_id": "private-request",
            "requirements": [],
        }


class ActionAuthConflict(ValueError):
    pass


class StorageError(RuntimeError):
    pass


class ActionAuthStorageError(RuntimeError):
    pass


@pytest.fixture
def environment(monkeypatch):
    # Match the shared harness for Flask 2 test clients with newer Werkzeug.
    monkeypatch.setattr(werkzeug, "__version__", version("werkzeug"), raising=False)
    app = Flask(__name__)
    app.secret_key = "synthetic-test-session"
    authorize = Mock(return_value={"request_id": "private-request"})
    namespace = {
        "g": g, "json": json, "jsonify": jsonify, "logging": logging, "log_event": Mock(),
        "ActionCredentialsRequired": ActionCredentialsRequired,
        "ActionAuthConflict": ActionAuthConflict, "AzureError": StorageError,
        "ActionAuthStorageError": ActionAuthStorageError,
        "authorize_action_auth_execution": authorize,
    }
    execute_functions("functions_action_auth_execution.py", {
        "action_auth_control_payload", "action_auth_error_response", "_action_auth_guard_stamp", "enforce_action_auth_request",
    }, namespace)
    return app, namespace, authorize


def test_nested_bridge_reuses_only_the_same_actor_request_claim(environment):
    app, namespace, authorize = environment
    guard = namespace["enforce_action_auth_request"]
    with app.test_request_context():
        payload = {"action_auth_request_id": "private-request", "agent_info": {"id": "agent"}}
        assert guard("bob", payload) is None
        assert guard("bob", {**payload, "conversation_id": "hidden-source"}) is None
        assert authorize.call_count == 1
        assert guard("alice", payload) is None
        assert authorize.call_count == 2
        assert authorize.call_args.args[0] == "alice"
    with app.test_request_context():
        assert guard("bob", payload) is None
        assert authorize.call_count == 3


@pytest.mark.parametrize("error,status", [
    (ActionCredentialsRequired("private diagnostic"), 409),
    (ActionAuthConflict("private diagnostic"), 409),
    (PermissionError("private diagnostic"), 403),
    (LookupError("private diagnostic"), 404),
    (ValueError("private diagnostic"), 400),
    (StorageError("private diagnostic"), 503),
    (ActionAuthStorageError("private diagnostic"), 503),
])
def test_guard_returns_private_safe_errors_without_claiming(environment, error, status):
    app, namespace, authorize = environment
    authorize.side_effect = error
    with app.test_request_context():
        response, actual_status = namespace["enforce_action_auth_request"](
            "bob", {"action_auth_request_id": "private-request"},
        )
        assert actual_status == status
        assert response.headers["Cache-Control"] == "no-store"
        assert "private diagnostic" not in response.get_data(as_text=True)
        assert getattr(g, "action_auth_verified_request", None) is None
        if isinstance(error, ActionCredentialsRequired):
            assert response.json["type"] == "action_credentials_required"
            assert response.json["execution_started"] is False
    assert "private diagnostic" not in str(namespace["log_event"].call_args_list)


def test_runtime_control_is_distinct_from_an_initial_deferred_send(environment):
    app, namespace, _ = environment
    with app.test_request_context():
        response, status = namespace["action_auth_error_response"](
            ActionCredentialsRequired(), execution_started=True,
        )
        assert status == 409
        assert response.json["execution_started"] is True
        assert response.json["error_code"] == "action_credentials_required"


def test_noop_gate_does_not_mint_a_trusted_receipt_from_client_input(environment):
    app, namespace, authorize = environment
    authorize.return_value = None
    with app.test_request_context():
        assert namespace["enforce_action_auth_request"]("bob", {"action_auth_request_id": "invented"}) is None
        assert getattr(g, "action_auth_verified_request", None) is None


def test_model_only_new_conversation_does_not_query_uncreated_auth_context(environment):
    app, namespace, authorize = environment
    with app.test_request_context():
        assert namespace["enforce_action_auth_request"]("bob", {"conversation_id": "server-generated"}) is None
    authorize.assert_not_called()


def test_nested_legacy_agent_reuses_check_before_new_conversation_storage(environment):
    app, namespace, authorize = environment
    authorize.return_value = None
    with app.test_request_context():
        guard = namespace["enforce_action_auth_request"]
        initial = {"agent_info": {"id": "legacy-agent"}, "conversation_id": None}
        assert guard("bob", initial) is None
        assert guard("bob", {**initial, "conversation_id": "server-generated"}) is None
        assert authorize.call_count == 1
        assert guard("bob", {"agent_info": {"id": "different-agent"}}) is None
        assert authorize.call_count == 2

def test_preparation_validates_without_consuming_an_execution_receipt(environment):
    app, namespace, authorize = environment
    with app.test_request_context():
        payload = {"action_auth_request_id": "private-request"}
        assert namespace["enforce_action_auth_request"]("bob", payload, claim=False) is None
        authorize.assert_called_once_with("bob", payload, claim=False)
        assert getattr(g, "action_auth_verified_request", None) is None


def test_runtime_control_retains_safe_action_reference_for_independent_repair(environment):
    _, namespace, _ = environment
    error = ActionCredentialsRequired()
    error.action_ref = "action:v1:global:Z2xvYmFs:eWFtY3M"
    payload = namespace["action_auth_control_payload"](error, execution_started=True)
    assert payload["action_ref"] == error.action_ref
    assert payload["execution_started"] is True


@pytest.mark.parametrize("error_type", [ActionCredentialsRequired, ActionAuthStorageError])
def test_authentication_failures_stop_kernel_work_and_never_take_model_fallback(environment, error_type):
    _, namespace, _ = environment
    error = error_type()
    budget = Mock()
    namespace.update({
        "current_agent_execution": lambda: SimpleNamespace(budget=budget),
        "plugin_name": "Yamcs",
        "sanitize_plugin_invocation_value": lambda value, **kwargs: value,
        "FoundryAgentUserAuthenticationRequired": type("FoundryAuthRequired", (RuntimeError,), {}),
        "delegation_budget": SimpleNamespace(attempts=0),
        "gpt_model": "model",
    })
    execute_route("semantic_kernel_plugins/plugin_invocation_logger.py", "_log_failure", namespace)
    namespace["_log_failure"]("read", error, 1.0)
    budget.require_authentication.assert_called_once_with(error)
    execute_route("route_backend_chats.py", "try_fallback_chain", namespace)
    fallback = Mock()
    error_handler = Mock()
    with pytest.raises(error_type):
        namespace["try_fallback_chain"]([
            {"name": "agent", "func": Mock(side_effect=error), "on_success": Mock(), "on_error": error_handler},
            {"name": "model fallback", "func": fallback, "on_success": Mock()},
        ])
    error_handler.assert_not_called()
    fallback.assert_not_called()


@pytest.mark.parametrize("function_name", [
    "chat_api", "chat_stream_api", "chat_document_action_stream_api", "chat_analyze_stream_api",
])
def test_chat_stops_before_stream_or_message_creation(environment, function_name):
    app, namespace, authorize = environment
    authorize.side_effect = ActionCredentialsRequired()
    streams = Mock()
    namespace.update({
        "request": request, "session": session, "time": time,
        "get_current_user_id": lambda: session["user"]["oid"],
        "get_current_user_info": lambda: {},
        "get_settings": lambda: {},
        "CHAT_STREAM_REGISTRY": streams,
    })
    execute_route("route_backend_chats.py", function_name, namespace)
    app.add_url_rule("/probe", view_func=namespace[function_name], methods=["POST"])
    client = app.test_client()
    with client.session_transaction() as values:
        values["user"] = {"oid": "bob"}
    response = client.post("/probe", json={
        "message": "Read telemetry.", "user_id": "alice",
        "agent_info": {"id": "agent", "is_global": True},
        "action_auth_request_id": "private-request",
    })
    assert response.status_code == 409
    assert response.json["error_code"] == "action_credentials_required"
    assert authorize.call_args.args[0] == "bob"
    streams.start_session.assert_not_called()


def test_collaboration_checks_submitter_before_source_creation_and_broadcast(environment):
    app, namespace, authorize = environment
    authorize.side_effect = ActionCredentialsRequired()
    participants = Mock()
    source = Mock()
    messages = Mock()
    events = Mock()
    namespace.update({
        "request": request, "session": session,
        "_require_collaboration_feature_enabled": Mock(),
        "_get_current_collaboration_user": lambda: {"user_id": session["user"]["oid"]},
        "get_collaboration_conversation": lambda _: {"created_by_user_id": "alice"},
        "assert_user_can_participate_in_collaboration_conversation": participants,
        "ensure_collaboration_source_conversation": source,
        "persist_collaboration_message": messages,
        "COLLABORATION_EVENT_REGISTRY": events,
        "COLLABORATION_KIND": "collaboration",
    })
    execute_route("route_backend_collaboration.py", "stream_collaboration_message_api", namespace)
    app.add_url_rule(
        "/probe/<conversation_id>", view_func=namespace["stream_collaboration_message_api"], methods=["POST"],
    )
    client = app.test_client()
    with client.session_transaction() as values:
        values["user"] = {"oid": "bob"}
    response = client.post("/probe/shared", json={
        "message": "Read telemetry.", "agent_info": {"id": "agent", "is_global": True},
        "action_auth_request_id": "private-request",
    })
    assert response.status_code == 409
    assert participants.call_args.args[0] == "bob"
    actor, context = authorize.call_args.args
    assert actor == "bob"
    assert context["conversation_id"] == "shared"
    assert context["conversation_kind"] == "collaboration"
    source.assert_not_called()
    messages.assert_not_called()
    events.publish.assert_not_called()


def test_saved_plan_checks_credentials_before_execution_claim(environment):
    app, namespace, authorize = environment
    authorize.side_effect = ActionCredentialsRequired()
    claim = Mock()
    namespace.update({
        "request": request, "_text": lambda value: str(value or ""),
        "get_current_user_id": lambda: "bob", "get_settings": lambda: {},
        "_orchestration_enabled": lambda _: True,
        "get_orchestration_run": lambda *args, **kwargs: {
            "id": "run", "conversation_id": "conversation", "status": "draft", "plan": {},
        },
        "_conversation_context_for_run": lambda *args: {},
        "PLAN_STATUS_RUNNING": "running", "PLAN_STATUS_COMPLETED": "completed",
        "claim_plan_run": claim,
    })
    execute_route("route_backend_orchestration.py", "orchestration_run", namespace)
    app.add_url_rule("/probe", view_func=namespace["orchestration_run"], methods=["POST"])
    response = app.test_client().post("/probe", json={
        "run_id": "run", "conversation_id": "conversation", "action_auth_request_id": "private-request",
    })
    assert response.status_code == 409
    assert authorize.call_args.args[0] == "bob"
    claim.assert_not_called()


@pytest.mark.parametrize("function_name", ["retry_message", "edit_message"])
def test_replay_checks_credentials_before_deactivating_existing_messages(environment, function_name):
    app, namespace, authorize = environment
    authorize.side_effect = ActionCredentialsRequired()
    original = {
        "id": "message", "conversation_id": "conversation", "role": "user", "content": "Original request",
        "metadata": {
            "user_info": {"user_id": "bob"},
            "thread_info": {"thread_id": "thread", "thread_attempt": 1, "active_thread": True},
            "agent_selection": {"agent_id": "agent", "selected_agent": "mission", "is_global": True},
        },
    }
    messages = Mock()
    messages.query_items.return_value = [original]
    namespace.update({
        "request": request, "get_current_user_id": lambda: "bob",
        "cosmos_messages_container": messages,
    })
    execute_functions("route_backend_conversations.py", {"_build_replayed_agent_selection"}, namespace)
    execute_route("route_backend_conversations.py", function_name, namespace)
    app.add_url_rule("/probe/<message_id>", view_func=namespace[function_name], methods=["POST"])
    response = app.test_client().post("/probe/message", json={
        "content": "Edited request", "action_auth_request_id": "private-request", "user_id": "alice",
    })
    assert response.status_code == 409
    actor, payload = authorize.call_args.args
    assert actor == "bob"
    assert payload["agent_info"]["id"] == "agent"
    assert payload["conversation_id"] == "conversation"
    assert authorize.call_args.kwargs["claim"] is False
    assert original["metadata"]["thread_info"]["active_thread"] is True
    messages.upsert_item.assert_not_called()


def test_replayed_agent_selection_uses_stable_ids_from_legacy_metadata():
    namespace = {}
    execute_functions("route_backend_conversations.py", {"_build_replayed_agent_selection"}, namespace)
    selection = namespace["_build_replayed_agent_selection"]({
        "agent_selection": {"agent_id": "stable-id", "selected_agent": "old-name", "is_global": True},
    })
    assert selection["id"] == "stable-id"
    assert selection["name"] == "old-name"
    assert selection["is_global"] is True
    assert namespace["_build_replayed_agent_selection"]({}) is None


def test_auth_requests_are_excluded_from_legacy_backup_export():
    records = [
        {"id": "binding", "record_type": "binding"},
        {"id": "private-request", "record_type": "request"},
    ]
    container = Mock()
    container.query_items.return_value = records
    namespace = {"_strip_cosmos_system_fields": lambda value: dict(value)}
    execute_functions("functions_data_management.py", {"_iter_cosmos_container_items"}, namespace)
    exported = list(namespace["_iter_cosmos_container_items"](container, record_type="binding"))
    assert exported == records[:1]
    assert "c.record_type = @record_type" in container.query_items.call_args.kwargs["query"]
    container.query_items.return_value = records
    assert list(namespace["_iter_cosmos_container_items"](container)) == records


@pytest.mark.parametrize("selection", [{"mode": "all"}, {"mode": "selected", "ids": ["bob"]}])
def test_auth_migration_filters_source_and_destination_records(selection):
    records = [
        {"id": "binding", "user_id": "bob", "record_type": "binding"},
        {"id": "private-request", "user_id": "bob", "record_type": "request"},
    ]
    container = Mock()
    container.query_items.return_value = records
    definition = {
        "container_attr": "auth_state", "partition_key_path": "/user_id",
        "filter_field": "user_id", "record_type_filter": "binding",
    }
    namespace = {
        "app_config": SimpleNamespace(auth_state=container),
        "_strip_cosmos_system_fields": lambda value: dict(value),
        "_get_selected_scope_filter_fields": lambda _: ["user_id"],
        "_build_selected_scope_filter_clause": lambda _: "c.user_id = @selected_id",
    }
    execute_functions("functions_data_management.py", {
        "_iter_selected_cosmos_records", "_iter_target_cosmos_records",
    }, namespace)
    assert list(namespace["_iter_selected_cosmos_records"](definition, selection)) == records[:1]
    assert list(namespace["_iter_target_cosmos_records"](container, definition, selection)) == records[:1]


def test_requirement_schema_never_loosens_legacy_secret_requirements():
    schema = json.loads((APP_ROOT / "static" / "json" / "schemas" / "plugin.schema.json").read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)
    manifest = {
        "name": "yamcs", "type": "yamcs", "description": "Read telemetry.",
        "endpoint": "https://yamcs.example", "auth": {"type": "username_password"},
        "metadata": {}, "additionalFields": {},
    }
    assert not validator.is_valid(manifest)
    requirement = {"source": "current_user", "identity_name": "Yamcs", "profile": "yamcs_login"}
    assert validator.is_valid({**manifest, "credential_requirement": requirement})
    assert validator.is_valid({**manifest, "auth": {"type": "username_password", "identity": "alice", "key": "synthetic"}})
    for override in (
        {"auth": {"type": "username_password", "key": "must-not-be-shared"}},
        {"identity_id": "someone-elses-identity"},
        {"type": "openapi"},
        {"credential_requirement": {**requirement, "source": "owner"}},
        {"credential_requirement": {**requirement, "profile": "arbitrary_script"}},
    ):
        assert not validator.is_valid({**manifest, "credential_requirement": requirement, **override})


@pytest.mark.parametrize("unsupported", [None, "auth_key", "action_auth_request_id"])
def test_connection_probe_uses_saved_action_and_current_user_only(environment, unsupported):
    app, namespace, _ = environment
    saved = {
        "id": "yamcs", "type": "yamcs", "endpoint": "https://approved.example",
        "credential_requirement": {"id": "requirement", "source": "current_user"},
    }
    own_auth = {"auth_type": "username_password", "username": "bob-service-user", "password": "synthetic-private-password"}
    resolve_action = Mock(return_value=saved)
    resolve_credentials = Mock(return_value=own_auth)
    probe = Mock()
    namespace.update({
        "request": request,
        "get_current_user_id": lambda: "bob",
        "resolve_action_manifest": resolve_action,
        "get_action_credential_requirement": lambda action: action.get("credential_requirement"),
        "resolve_action_auth_credentials": resolve_credentials,
        "validate_yamcs_credentials": probe,
        "YAMCS_PLUGIN_TYPE": "yamcs",
        "YamcsAuthenticationError": type("YamcsAuthenticationError", (RuntimeError,), {}),
        "YamcsPermissionError": type("YamcsPermissionError", (RuntimeError,), {}),
        "YamcsConnectionError": type("YamcsConnectionError", (RuntimeError,), {}),
    })
    execute_route("route_backend_plugins.py", "test_yamcs_connection", namespace)
    app.add_url_rule("/probe", view_func=namespace["test_yamcs_connection"], methods=["POST"])
    payload = {"action_ref": "global-yamcs-reference", "user_id": "alice"}
    if unsupported:
        payload[unsupported] = "must-not-be-used"
    response = app.test_client().post("/probe", json=payload)
    assert response.status_code == (400 if unsupported else 200)
    resolve_action.assert_called_once_with("bob", "global-yamcs-reference")
    if unsupported:
        probe.assert_not_called()
        resolve_credentials.assert_not_called()
    else:
        resolve_credentials.assert_called_once_with(saved)
        probe.assert_called_once_with(saved, own_auth)
    assert "synthetic-private-password" not in response.get_data(as_text=True)
