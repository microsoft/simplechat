# test_personal_action_save_helper_regression.py
"""
Functional regression test for the M4 §8 B0 fix.

Version: 0.261.137
Implemented in: 0.261.137

While inserting the group-action payload preparer, the shared helper
``_save_personal_action_or_error`` lost its ``def`` line, so both personal
action write paths — ``_create_personal_action`` (POST) and
``update_user_plugin`` (PATCH) — called an undefined name and raised a
``NameError`` that surfaced as a 500. The suite could not see it because it
stubbed the helper. This test runs the two real write paths against the real,
restored helper over stubbed storage, so a personal create and a personal
update must both succeed and reach that helper. If the helper is missing again,
both calls raise ``NameError`` and this test fails.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, jsonify, request

from test_support.agent_delegation import APP_ROOT, execute_functions
from test_support.versioning import assert_app_version_at_least


@pytest.fixture
def personal_writes():
    saved_calls = []

    def save_personal_action(user_id, plugin_to_save):
        saved_calls.append((user_id, dict(plugin_to_save)))
        stored = dict(plugin_to_save)
        stored.setdefault("id", "stored-id")
        return stored

    def prepare(user_id, payload, *, editor=False):
        prepared = {key: value for key, value in payload.items() if not key.startswith("_")}
        prepared.setdefault("id", payload.get("id") or "stored-id")
        return prepared, None

    existing_record = {"id": "act", "name": "act", "type": "openapi", "endpoint": "https://api.test"}

    def get_personal_action(user_id, identifier, return_type=None):
        # The create path looks up its new name (absent -> None); the update path
        # looks up the existing action by id and must find it.
        return dict(existing_record) if identifier == "act" else None

    namespace = {
        "jsonify": jsonify, "request": request,
        "get_current_user_id": lambda: "user-1",
        "get_global_actions": lambda: [],
        "get_personal_action": get_personal_action,
        "get_legacy_personal_action": Mock(return_value=dict(existing_record)),
        "SecretReturnType": SimpleNamespace(NAME="name", VALUE="value"),
        "LEGACY_ACTION_PREFIX": "legacy::",
        "personal_editor_response": Mock(),
        "_prepare_personal_action_payload": prepare,
        "save_personal_action": save_personal_action,
        "reconfigure_legacy_personal_action": Mock(side_effect=AssertionError("legacy path not used")),
        "McpConfigurationError": type("McpConfigurationError", (Exception,), {}),
        "LegacyActionCreationError": type("LegacyActionCreationError", (Exception,), {}),
        "LegacyActionConflictError": type("LegacyActionConflictError", (Exception,), {}),
        "LegacyActionSourceUpdateError": type("LegacyActionSourceUpdateError", (Exception,), {}),
        "_handle_mcp_configuration_error": Mock(),
        "_handle_legacy_action_error": Mock(),
        "LEGACY_ACTION_CREATION_MESSAGE": "legacy",
        "ACTION_VALIDATION_ERROR_MESSAGE": "invalid",
        "ACTION_PERMISSION_ERROR_MESSAGE": "denied",
        "ACTION_KEY_VAULT_ERROR_MESSAGE": "vault",
        "debug_print": Mock(), "log_event": Mock(), "log_action_creation": Mock(),
        "log_action_update": Mock(),
        # Passthrough route decorators so the PATCH view can be called directly.
        "bpap": SimpleNamespace(route=lambda *a, **k: (lambda function: function)),
        "swagger_route": lambda **k: (lambda function: function),
        "get_auth_security": lambda: [{"sessionAuth": []}],
        "login_required": lambda function: function,
        "user_required": lambda function: function,
        "enabled_required": lambda *a, **k: (lambda function: function),
    }
    execute_functions("route_backend_plugins.py", {
        "_save_personal_action_or_error",
        "_create_personal_action",
        "update_user_plugin",
    }, namespace)

    app = Flask("personal_action_regression")
    app.config.update(TESTING=True)
    return SimpleNamespace(app=app, ns=namespace, saved_calls=saved_calls, existing=existing_record)


def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.137")


def test_personal_create_reaches_the_save_helper(personal_writes):
    with personal_writes.app.test_request_context(json={}):
        response, status = personal_writes.ns["_create_personal_action"](
            "user-1", {"name": "new-action", "type": "openapi", "endpoint": "https://api.test"},
        )
    assert status == 201
    assert response.get_json()["name"] == "new-action"
    # The real helper actually persisted through the storage seam.
    assert personal_writes.saved_calls and personal_writes.saved_calls[0][1]["name"] == "new-action"


def test_personal_update_reaches_the_save_helper(personal_writes):
    with personal_writes.app.test_request_context(json={"description": "edited"}):
        result = personal_writes.ns["update_user_plugin"]("act")
    response = result[0] if isinstance(result, tuple) else result
    assert response.get_json()["description"] == "edited"
    assert personal_writes.saved_calls and personal_writes.saved_calls[0][1]["description"] == "edited"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
