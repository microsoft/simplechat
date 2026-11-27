# test_storage_container_repair_policy.py
"""Admin-only Blueprint and Swagger policy for explicit storage container repair.

Version: 0.261.472
Implemented in: 0.261.396
Replay index admin coverage implemented in: 0.261.472
"""

import ast
import logging
from pathlib import Path
from unittest.mock import Mock

from azure.core.exceptions import AzureError
from flask import Flask, jsonify, request

from app_settings_cache import COSMOS_REPLAY_INDEX_SETTING
from app_settings_store import SettingsConflictError, SettingsUnavailableError
from test_route_unauthenticated_policy_contract import expected_policy, iter_route_functions


def test_storage_repair_is_explicit_admin_post():
    matches = [
        route for route in iter_route_functions()
        if route.path == "/api/admin/settings/storage/repair-containers"
    ]
    assert len(matches) == 1
    route = matches[0]
    assert route.file_name == "route_backend_settings.py"
    assert route.route_target == "bp"
    assert route.decorator_names == ("bp.route", "swagger_route", "login_required", "admin_required")
    assert expected_policy(route.path) == "session_admin_401_or_redirect"


def test_replay_indexing_requires_a_signed_in_admin():
    path = "/api/admin/settings/cosmos-replay-indexing"
    route, = [candidate for candidate in iter_route_functions() if candidate.path == path]
    assert route.file_name == "route_backend_settings.py"
    assert route.decorator_names == ("bp.route", "swagger_route", "login_required", "admin_required")
    assert expected_policy(path) == "session_admin_401_or_redirect"


def test_replay_indexing_saves_only_after_reader_and_policy_confirmation():
    path = "/api/admin/settings/cosmos-replay-indexing"
    source = Path(__file__).resolve().parents[2] / "application" / "single_app" / "route_backend_settings.py"
    view = next(node for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
                if isinstance(node, ast.FunctionDef) and node.name == "cosmos_replay_indexing_admin")
    view.decorator_list = []
    inspect_policy = Mock(return_value={"enabled": False, "policy_state": "manual"})
    save = Mock(return_value=True)
    settings = {"_etag": "revision", "enable_redis_cache": False}
    namespace = {
        "request": request, "jsonify": jsonify, "get_settings": Mock(return_value=settings),
        "get_cosmos_replay_index_status": inspect_policy, "update_settings": save,
        "COSMOS_REPLAY_INDEX_SETTING": COSMOS_REPLAY_INDEX_SETTING, "SettingsUnavailableError": SettingsUnavailableError,
        "SettingsConflictError": SettingsConflictError, "AzureError": AzureError, "get_current_user_id": lambda: "admin",
        "log_event": Mock(), "logging": logging,
    }
    exec(compile(ast.Module(body=[view], type_ignores=[]), str(source), "exec"), namespace)
    app = Flask(__name__)
    app.add_url_rule(path, view_func=namespace["cosmos_replay_indexing_admin"], methods=["GET", "POST"])
    client = app.test_client()

    missing_checkbox = client.post(path, json={"action": "apply"})
    assert missing_checkbox.status_code == 400
    inspect_policy.assert_not_called()
    manual = client.post(path, json={"action": "apply", "readers_ready": True})
    assert manual.status_code == 409 and manual.json["status"]["policy_state"] == "manual"
    save.assert_not_called()
    settings["enable_redis_cache"] = True
    with_redis = client.post(path, json={"action": "apply", "readers_ready": True})
    assert with_redis.status_code == 409
    inspect_policy.assert_called_with(settings)
    save.assert_not_called()
    settings["enable_redis_cache"] = False
    inspect_policy.return_value = {"enabled": False, "policy_state": "ready"}
    verified = client.post(path, json={"action": "verify", "readers_ready": True})
    assert verified.status_code == 200 and verified.json["enabled"] is True
    inspect_policy.assert_called_with(settings, apply=False)
    save.assert_called_once_with({COSMOS_REPLAY_INDEX_SETTING: True}, expected_etag="revision")

    settings[COSMOS_REPLAY_INDEX_SETTING] = True
    disabled = client.post(path, json={"action": "disable"})
    assert disabled.status_code == 200
    save.assert_called_with({COSMOS_REPLAY_INDEX_SETTING: False}, expected_etag="revision")
    inspect_policy.assert_called_with({**settings, COSMOS_REPLAY_INDEX_SETTING: False})
