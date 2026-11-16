# test_v2_orchestration_model_routing_preference.py
"""
Functional regressions for the account-level Orchestrate model preference.
Version: 0.261.137
Implemented in: 0.261.137

The Orchestrate model choice (Auto, or one pinned model) used to live only in the composer's
component state, so it reset whenever the composer remounted. It is now saved to the account.
Exercise the real settings route with isolated authentication/storage dependencies, the V2
key declarations, and the real TypeScript resolver.
Run with python -m pytest functional_tests/test_v2_orchestration_model_routing_preference.py.
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
ROUTING = "orchestrationModelRouting"
PINNED = "orchestrationPreferredModelId"


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
        "writes": [],
        "documents": {
            "alice": {"id": "alice", "settings": {"darkModeEnabled": True, "preferredModelId": "normal"}},
            "bob": {"id": "bob", "settings": {ROUTING: "manual", PINNED: "bob-model"}},
        },
    }

    def update_settings(user_id, partial):
        state["writes"].append((user_id, copy.deepcopy(partial)))
        state["documents"][user_id]["settings"].update(copy.deepcopy(partial))
        return True

    namespace = {
        "APPROVAL_MODES": ("manual", "timed", "auto"),
        "AI_NOTICE_USER_SETTINGS_KEY": "aiNoticeDismissal",
        "LATEST_FEATURES_HIDDEN_VERSION_SETTING": "latestFeaturesHiddenVersion",
        "get_current_user_id": lambda: state["actor"],
        "get_user_settings": lambda user_id: copy.deepcopy(state["documents"][user_id]),
        # The GET path sanitizes before returning; these documents hold no secrets.
        "sanitize_settings_for_user": copy.deepcopy,
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
    assert_app_version_at_least("0.261.137")


def test_keys_are_typed_declared_writable_and_whitelisted():
    source = (V2_ROOT / "lib" / "userSettings.ts").read_text(encoding="utf-8")
    assert f"{ROUTING}?: 'auto' | 'manual';" in source
    assert f"{PINNED}?: string;" in source
    writable = re.search(r"WRITABLE_USER_SETTING_KEYS = \[(.*?)\] as const", source, re.DOTALL)
    assert writable and f"'{ROUTING}'" in writable.group(1) and f"'{PINNED}'" in writable.group(1)
    users = (APP_ROOT / "route_backend_users.py").read_text(encoding="utf-8")
    allowed = re.search(r"allowed_keys = \{(.*?)\}", users, re.DOTALL)
    assert allowed and f"'{ROUTING}'" in allowed.group(1) and f"'{PINNED}'" in allowed.group(1)


@pytest.mark.parametrize("routing", ["auto", "manual"])
def test_routing_round_trip_preserves_other_settings(settings_api, routing):
    client, state = settings_api
    response = client("POST", {"settings": {ROUTING: routing}})
    assert response.status_code == 200
    assert state["writes"] == [("alice", {ROUTING: routing})]
    assert client().get_json()["settings"] == {
        "darkModeEnabled": True, "preferredModelId": "normal", ROUTING: routing,
    }


def test_pin_is_stored_trimmed_and_leaves_the_normal_chat_model_alone(settings_api):
    client, state = settings_api
    response = client("POST", {"settings": {ROUTING: "manual", PINNED: "  global::east:writer  "}})
    assert response.status_code == 200
    saved = client().get_json()["settings"]
    assert saved[PINNED] == "global::east:writer"
    assert saved["preferredModelId"] == "normal"


@pytest.mark.parametrize("value", ["", "Auto", "pinned", None, True, 1, [], {}])
def test_invalid_routing_rejects_the_entire_update(settings_api, value):
    client, state = settings_api
    before = copy.deepcopy(state["documents"])
    response = client("POST", {"settings": {ROUTING: value, "darkModeEnabled": False}})
    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid orchestration model routing"}
    assert state["documents"] == before and not state["writes"]


@pytest.mark.parametrize("value", ["", "   ", "x" * 513, "model\u0000id", "line\nbreak", None, 5, [], {}])
def test_invalid_pin_rejects_the_entire_update(settings_api, value):
    client, state = settings_api
    before = copy.deepcopy(state["documents"])
    response = client("POST", {"settings": {ROUTING: "manual", PINNED: value}})
    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid orchestration model"}
    assert state["documents"] == before and not state["writes"]


def test_preference_is_scoped_to_the_authenticated_user(settings_api):
    client, state = settings_api
    response = client("POST", {"user_id": "bob", "settings": {ROUTING: "auto"}})
    assert response.status_code == 200
    assert state["writes"] == [("alice", {ROUTING: "auto"})]
    state["actor"] = "bob"
    assert client().get_json()["settings"] == {ROUTING: "manual", PINNED: "bob-model"}


def test_absent_preference_is_not_materialized(settings_api):
    client, state = settings_api
    settings = client().get_json()["settings"]
    assert ROUTING not in settings and PINNED not in settings and not state["writes"]


def test_real_resolver_logic():
    node = shutil.which("node")
    assert node, "Node is required for the existing v2 TypeScript runtime tests."
    result = subprocess.run(
        [node, str(REPO_ROOT / "functional_tests" / "test_v2_orchestration_model_routing_logic.mjs")],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
