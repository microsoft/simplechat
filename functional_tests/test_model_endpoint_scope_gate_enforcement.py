# test_model_endpoint_scope_gate_enforcement.py
#!/usr/bin/env python3
"""
Functional test for user and group model endpoint scope enforcement.
Version: 0.261.042
Implemented in: 0.239.187

Schema-v2 preview authorization and no-I/O coverage added in: 0.261.042

This test ensures non-admin model fetch and test routes require the
custom-endpoint feature gates while still allowing pre-save fetch/test
requests and restricting persisted endpoint IDs to authorized endpoints.
"""

import ast
import copy
import os
from pathlib import Path
import sys
from unittest.mock import Mock

from flask import Flask, jsonify, request

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from functions_model_endpoint_urls import normalize_model_endpoint_routing, resolve_model_endpoint_route


def test_routing_preview_authorization_and_no_dispatch():
    source = ast.parse((APP_ROOT / "route_backend_models.py").read_text(encoding="utf-8"))
    registrar = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_models")
    names = {"handle_test_model_connection", "handle_model_routing_preview", "build_safe_error_response"}
    nodes = [node for node in registrar.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(nodes) == len(names), "The authorized, no-dispatch preview branch is missing."
    forbidden = Mock(side_effect=AssertionError("Preview must not resolve secrets or dispatch."))
    lookup = Mock(return_value={"id": "saved"})
    governance = Mock()
    settings = {"enable_multi_model_endpoints": True, "allow_user_custom_endpoints": True, "allow_group_custom_endpoints": True}
    namespace = {
        "request": request, "jsonify": jsonify,
        "get_settings": lambda: settings,
        "get_current_user_id": lambda: "actor",
        "ensure_governance_access": governance,
        "resolve_endpoint_by_id": lookup,
        "normalize_model_endpoint_routing": normalize_model_endpoint_routing,
        "resolve_model_endpoint_route": resolve_model_endpoint_route,
        "resolve_request_endpoint_payload": forbidden,
        "build_inference_client": forbidden,
        "log_models_exception": Mock(), "log_event": Mock(),
        "logging": __import__("logging"),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<routing-preview>", "exec"), namespace)
    app = Flask(__name__)
    payload = {
        "id": "saved", "routing_schema_version": 2, "preview_only": True,
        "provider": "custom", "connection": {"endpoint": "https://gateway.example/shared"},
        "auth": {"api_key": "must-not-echo", "key_vault_reference": "must-not-echo"},
        "model": {"id": "one", "modelName": "not-an-anthropic-model", "api_type": "anthropic", "api_path": "team", "url_mode": "auto"},
    }
    for scope in ("global", "user", "group"):
        with app.test_request_context(json=payload):
            response, status = namespace["handle_test_model_connection"](scope)
        assert status == 200
        body = response.get_json()
        assert body["preview_only"] is True
        assert body["resolved"]["operation_url"] == "https://gateway.example/team/shared/v1/messages"
        assert body["resolved"]["method"] == "POST"
        assert "must-not-echo" not in response.get_data(as_text=True)
        lookup.assert_called_with("actor", scope, "saved")
        governance.assert_any_call(f"governance_{scope}_endpoints", "actor")
    forbidden.assert_not_called()
    for field, value in (("api_path", "../escape"), ("api_type", "responses"), ("url_mode", "inherit")):
        invalid = copy.deepcopy(payload)
        invalid["model"][field] = value
        with app.test_request_context(json=invalid):
            response, status = namespace["handle_test_model_connection"]("user")
        assert status == 400
        assert value not in response.get_data(as_text=True)
    lookup.return_value = None
    with app.test_request_context(json=payload):
        response, status = namespace["handle_test_model_connection"]("user")
    assert status == 404
    lookup.return_value = {"id": "saved"}
    governance.side_effect = PermissionError("private detail")
    with app.test_request_context(json=payload):
        response, status = namespace["handle_test_model_connection"]("group")
    assert status == 403
    assert "private detail" not in response.get_data(as_text=True)
    governance.side_effect = None
    settings["allow_user_custom_endpoints"] = False
    with app.test_request_context(json=payload):
        response, status = namespace["handle_test_model_connection"]("user")
    assert status == 403
    payload["preview_only"] = False
    with app.test_request_context(json=payload):
        response, status = namespace["handle_test_model_connection"]("global")
    assert status == 501
    forbidden.assert_not_called()


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_model_endpoint_scope_gate_enforcement():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    backend_path = os.path.join(repo_root, 'application', 'single_app', 'route_backend_models.py')

    backend_content = read_file_text(backend_path)

    assert 'if scope in ("user", "group") and endpoint_id:' in backend_content, (
        "User/group persisted endpoint validation should only apply when an endpoint_id is supplied."
    )
    assert "raise LookupError(\"Model endpoint not found.\")" in backend_content, (
        "User/group model routes must reject unknown endpoint IDs."
    )
    assert 'merge_model_endpoint_payload(persisted_endpoint or {}, payload)' in backend_content, (
        "Feature-gated user/group model routes should still accept ad hoc payloads for pre-save fetch/test flows."
    )
    assert 'merge_model_endpoint_payload(persisted_endpoint, {})' in backend_content, (
        "User/group requests that reference a saved endpoint must resolve persisted endpoint configuration."
    )
    assert "@enabled_required('allow_user_custom_endpoints')\n    def fetch_model_list_user():" in backend_content, (
        "User model fetch route must require allow_user_custom_endpoints."
    )
    assert "@enabled_required('allow_user_custom_endpoints')\n    def test_model_connection_user():" in backend_content, (
        "User model test route must require allow_user_custom_endpoints."
    )
    assert "@enabled_required('allow_group_custom_endpoints')\n    def fetch_model_list_group():" in backend_content, (
        "Group model fetch route must require allow_group_custom_endpoints."
    )
    assert "@enabled_required('allow_group_custom_endpoints')\n    def test_model_connection_group():" in backend_content, (
        "Group model test route must require allow_group_custom_endpoints."
    )

    print("✅ Model endpoint scope gates, pre-save fetch/test flow, and persisted-endpoint enforcement verified.")


if __name__ == "__main__":
    test_model_endpoint_scope_gate_enforcement()
    test_routing_preview_authorization_and_no_dispatch()