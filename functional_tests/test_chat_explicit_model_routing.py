# test_chat_explicit_model_routing.py
"""
Regression tests for chat bootstrap with explicit per-model routing.
Version: 0.261.053
Implemented in: 0.261.053

Execute the chat route and catalog functions with the real model-identifier
resolver, without initializing cloud clients.
"""

import ast
import copy
import logging
import sys
from pathlib import Path

import pytest
from flask import Flask, jsonify, request


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

from functions_model_endpoint_types import resolve_model_endpoint_request_model  # noqa: E402


def load_chat_functions(settings, personal_endpoints=None, group_endpoints=None):
    source = ast.parse((APP_DIR / "route_frontend_chats.py").read_text(encoding="utf-8"))
    catalog = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == "_build_chat_model_catalog"
    )
    registrar = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == "register_route_frontend_chats"
    )
    chats = copy.deepcopy(next(
        node for node in registrar.body
        if isinstance(node, ast.FunctionDef) and node.name == "chats"
    ))
    chats.decorator_list = []
    groups = [{"id": "group-one", "name": "Group One"}] if group_endpoints else []
    user_settings = {
        "settings": {"personal_model_endpoints": personal_endpoints or []},
        "display_name": "Test User",
    }
    namespace = {
        "resolve_model_endpoint_request_model": resolve_model_endpoint_request_model,
        "sanitize_model_endpoints_for_frontend": copy.deepcopy,
        "normalize_model_endpoints": lambda endpoints: (endpoints, False),
        "_filter_chat_model_endpoints_by_governance": lambda user_id, endpoints, feature: endpoints,
        "get_group_model_endpoints": lambda group_id: group_endpoints or [],
        "get_current_user_id": lambda: "user-one",
        "get_current_user_info": lambda: {"email": "test@example.com"},
        "get_settings": lambda: settings,
        "get_user_settings": lambda user_id: user_settings,
        "_ensure_public_chat_workspace_visible": lambda *args: None,
        "sanitize_settings_for_user": copy.deepcopy,
        "get_ai_notice_config": lambda settings: {},
        "is_ai_notice_dismissed": lambda *args: False,
        "session": {"user": {"roles": []}},
        "is_user_workflows_enabled_for_user": lambda *args, **kwargs: False,
        "is_chat_file_upload_enabled_for_user": lambda *args: True,
        "is_source_review_enabled_for_user": lambda *args, **kwargs: False,
        "is_url_access_enabled_for_user": lambda *args, **kwargs: False,
        "is_conversation_contents_drawer_enabled": lambda *args: False,
        "get_deep_research_config": lambda settings: {},
        "CLIENTS": {},
        "get_user_groups": lambda user_id: groups,
        "get_user_role_in_group": lambda *args: "User",
        "get_user_visible_public_workspace_ids_from_settings": lambda user_id: [],
        "build_chat_bootstrap_cache_key": lambda *args, **kwargs: "test-cache-key",
        "get_cached_chat_bootstrap_payload": lambda key: None,
        "_is_valid_chat_bootstrap_payload": lambda payload: False,
        "build_accessible_agent_catalog": lambda *args, **kwargs: [],
        "_build_chat_prompt_catalog": lambda **kwargs: [],
        "set_cached_chat_bootstrap_payload": lambda *args, **kwargs: None,
        "_build_initial_chat_model_selection": lambda **kwargs: None,
        "request": request,
        "logger": logging.getLogger(__name__),
        "render_template": lambda template, **context: jsonify({
            "models": context["multi_endpoint_models"],
            "catalog": context["chat_model_options"],
        }),
    }
    module = ast.Module(body=[catalog, chats], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "route_frontend_chats.py", "exec"), namespace)
    return namespace, user_settings, groups


def endpoint_for(api_type, identifier_field, identifier, *, enabled=True):
    return {
        "id": f"endpoint-{api_type}",
        "provider": "custom",
        "enabled": enabled,
        "routing_schema_version": 2,
        "models": [{
            "id": f"model-{api_type}",
            "enabled": True,
            "api_type": api_type,
            identifier_field: identifier,
        }],
    }


@pytest.mark.parametrize(
    ("api_type", "identifier_field", "identifier"),
    [
        ("anthropic", "modelName", "claude-test"),
        ("openai", "modelName", "chat-test"),
        ("azure_openai", "deploymentName", "deployment-alias"),
    ],
)
def test_chats_loads_with_enabled_explicit_routing(api_type, identifier_field, identifier):
    endpoint = endpoint_for(api_type, identifier_field, identifier)
    functions, _, _ = load_chat_functions({
        "enable_multi_model_endpoints": True,
        "model_endpoints": [endpoint],
    })
    app = Flask(__name__)
    app.add_url_rule("/chats", "chats", functions["chats"])

    response = app.test_client().get("/chats")

    assert response.status_code == 200
    assert response.json["models"][0]["request_model"] == identifier
    assert response.json["catalog"][0]["request_model"] == identifier


def test_chat_catalog_supports_explicit_routing_in_all_scopes():
    global_endpoint = endpoint_for("azure_openai", "deploymentName", "global-deployment")
    personal_endpoint = endpoint_for("anthropic", "modelName", "personal-model")
    group_endpoint = endpoint_for("openai", "modelName", "group-model")
    settings = {
        "enable_multi_model_endpoints": True,
        "allow_user_custom_endpoints": True,
        "enable_group_workspaces": True,
        "allow_group_custom_endpoints": True,
        "model_endpoints": [global_endpoint],
    }
    functions, user_settings, groups = load_chat_functions(
        settings, [personal_endpoint], [group_endpoint],
    )

    catalog = functions["_build_chat_model_catalog"](
        user_id="user-one",
        settings=settings,
        user_settings_dict=user_settings["settings"],
        user_groups_raw=groups,
    )

    assert [(model["scope_type"], model["request_model"]) for model in catalog] == [
        ("global", "global-deployment"),
        ("personal", "personal-model"),
        ("group", "group-model"),
    ]


def test_chat_keeps_legacy_endpoint_and_skips_disabled_explicit_endpoint():
    legacy = {
        "id": "legacy",
        "provider": "aoai",
        "enabled": True,
        "models": [{"id": "legacy-model", "deploymentName": "legacy-deployment"}],
    }
    disabled = endpoint_for("anthropic", "modelName", "disabled-model", enabled=False)
    functions, _, _ = load_chat_functions({
        "enable_multi_model_endpoints": True,
        "model_endpoints": [legacy, disabled],
    })
    app = Flask(__name__)
    app.add_url_rule("/chats", "chats", functions["chats"])

    response = app.test_client().get("/chats")

    assert response.status_code == 200
    assert [model["request_model"] for model in response.json["models"]] == ["legacy-deployment"]
    assert [model["request_model"] for model in response.json["catalog"]] == ["legacy-deployment"]
