# personal_file_source_harness.py
"""
Isolated personal File Sync routes using the existing real engine/Key Vault harness.
Version: 0.261.311
Implemented in: 0.261.310
"""

import importlib.util
import sys
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask

from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub
from test_support.group_file_source_harness import as_user, smb_payload


LIST_PATH = "/api/file-sync/personal/sources"
OPTIONS_PATH = "/api/file-sync/personal/source-options"


@pytest.fixture
def personal_environment(environment, monkeypatch):
    """Run the real personal route module with cloud I/O replaced by the shared harness."""
    env = environment
    auth = sys.modules["functions_authentication"]
    namespace = dict(vars(auth))
    execute_functions("functions_authentication.py", {"admin_required"}, namespace)
    monkeypatch.setattr(auth, "admin_required", namespace["admin_required"], raising=False)
    monkeypatch.setattr(auth, "enabled_required", sys.modules["functions_settings"].enabled_required, raising=False)
    groups = sys.modules["functions_group"]
    monkeypatch.setattr(groups, "require_active_group", Mock(), raising=False)
    monkeypatch.setattr(groups, "search_all_groups", Mock(), raising=False)
    monkeypatch.setattr(sys.modules["functions_public_workspaces"], "search_all_public_workspaces", Mock(), raising=False)
    monkeypatch.setitem(sys.modules, "functions_simplechat_operations", module_stub(
        "functions_simplechat_operations", search_directory_users=Mock(),
    ))
    spec = importlib.util.spec_from_file_location("route_backend_file_sync", APP_ROOT / "route_backend_file_sync.py")
    routes = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "route_backend_file_sync", routes)
    spec.loader.exec_module(routes)
    app = Flask("personal_file_source_contract")
    app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
    blueprint = Blueprint("backend_file_sync", __name__)
    blueprint.before_request(auth.user_required_blueprint())
    routes.register_route_backend_file_sync(blueprint)
    app.register_blueprint(blueprint)
    app.extensions["executor"] = env.executor
    env.app, env.client = app, app.test_client()
    env.sources_container = env.filesync._get_sources_container("personal")
    env.items_container = env.filesync._get_items_container("personal")
    env.runs_container = env.filesync._get_runs_container("personal")
    env.routes = routes
    as_user(env, "owner")
    yield env


def create_personal_source(env, payload=None):
    response = env.client.post(LIST_PATH, json=payload or smb_payload())
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["source"]
