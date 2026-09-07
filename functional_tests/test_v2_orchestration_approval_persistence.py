# test_v2_orchestration_approval_persistence.py
"""
Functional regressions for account-level orchestration approval preferences.
Version: 0.261.101
Implemented in: 0.261.101

Exercise the real settings route with isolated authentication/storage dependencies,
its approval vocabulary, and the real TypeScript resolver and preference store.
Run with python -m pytest functional_tests/test_v2_orchestration_approval_persistence.py.
"""

import ast
import copy
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from flask import Flask, jsonify, request

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
V2_ROOT = REPO_ROOT / "application" / "v2_ui" / "src"
SETTING = "orchestrationApprovalMode"


def _approval_modes():
    source = APP_ROOT / "functions_orchestration_schema.py"
    names = {"APPROVAL_MODE_MANUAL", "APPROVAL_MODE_TIMED", "APPROVAL_MODE_AUTO", "APPROVAL_MODES"}
    assignments = [
        node for node in ast.parse(source.read_text(encoding="utf-8")).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)
    ]
    namespace = {}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), str(source), "exec"), namespace)
    return namespace["APPROVAL_MODES"]


@pytest.fixture
def settings_api():
    source = APP_ROOT / "route_backend_users.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    registrar = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_users"
    )
    route = next(
        node for node in registrar.body
        if isinstance(node, ast.FunctionDef) and node.name == "user_settings"
    )
    route.decorator_list = []
    state = {
        "actor": "alice",
        "fail_write": False,
        "writes": [],
        "documents": {
            "alice": {"id": "alice", "settings": {"darkModeEnabled": True}},
            "bob": {"id": "bob", "settings": {SETTING: "timed"}},
        },
    }

    def update_settings(user_id, partial):
        if state["fail_write"]:
            return False
        state["writes"].append((user_id, copy.deepcopy(partial)))
        state["documents"][user_id]["settings"].update(copy.deepcopy(partial))
        return True

    namespace = {
        "APPROVAL_MODES": _approval_modes(),
        "AI_NOTICE_USER_SETTINGS_KEY": "aiNoticeDismissal",
        "LATEST_FEATURES_HIDDEN_VERSION_SETTING": "latestFeaturesHiddenVersion",
        "get_current_user_id": lambda: state["actor"],
        "get_user_settings": lambda user_id: copy.deepcopy(state["documents"][user_id]),
        "update_user_settings": update_settings,
        "jsonify": jsonify,
        "request": request,
    }
    module = ast.fix_missing_locations(ast.Module(body=[route], type_ignores=[]))
    exec(compile(module, str(source), "exec"), namespace)
    app = Flask(__name__)

    def call_route(method="GET", body=None):
        with app.test_request_context("/api/user/settings", method=method, json=body):
            response, status = namespace["user_settings"]()
            response.status_code = status
            return response

    return call_route, state


def test_implementation_version():
    assert_app_version_at_least("0.261.101")


def test_preference_key_is_typed_and_declared_writable():
    source = (V2_ROOT / "lib" / "userSettings.ts").read_text(encoding="utf-8")
    assert f"{SETTING}?: ApprovalMode;" in source
    writable = re.search(r"WRITABLE_USER_SETTING_KEYS = \[(.*?)\] as const", source, re.DOTALL)
    assert writable and f"'{SETTING}'" in writable.group(1)
    assert set(_approval_modes()) == {"manual", "timed", "auto"}


@pytest.mark.parametrize("mode", _approval_modes())
def test_preference_round_trip_preserves_other_settings(settings_api, mode):
    client, state = settings_api
    response = client("POST", {"settings": {SETTING: mode}})
    assert response.status_code == 200
    assert state["writes"] == [("alice", {SETTING: mode})]
    assert client().get_json() == {
        "id": "alice", "settings": {"darkModeEnabled": True, SETTING: mode}
    }


def test_absent_preference_is_not_materialized(settings_api):
    client, state = settings_api
    assert SETTING not in client().get_json()["settings"]
    assert not state["writes"]


@pytest.mark.parametrize("value", ["", "Manual", "invalid", None, True, 1, [], {}])
def test_invalid_preference_rejects_entire_update(settings_api, value):
    client, state = settings_api
    before = copy.deepcopy(state["documents"])
    response = client("POST", {"settings": {SETTING: value, "darkModeEnabled": False}})
    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid orchestration approval mode"}
    assert state["documents"] == before
    assert not state["writes"]


def test_preference_is_scoped_to_authenticated_user(settings_api):
    client, state = settings_api
    response = client("POST", {"user_id": "bob", "settings": {SETTING: "auto"}})
    assert response.status_code == 200
    assert state["writes"] == [("alice", {SETTING: "auto"})]
    state["actor"] = "bob"
    assert client().get_json()["settings"][SETTING] == "timed"
    client("POST", {"settings": {SETTING: "manual"}})
    state["actor"] = "alice"
    assert client().get_json()["settings"][SETTING] == "auto"


def test_storage_failure_is_not_reported_as_success(settings_api):
    client, state = settings_api
    state["fail_write"] = True
    response = client("POST", {"settings": {SETTING: "auto"}})
    assert response.status_code == 500
    assert response.get_json() == {"error": "Failed to update settings"}
    assert SETTING not in client().get_json()["settings"]


def test_runtime_resolution_and_save_ordering():
    node = shutil.which("node")
    assert node, "Node is required for the existing v2 TypeScript runtime tests."
    result = subprocess.run(
        [node, str(REPO_ROOT / "functional_tests" / "test_v2_orchestration_approval_logic.mjs")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
