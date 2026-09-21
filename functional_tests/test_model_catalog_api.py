# test_model_catalog_api.py
"""
Catalog HTTP contracts and real fenced-store writes against offline services.
Version: 0.261.126
Implemented in: 0.261.126

Lift the actual catalog handlers and save function without the route module's
Azure bootstrap. Authentication seams simulate roles; route-policy tests cover
the production decorators. No global modules or production settings are replaced.
"""

import ast
from copy import deepcopy
from functools import wraps
import logging
from pathlib import Path
import socket
import sys

from flask import Flask, jsonify, request
import pytest

from test_app_settings_store_consistency import (
    AppSettingsStore, FakeCosmos, SettingsConflictError, SettingsUnavailableError,
)

APP = Path(__file__).resolve().parents[1] / "application/single_app"
sys.path.insert(0, str(APP))

from functions_model_catalog import (
    ModelCatalogError, TASKS, apply_model_profile, get_effective_model_profiles,
)


@pytest.fixture
def catalog_api(monkeypatch):
    def deny_network(*_args, **_kwargs):
        raise AssertionError("Catalog tests cannot contact external services.")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    cosmos = FakeCosmos()
    cosmos.document["credential_fixture"] = "not-for-the-browser"
    store = AppSettingsStore(cosmos)
    app = Flask(__name__)
    app.config["TESTING"] = True

    def require_role(admin=False):
        def decorate(function):
            @wraps(function)
            def guarded(*args, **kwargs):
                role = request.headers.get("X-Test-Role")
                if not role:
                    return jsonify(error="Sign in"), 401
                if admin and role != "admin":
                    return jsonify(error="Administrator required"), 403
                return function(*args, **kwargs)
            return guarded
        return decorate

    namespace = {
        "request": request, "jsonify": jsonify, "logging": logging,
        "log_event": lambda *_args, **_kwargs: None,
        "ModelCatalogError": ModelCatalogError, "TASKS": TASKS,
        "get_effective_model_profiles": get_effective_model_profiles,
        "apply_model_profile": apply_model_profile,
        "get_settings": store.read, "_get_app_settings_store": lambda: store,
        "SettingsConflictError": SettingsConflictError,
        "SettingsUnavailableError": SettingsUnavailableError,
        "swagger_route": lambda **_kwargs: lambda function: function,
        "get_auth_security": lambda: [],
        "login_required": require_role(), "user_required": require_role(),
        "admin_required": require_role(admin=True),
    }
    settings_tree = ast.parse((APP / "functions_settings.py").read_text())
    save = next(node for node in settings_tree.body if isinstance(node, ast.FunctionDef) and node.name == "save_model_catalog_change")
    exec(compile(ast.Module(body=[save], type_ignores=[]), str(APP / "functions_settings.py"), "exec"), namespace)
    tree = ast.parse((APP / "route_backend_models.py").read_text())
    register = deepcopy(next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_models"))
    handlers = {
        "catalog_response", "read_catalog", "model_catalog_choices", "admin_model_catalog",
        "save_catalog", "create_model_catalog_profile", "update_model_catalog_profile",
    }
    register.body = [node for node in register.body if isinstance(node, ast.FunctionDef) and node.name in handlers]
    assert len(register.body) == len(handlers)
    exec(compile(ast.Module(body=[register], type_ignores=[]), str(APP / "route_backend_models.py"), "exec"), namespace)
    namespace["register_route_backend_models"](app)
    return app.test_client(), cosmos, namespace


def test_authentication_and_safe_user_projection(catalog_api):
    client, _cosmos, _namespace = catalog_api
    for path, method in (("/api/models/catalog", "GET"), ("/api/admin/model-catalog", "GET"),
                         ("/api/admin/model-catalog", "POST"), ("/api/admin/model-catalog/gpt-5", "PATCH")):
        response = client.open(path, method=method, json={})
        assert response.status_code == 401
    denied = client.post("/api/admin/model-catalog", headers={"X-Test-Role": "user"}, json={})
    assert denied.status_code == 403
    choices = client.get("/api/models/catalog", headers={"X-Test-Role": "user"})
    assert choices.status_code == 200
    assert "not-for-the-browser" not in choices.get_data(as_text=True)
    assert "etag" not in choices.json
    assert all("linked_models" not in profile for profile in choices.json["profiles"])


def test_create_conflict_and_archive_use_real_store(catalog_api):
    client, cosmos, _namespace = catalog_api
    headers = {"X-Test-Role": "admin"}
    created = client.post("/api/admin/model-catalog", headers=headers, json={
        "etag": "1", "profile": {"displayName": "Private reusable profile"},
    })
    assert created.status_code == 200
    profile = created.json["profiles"][-1]
    assert profile["id"].startswith("custom:")
    assert cosmos.document["credential_fixture"] == "not-for-the-browser"
    conflict = client.patch(f"/api/admin/model-catalog/{profile['id']}", headers=headers, json={
        "etag": "1", "preferences": {"favorite": True},
    })
    assert conflict.status_code == 409
    assert cosmos.writes == 1
    archived = client.patch(f"/api/admin/model-catalog/{profile['id']}", headers=headers, json={
        "etag": created.json["etag"], "profile": {"displayName": profile["displayName"], "archived": True},
    })
    assert archived.status_code == 200
    choices = client.get("/api/models/catalog", headers={"X-Test-Role": "user"})
    assert all(item["id"] != profile["id"] for item in choices.json["profiles"])


def test_invalid_profile_and_unconfirmed_save_are_not_success(catalog_api):
    client, cosmos, namespace = catalog_api
    headers = {"X-Test-Role": "admin"}
    invalid = client.patch("/api/admin/model-catalog/gpt-5", headers=headers, json={
        "etag": "1", "profile": {"displayName": "Overwrite packaged facts"},
    })
    assert invalid.status_code == 400
    assert cosmos.writes == 0

    def unavailable():
        raise SettingsUnavailableError("Internal cache location must not leak")

    namespace["_get_app_settings_store"] = unavailable
    failed = client.post("/api/admin/model-catalog", headers=headers, json={
        "etag": "1", "profile": {"displayName": "Unsaved"},
    })
    assert failed.status_code == 503
    assert "Internal cache" not in failed.get_data(as_text=True)


def test_catalog_read_failure_is_safe_and_explicit(catalog_api):
    client, cosmos, _namespace = catalog_api
    cosmos.failed = True
    failed = client.get("/api/admin/model-catalog", headers={"X-Test-Role": "admin"})
    assert failed.status_code == 503
    assert "Unable to load" in failed.json["error"]
