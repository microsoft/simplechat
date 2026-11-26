# test_agent_model_governance_filtering.py
#!/usr/bin/env python3
"""
Functional tests for agent model governance and read-only model projections.
Version: 0.261.437
Implemented in: 0.261.048
Empty explicit-route projection regression added in: 0.261.437

This test ensures the personal and group agent model dropdown payloads apply
governance policies before returning model endpoints to the browser.
"""

import ast
import os
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_model_endpoint_normalization_backend import (  # noqa: E402
    _load_functions_settings_module, _restore_modules,
)
from functions_ai_connections import filter_model_endpoints_by_capability  # noqa: E402
import functions_workspace_authoring as authoring  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROUTE = REPO_ROOT / "application" / "single_app" / "route_backend_agents.py"
AUTHORING_MODULE = REPO_ROOT / "application" / "single_app" / "functions_workspace_authoring.py"


def _load_agent_settings_helpers():
    source = AGENTS_ROUTE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"collect_agent_model_endpoints", "build_combined_model_endpoints", "get_global_agent_settings"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == names
    module = ast.Module(body=functions, type_ignores=[])
    namespace = {"jsonify": jsonify}
    exec(compile(module, str(AGENTS_ROUTE), "exec"), namespace)
    return namespace


def test_agent_settings_model_endpoints_respect_governance():
    print("Testing agent settings model endpoint governance filtering...")
    assert_app_version_at_least("0.261.048")

    calls = []
    helpers = _load_agent_settings_helpers()
    build_combined_model_endpoints = helpers["build_combined_model_endpoints"]

    def filter_governed_model_endpoints(user_id, endpoints, feature_key):
        calls.append((user_id, feature_key, [endpoint.get("id") for endpoint in endpoints]))
        return [endpoint for endpoint in endpoints if "denied" not in endpoint.get("id", "")]

    def sanitize_model_endpoints_for_frontend(endpoints, include_connection_details=False):
        return endpoints

    def filter_model_endpoints_by_capability(endpoints, preserve_empty=False):
        return endpoints

    def ensure_governance_access(feature_key, user_id):
        calls.append((user_id, feature_key, "feature-check"))

    def get_user_settings(user_id):
        return {
            "settings": {
                "personal_model_endpoints": [
                    {"id": "personal-allowed", "models": [{"id": "personal-model"}]},
                    {"id": "personal-denied", "models": [{"id": "restricted-personal-model"}]},
                ]
            }
        }

    def get_group_model_endpoints(group_id):
        return [
            {"id": "group-allowed", "models": [{"id": "group-model"}]},
            {"id": "group-denied", "models": [{"id": "restricted-group-model"}]},
        ]

    helpers.update({
        "filter_governed_model_endpoints": filter_governed_model_endpoints,
        "sanitize_model_endpoints_for_frontend": sanitize_model_endpoints_for_frontend,
        "filter_model_endpoints_by_capability": filter_model_endpoints_by_capability,
        "ensure_governance_access": ensure_governance_access,
        "get_user_settings": get_user_settings,
        "get_group_model_endpoints": get_group_model_endpoints,
    })

    settings = {
        "model_endpoints": [
            {"id": "global-allowed", "models": [{"id": "allowed-model"}]},
            {"id": "global-denied", "models": [{"id": "restricted-model"}]},
        ],
        "allow_user_custom_endpoints": True,
        "allow_group_custom_endpoints": True,
    }

    personal_ids = [
        endpoint["id"]
        for endpoint in build_combined_model_endpoints(settings, user_id="user-b")
    ]
    assert personal_ids == ["global-allowed", "personal-allowed"], personal_ids

    group_ids = [
        endpoint["id"]
        for endpoint in build_combined_model_endpoints(
            settings,
            user_id="user-b",
            group_id="group-1",
        )
    ]
    assert group_ids == ["global-allowed", "group-allowed"], group_ids

    admin_ids = [endpoint["id"] for endpoint in build_combined_model_endpoints(settings)]
    assert admin_ids == ["global-allowed", "global-denied"], admin_ids

    asserted_filters = {(call[0], call[1]) for call in calls if len(call) == 3}
    assert ("user-b", "governance_global_endpoints") in asserted_filters
    assert ("user-b", "governance_user_endpoints") in asserted_filters
    assert ("user-b", "governance_group_endpoints") in asserted_filters

    authoring_source = AUTHORING_MODULE.read_text(encoding="utf-8")
    assert '"governance_user_endpoints"' in authoring_source
    assert '"governance_group_endpoints"' in authoring_source
    assert '"governance_global_endpoints"' in authoring_source
    print("PASS: agent settings model endpoint governance filtering verified")


