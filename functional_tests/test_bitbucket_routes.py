# test_bitbucket_routes.py
"""
Functional tests for Bitbucket routes, identity hydration and authoring policy.
Version: 0.261.451
Implemented in: 0.261.450
Error-boundary regression implemented in: 0.261.451

Real modules run in a fresh offline bootstrap with scoped external/actor seams.
Exercises canonical callback configuration, CSRF, private status and edit-only discovery.
"""

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"


def test_real_bitbucket_route_identity_and_plugin_integration():
    probe = r"""
import copy
import importlib
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch
from flask import Blueprint, Flask
from cryptography.fernet import Fernet
from test_support.offline_bootstrap import offline_app_imports
from test_support.m365 import CosmosContainer
from test_bitbucket_action_plugin import manifest
with offline_app_imports():
    routes = importlib.import_module("route_backend_bitbucket")
    connections = importlib.import_module("functions_bitbucket_connections")
    identities = importlib.import_module("functions_workspace_identities")
    plugin_module = importlib.import_module("semantic_kernel_plugins.bitbucket_plugin")
    governance = importlib.import_module("functions_governance")
    from azure.cosmos._cosmos_responses import CosmosDict
    from functions_action_manifest import bind_action_origin
    with patch.object(governance, "cosmos_governance_policies_container", CosmosContainer("id")), \
         patch.object(governance, "cosmos_governance_item_policies_container", CosmosContainer("id")), \
         patch.object(governance, "get_settings", return_value={"governance_user_actions": True}), \
         patch.object(governance, "get_user_governance_group_ids", return_value=set()), \
         patch.object(governance, "log_governance_change"):
        feature = governance.upsert_feature_policy("governance_user_actions", {"allow_all": True}, "admin", "")
        policy = governance.upsert_item_policy("personal_action_type", "bitbucket", {
            "allow_all": False, "allowed_users": ["actor"], "denied_users": ["other"],
        }, "admin", "")
        assert isinstance(feature, CosmosDict) and isinstance(policy, CosmosDict)
        governance.ensure_action_type_access("governance_user_actions", "actor", "bitbucket", "personal")
        try:
            governance.ensure_action_type_access("governance_user_actions", "other", "bitbucket", "personal")
        except PermissionError:
            pass
        else:
            raise AssertionError("Bitbucket type policy did not enforce the saved SDK policy")
        assert governance.get_governed_action_type_label("bitbucket") == "Bitbucket"
        governance.invalidate_governance_cache()
    record = manifest()
    record["auth"] = {"type": "user", "identity": "oauth-client", "key": "private-client-secret"}
    record["additionalFields"]["auth_method"] = "oauth"
    def authorize(user, reference):
        scope, scope_id, action_id = reference.split(":", 2)
        if scope == "personal" and scope_id != user:
            raise PermissionError("Not your action")
        return bind_action_origin(copy.deepcopy(record), scope, scope_id)
    service = connections.BitbucketConnections(
        CosmosContainer("user_id"), authorize, key_provider=lambda: Fernet(b"zFCFYhfl8RR--EK2uJWvX8Khq6m-uTfhEOzMBc3_bN4="),
    )
    app = Flask(__name__, template_folder=str(__import__("pathlib").Path(routes.__file__).parent / "templates"))
    app.secret_key = "offline-bitbucket-test"
    with patch.object(routes, "login_required", lambda function: function), \
         patch.object(routes, "user_required", lambda function: function), \
         patch.object(routes, "get_current_user_id", lambda: "actor"), \
         patch.object(routes, "get_current_user_info", lambda: {"roles": []}), \
         patch.object(connections, "_service", service):
        bp = Blueprint("backend_bitbucket", __name__)
        routes.register_route_backend_bitbucket(bp)
        app.register_blueprint(bp)
        client = app.test_client()
        status = client.get("/api/bitbucket/connection?action_ref=personal:self:review")
        assert status.status_code == 200 and not status.json["connected"]
        assert status.headers["Cache-Control"] == "no-store"
        csrf = status.json["csrf_token"]
        for error_type, expected_status, expected_message in (
            (KeyError, 400, "Invalid Bitbucket configuration or request."),
            (ValueError, 400, "Invalid Bitbucket configuration or request."),
            (TypeError, 400, "Invalid Bitbucket configuration or request."),
            (LookupError, 404, "The Bitbucket action is unavailable."),
            (IndexError, 404, "The Bitbucket action is unavailable."),
            (PermissionError, 404, "The Bitbucket action is unavailable."),
        ):
            with patch.object(service, "status", side_effect=error_type("private-error-detail")):
                failed = client.get("/api/bitbucket/connection?action_ref=personal:self:review")
            assert failed.status_code == expected_status, (error_type.__name__, failed.json)
            assert failed.json == {"error": expected_message}
            assert failed.headers["Cache-Control"] == "no-store"
            assert failed.headers["Referrer-Policy"] == "no-referrer"
        assert client.get("/api/bitbucket/connection?action_ref=personal:other:review").status_code == 404
        assert client.post("/api/bitbucket/connect", json={"action_ref": "personal:self:review"}).status_code == 403
        headers = {"X-CSRFToken": csrf}
        assert client.post("/api/bitbucket/disconnect", headers={**headers, "Sec-Fetch-Site": "cross-site"},
                           json={"action_ref": "personal:self:review"}).status_code == 403
        with patch.dict("os.environ", {"BITBUCKET_REDIRECT_URI": ""}):
            assert client.post("/api/bitbucket/connect", headers=headers, json={"action_ref": "personal:self:review"}).status_code == 503
        with patch.dict("os.environ", {"BITBUCKET_REDIRECT_URI": "https://simplechat.example.test/api/bitbucket/callback"}):
            result = client.post("/api/bitbucket/connect", headers={**headers, "X-Forwarded-Host": "attacker.invalid"},
                                 json={"action_ref": "personal:self:review"})
            assert result.status_code == 200, result.json
            query = parse_qs(urlsplit(result.json["authorization_url"]).query)
            assert query["redirect_uri"] == ["https://simplechat.example.test/api/bitbucket/callback"]
        with client.session_transaction() as browser:
            binding = browser["bitbucket_session_binding"]
        with patch.object(service, "exchange", return_value={"access_token": "private-access", "refresh_token": "private-refresh", "expires_in": 3600}):
            callback = client.get("/api/bitbucket/callback", query_string={"state": query["state"][0], "code": "private-code"})
            assert callback.status_code == 200
            replay = client.get("/api/bitbucket/callback", query_string={"state": query["state"][0], "code": "private-code"})
            assert replay.status_code == 400
        assert client.get("/bitbucket/connect?action_ref=personal:self:review").status_code == 200
        with patch.object(routes, "BitbucketClient") as factory:
            factory.return_value.discover.return_value = {"repositories": [], "next_cursor": None}
            found = client.post("/api/bitbucket/discover", headers=headers, json={"action_ref": "personal:self:review", "project": "team"})
            assert found.status_code == 200
            factory.return_value.discover.assert_called_once_with("team", 0)
            denied = client.post("/api/bitbucket/discover", headers=headers, json={"action_ref": "global:global:review", "project": "team"})
            assert denied.status_code == 404
            assert factory.call_count == 1
            with patch.object(routes, "find_group_by_id", return_value={"id": "group", "status": "active"}), \
                 patch.object(routes, "get_user_role_in_group", return_value="User"), \
                 patch.object(routes, "get_settings", return_value={"enable_group_workspaces": True}):
                denied = client.post("/api/bitbucket/discover", headers=headers, json={"action_ref": "group:group:review", "project": "team"})
                assert denied.status_code == 404
        disconnected = client.post("/api/bitbucket/disconnect", headers=headers, json={"action_ref": "personal:self:review"})
        assert disconnected.status_code == 200 and disconnected.json == {"connected": False}
        saved = copy.deepcopy(record)
        saved["additionalFields"]["auth_method"] = "bearer_token"
        saved["auth"] = {"type": "identity", "identity": "identity-id"}
        hydrated = identities._apply_action_identity_auth(saved, {"auth_type": "bearer_token", "secret": "identity-private"})
        assert hydrated["auth"]["key"] == "identity-private"
        try:
            identities._apply_action_identity_auth(saved, {"auth_type": "username_password", "username": "email", "password": "private"})
        except ValueError:
            pass
        else:
            raise AssertionError("Mismatched identity auth method accepted")
        plugin = plugin_module.BitbucketPlugin(authorize("actor", "personal:actor:review"))
        with patch.object(plugin_module, "actor_context", return_value=("actor", "chat", None)), \
             patch.object(plugin_module, "authorized_manifest", side_effect=authorize):
            result = plugin.list_repositories()
            assert result["error"] == "reconnect_required" and result["connect_url"].startswith("/bitbucket/connect?")
            assert "private-client-secret" not in repr(result)
    """
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join((str(APP), str(ROOT / "functional_tests")))}
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=environment,
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
