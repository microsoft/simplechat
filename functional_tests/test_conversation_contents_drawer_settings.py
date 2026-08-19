#!/usr/bin/env python3
"""
Functional test for conversation contents drawer settings.
Version: 0.250.074
Implemented in: 0.250.074

This test ensures the admin feature gate and user preference default on,
persist through their established settings flows, and combine as a hard gate.
"""

import ast
import importlib.util
from pathlib import Path

from flask import Flask, jsonify, request
from test_support.templates import compose_if_admin_settings


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
HELPER_SPEC = importlib.util.spec_from_file_location(
    "functions_conversation_contents",
    APP_ROOT / "functions_conversation_contents.py",
)
HELPER_MODULE = importlib.util.module_from_spec(HELPER_SPEC)
HELPER_SPEC.loader.exec_module(HELPER_MODULE)
is_conversation_contents_drawer_enabled = HELPER_MODULE.is_conversation_contents_drawer_enabled


def _read(relative_path):
    _path = REPO_ROOT / relative_path
    return compose_if_admin_settings(
        _path, _path.read_text(encoding="utf-8")
    )


def test_admin_setting_defaults_on_and_persists():
    """Verify the admin setting is default-on and saved from the admin form."""
    settings_source = _read("application/single_app/functions_settings.py")
    admin_route_source = _read("application/single_app/route_frontend_admin_settings.py")
    admin_template = _read("application/single_app/templates/admin_settings.html")

    assert "'enable_conversation_contents_drawer': True" in settings_source
    assert "'enable_conversation_contents_drawer': form_data.get('enable_conversation_contents_drawer') == 'on'" in admin_route_source
    assert 'name="enable_conversation_contents_drawer"' in admin_template
    assert "{% if settings.enable_conversation_contents_drawer %}checked{% endif %}" in admin_template


def test_user_preference_defaults_on_and_is_validated():
    """Verify the current-user preference is allowed, boolean-only, and default-on."""
    users_route_source = _read("application/single_app/route_backend_users.py")
    profile_template = _read("application/single_app/templates/profile.html")

    assert "'conversationContentsDrawerEnabled'" in users_route_source
    assert 'isinstance(settings_to_update["conversationContentsDrawerEnabled"], bool)' in users_route_source
    assert ".get('conversationContentsDrawerEnabled', True)" in profile_template
    assert "{% if app_settings.enable_conversation_contents_drawer %}" in profile_template


def _load_user_settings_route_for_test(saved_updates):
    route_path = APP_ROOT / "route_backend_users.py"
    route_tree = ast.parse(route_path.read_text(encoding="utf-8"))
    register_function = next(
        node for node in route_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_users"
    )
    route_function = next(
        node for node in register_function.body
        if isinstance(node, ast.FunctionDef) and node.name == "user_settings"
    )
    route_function.decorator_list = []
    isolated_module = ast.fix_missing_locations(ast.Module(body=[route_function], type_ignores=[]))
    namespace = {
        "LATEST_FEATURES_HIDDEN_VERSION_SETTING": "latestFeaturesHiddenVersion",
        "VERSION": "0.250.074",
        "get_current_user_id": lambda: "user-1",
        "get_user_settings": lambda user_id: {"id": user_id, "settings": {}},
        "jsonify": jsonify,
        "normalize_latest_features_hidden_version": lambda value: value,
        "request": request,
        "update_user_settings": lambda user_id, settings: saved_updates.append((user_id, settings)) or True,
    }
    exec(compile(isolated_module, str(route_path), "exec"), namespace)
    return namespace["user_settings"]


def test_user_preference_route_persists_boolean_and_rejects_invalid_type():
    """Execute the current-user route validation and persistence path."""
    app = Flask(__name__)
    saved_updates = []
    user_settings_route = _load_user_settings_route_for_test(saved_updates)

    with app.test_request_context(
        "/api/user/settings",
        method="POST",
        json={"settings": {"conversationContentsDrawerEnabled": False}},
    ):
        response, status_code = user_settings_route()

    assert status_code == 200
    assert response.get_json()["message"] == "User settings updated successfully"
    assert saved_updates == [
        ("user-1", {"conversationContentsDrawerEnabled": False})
    ]

    with app.test_request_context(
        "/api/user/settings",
        method="POST",
        json={"settings": {"conversationContentsDrawerEnabled": "false"}},
    ):
        response, status_code = user_settings_route()

    assert status_code == 400
    assert response.get_json()["error"] == "Invalid conversation contents drawer preference"
    assert len(saved_updates) == 1


def test_chat_route_uses_shared_gate():
    """Verify the chat route delegates the effective setting to the tested helper."""
    chats_route_source = _read("application/single_app/route_frontend_chats.py")
    chats_template = _read("application/single_app/templates/chats.html")

    assert "is_conversation_contents_drawer_enabled(" in chats_route_source
    assert "conversation_contents_drawer_enabled=conversation_contents_drawer_enabled" in chats_route_source
    assert chats_template.count("{% if conversation_contents_drawer_enabled %}") >= 2


def test_effective_gate_defaults_and_precedence():
    """Exercise default-on behavior and the authoritative admin gate."""
    assert is_conversation_contents_drawer_enabled({}, {}) is True
    assert is_conversation_contents_drawer_enabled(
        {'enable_conversation_contents_drawer': True},
        {'conversationContentsDrawerEnabled': True},
    ) is True
    assert is_conversation_contents_drawer_enabled(
        {'enable_conversation_contents_drawer': True},
        {'conversationContentsDrawerEnabled': False},
    ) is False
    assert is_conversation_contents_drawer_enabled(
        {'enable_conversation_contents_drawer': False},
        {'conversationContentsDrawerEnabled': True},
    ) is False
    assert is_conversation_contents_drawer_enabled(None, None) is True


if __name__ == "__main__":
    tests = [
        test_admin_setting_defaults_on_and_persists,
        test_user_preference_defaults_on_and_is_validated,
        test_user_preference_route_persists_boolean_and_rejects_invalid_type,
        test_chat_route_uses_shared_gate,
        test_effective_gate_defaults_and_precedence,
    ]
    for test in tests:
        test()
    print(f"Conversation contents drawer settings tests passed: {len(tests)}/{len(tests)}")