def _explicit_connections():
    chat = {
        "id": "chat",
        "name": "Chat connection",
        "provider": "custom",
        "routing_schema_version": 2,
        "connection": {"endpoint": "https://gateway.example.test/shared"},
        "auth": {"type": "api_key", "api_key": "test-only-key"},
        "models": [{
            "id": "responses", "modelName": "synthetic-chat", "api_type": "openai",
            "inference_api": "responses", "api_path": "team",
        }],
    }
    disabled = {**deepcopy(chat), "id": "disabled", "name": "Disabled connection", "enabled": False}
    embeddings = {
        **deepcopy(chat),
        "id": "vectors",
        "name": "Embedding connection",
        "models": [{
            "id": "vectors", "modelName": "text-embedding-3-small", "api_type": "openai",
            "enabled_capabilities": ["embeddings"],
            "embedding_operation": {"endpoint": "https://embeddings.example.test/v1"},
        }],
    }
    return [chat, disabled, embeddings]


def _assert_chat_projection(projected):
    assert [(endpoint["id"], [model["id"] for model in endpoint["models"]]) for endpoint in projected] == [
        ("chat", ["responses"]), ("disabled", []), ("vectors", []),
    ]
    assert projected[0]["models"][0]["inference_api"] == "responses"
    assert projected[0]["models"][0]["api_path"] == "team"
    assert projected[0]["models"][0]["capability_status"]["chat"]["supported"]
    for endpoint in projected:
        assert {"auth", "connection", "management", "identity_header"}.isdisjoint(endpoint)


def test_agent_settings_preserve_empty_explicit_connections_without_exposing_connection_details():
    settings_module, original_modules = _load_functions_settings_module()
    try:
        settings = {"model_endpoints": _explicit_connections()}
        before = deepcopy(settings)
        helpers = _load_agent_settings_helpers()
        helpers.update({
            "get_settings": lambda: settings,
            "get_global_agents": lambda: [],
            "sanitize_model_endpoints_for_frontend": settings_module.sanitize_model_endpoints_for_frontend,
            "filter_model_endpoints_by_capability": filter_model_endpoints_by_capability,
        })

        with Flask(__name__).app_context():
            response = helpers["get_global_agent_settings"](include_admin_extras=True)
        assert response.status_code == 200
        projected = response.get_json()["model_endpoints"]

        _assert_chat_projection(projected)
        assert all(endpoint["scope"] == "global" for endpoint in projected)
        assert settings == before
    finally:
        _restore_modules(original_modules)


@pytest.mark.parametrize("scope", ["global", "personal", "group"])
def test_agent_editor_options_preserve_empty_explicit_connections(scope, monkeypatch):
    settings_module, original_modules = _load_functions_settings_module()
    try:
        services = {
            "functions_settings": settings_module,
            "functions_keyvault": SimpleNamespace(validate_secret_name_dynamic=lambda _value: False),
            "functions_governance": SimpleNamespace(
                ensure_governance_access=lambda *_args: None,
                filter_governed_model_endpoints=lambda _user, endpoints, _feature: endpoints,
            ),
            "functions_agent_templates": SimpleNamespace(
                agent_template_submission_decision=lambda *_args: (False, None),
            ),
        }
        monkeypatch.setattr(authoring, "import_module", services.__getitem__)
        monkeypatch.setattr(authoring, "ensure_editor_options_access", lambda *_args: True)
        monkeypatch.setattr(authoring, "ensure_editor_access", lambda *_args: None)
        endpoint_scope = "user" if scope == "personal" else scope
        endpoints = [{**endpoint, "scope": endpoint_scope} for endpoint in _explicit_connections()]
        before = deepcopy(endpoints)
        settings = {"allow_user_custom_endpoints": True, "allow_group_custom_endpoints": True}

        if scope == "global":
            result = authoring.build_global_agent_editor_options(settings, endpoints)
        elif scope == "personal":
            result = authoring.build_agent_editor_options("owner", settings, endpoints)
        else:
            result = authoring.build_group_agent_editor_options("owner", "group-1", settings, endpoints, True)

        _assert_chat_projection(result["model_endpoints"])
        assert all(endpoint["scope"] == endpoint_scope for endpoint in result["model_endpoints"])
        assert endpoints == before
    finally:
        _restore_modules(original_modules)


if __name__ == "__main__":
    try:
        test_agent_settings_model_endpoints_respect_governance()
        test_agent_settings_preserve_empty_explicit_connections_without_exposing_connection_details()
        sys.exit(0)
    except Exception as exc:
        print(f"FAIL: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
