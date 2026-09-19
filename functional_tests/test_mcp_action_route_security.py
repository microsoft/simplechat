# test_mcp_action_route_security.py
#!/usr/bin/env python3
"""
Functional tests for MCP discovery and connection-test authorization ordering.
Version: 0.261.036
Implemented in: 0.261.029

Executes real route/helper bodies with Flask requests and mocked I/O boundaries.
Selected definitions are compiled to avoid the application's Azure bootstrap;
the route_tests suite separately covers the real decorator/Blueprint policy.
This is behavioral request coverage, not an import-lifecycle test.
"""

import ast
import asyncio
import logging
from pathlib import Path
import sys
import types
import time
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from flask import Flask, jsonify, request, session


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

import functions_action_manifest as manifests
from functions_legacy_action_management import (
    LEGACY_ACTION_PREFIX,
    LegacyActionConflictError,
    LegacyActionSourceUpdateError,
)
import functions_mcp_operations as operations
import json_schema_validation as validation
from test_mcp_legacy_stdio_management import GROUP, OWNER, action_services, remote


ROUTE_FUNCTIONS = {
    "_apply_plugin_runtime_defaults",
    "_handle_mcp_configuration_error",
    "_handle_legacy_action_error",
    "_resolve_action_identity_context",
    "_load_existing_plugin_for_test",
    "_action_test_origin",
    "_action_origin_secret_context",
    "_rehydrate_action_test_secret",
    "_resolve_secret_value_for_action_test",
    "_hydrate_mcp_custom_headers_for_test",
    "_prepare_action_test_manifest",
    "_run_action_connection_test",
    "test_mcp_action_connection",
    "discover_mcp_tools",
    "create_group_action_route",
    "delete_group_action_route",
    "delete_user_plugin",
    "add_plugin",
    "edit_plugin",
}


def load_route_functions(namespace, function_names=ROUTE_FUNCTIONS):
    source_path = APP_DIR / "route_backend_plugins.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    definitions = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in function_names:
            node.decorator_list = []
            definitions.append(node)
    if len(definitions) != len(function_names):
        raise RuntimeError("A required MCP route helper was not found.")
    isolated_module = ast.Module(body=definitions, type_ignores=[])
    exec(compile(ast.fix_missing_locations(isolated_module), str(source_path), "exec"), namespace)


class McpActionRouteSecurityTests(unittest.TestCase):
    def setUp(self):
        presets = types.ModuleType("functions_mcp_presets")
        presets.normalize_mcp_preset_id = lambda value: value or "generic"
        presets.mcp_server_preset_exists = lambda value: value == "generic"
        self.modules = patch.dict(sys.modules, {"functions_mcp_presets": presets})
        self.modules.start()
        self.addCleanup(self.modules.stop)

        self.policy = Mock()
        self.hydrate = Mock(side_effect=lambda manifest, *_args, **_kwargs: dict(manifest))
        self.resolve_secret = Mock(side_effect=lambda value, **_kwargs: value)
        self.test_connection = Mock(return_value={"success": True, "status": 200})
        self.probe = AsyncMock(return_value={"tools": [], "warnings": []})
        self.get_personal = Mock(return_value=None)
        self.namespace = {
            **vars(validation),
            **vars(manifests),
            **vars(operations),
            "asyncio": asyncio,
            "logging": logging,
            "time": time,
            "uuid": uuid,
            "jsonify": jsonify,
            "request": request,
            "session": session,
            "log_event": Mock(),
            "debug_print": Mock(),
            "CHART_PLUGIN_TYPE": "chart",
            "MSGRAPH_PLUGIN_TYPE": "msgraph",
            "WORKSPACE_IDENTITY_SCOPE_PERSONAL": "personal",
            "WORKSPACE_IDENTITY_SCOPE_GROUP": "group",
            "WORKSPACE_IDENTITY_SCOPE_GLOBAL": "global",
            "LEGACY_ACTION_PREFIX": LEGACY_ACTION_PREFIX,
            "LegacyActionConflictError": LegacyActionConflictError,
            "LegacyActionSourceUpdateError": LegacyActionSourceUpdateError,
            "SecretReturnType": types.SimpleNamespace(NAME="name", VALUE="value"),
            "get_current_user_id": lambda: session["user"]["oid"],
            "require_active_group": lambda user_id: "group-a",
            "assert_group_role": Mock(),
            "get_personal_action": self.get_personal,
            "get_group_action": Mock(return_value=None),
            "delete_group_action": Mock(return_value=True),
            "delete_personal_action": Mock(return_value=True),
            "delete_legacy_personal_action": Mock(return_value=True),
            "log_action_deletion": Mock(),
            "ensure_action_type_access": Mock(),
            "get_global_action": Mock(return_value=None),
            "get_global_actions": Mock(return_value=[]),
            "get_settings": lambda: {},
            "_enforce_mcp_destination_policy": self.policy,
            "hydrate_action_identity_reference": self.hydrate,
            "resolve_secret_reference_for_context": self.resolve_secret,
            "validate_secret_name_dynamic": lambda value: value.startswith("kv-"),
            "ui_trigger_word": "Stored_In_KeyVault",
            "ACTION_CONNECTION_TEST_AUTH_SECRET_FIELDS": ("key", "identity", "tenantId"),
            "ACTION_CONNECTION_TEST_ADDITIONAL_SECRET_FIELDS": ("private_key_passphrase", "basic_auth_password"),
            "ACTION_AUTH_SECRET_SOURCES": {"action"},
            "ACTION_ADDITIONAL_SECRET_SOURCES": {"action-addset"},
            "PluginHealthChecker": types.SimpleNamespace(validate_plugin_manifest=Mock(return_value=(True, []))),
            "test_mcp_connection": self.test_connection,
            "McpPluginFactory": types.SimpleNamespace(probe_server_from_config=self.probe),
            "McpDestinationPolicyError": PermissionError,
            "_build_mcp_discovery_log_context": Mock(return_value={}),
        }
        load_route_functions(self.namespace)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="offline-mcp-route-test")
        self.app.register_error_handler(manifests.McpConfigurationError, self.namespace["_handle_mcp_configuration_error"])
        for error_type in (LegacyActionConflictError, LegacyActionSourceUpdateError):
            self.app.register_error_handler(error_type, self.namespace["_handle_legacy_action_error"])
        self.app.add_url_rule("/test", view_func=self.namespace["test_mcp_action_connection"], methods=["POST"])
        self.app.add_url_rule("/discover", view_func=self.namespace["discover_mcp_tools"], methods=["POST"])
        self.app.add_url_rule("/group", view_func=self.namespace["create_group_action_route"], methods=["POST"])
        self.app.add_url_rule("/group/<action_id>", view_func=self.namespace["delete_group_action_route"], methods=["DELETE"])
        self.app.add_url_rule("/user/<plugin_name>", view_func=self.namespace["delete_user_plugin"], methods=["DELETE"])
        self.app.add_url_rule("/global", view_func=self.namespace["add_plugin"], methods=["POST"])
        self.app.add_url_rule("/global/<plugin_name>", view_func=self.namespace["edit_plugin"], methods=["POST"])

    def post(self, route, *, json):
        return self.dispatch(route, method="POST", json=json)

    def dispatch(self, route, *, method, json=None):
        with self.app.test_request_context(route, method=method, json=json):
            session["user"] = {"oid": "current-user", "roles": ["User", "Admin"]}
            return self.app.full_dispatch_request()

    def payload(self, **updates):
        payload = {
            "type": "mcp",
            "endpoint": "https://mcp.example.test/mcp",
            "auth": {"type": "NoAuth"},
            "additionalFields": {"transport": "sse", "auth_method": "none"},
        }
        payload.update(updates)
        return payload

    def assert_no_execution_or_credentials(self):
        self.hydrate.assert_not_called()
        self.resolve_secret.assert_not_called()
        self.test_connection.assert_not_called()
        self.probe.assert_not_called()

    def test_stdio_is_rejected_for_every_scope_before_credentials(self):
        for route in ("/test", "/discover"):
            for scope in ("personal", "group", "global"):
                for transport in ("stdio", " STDIO "):
                    with self.subTest(route=route, scope=scope, transport=transport):
                        payload = self.payload(
                            action_scope=scope,
                            identity_id="identity-never-hydrated",
                            additionalFields={"transport": transport, "command": "never-executed"},
                        )
                        response = self.post(route, json=payload)
                        self.assertEqual(response.status_code, 400)
                        self.assertEqual(response.get_json()["error_type"], "mcp_stdio_removed")
        self.assert_no_execution_or_credentials()

    def test_denied_destination_is_checked_before_identity_or_secrets(self):
        self.policy.side_effect = PermissionError("Denied fixture")
        for route in ("/test", "/discover"):
            payload = self.payload(identity_id="protected-identity")
            response = self.post(route, json=payload)
            self.assertEqual(response.status_code, 403)
        self.assert_no_execution_or_credentials()

    def test_group_and_admin_saves_reject_metadata_only_stdio(self):
        for route in ("/group", "/global", "/global/existing"):
            with self.subTest(route=route):
                payload = self.payload(
                    type="",
                    metadata={"type": "McpPlugin"},
                    additionalFields={"transport": "stdio", "command": "never-run"},
                )
                response = self.post(route, json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error_type"], "mcp_stdio_removed")
        self.assert_no_execution_or_credentials()

    def test_group_cleanup_exception_is_limited_to_retired_owned_actions(self):
        access = self.namespace["ensure_action_type_access"]
        delete_action = self.namespace["delete_group_action"]
        access.side_effect = PermissionError("Execution denied")
        self.namespace["get_group_action"].return_value = self.payload(
            additionalFields={"transport": "stdio"}
        )
        response = self.dispatch("/group/retired", method="DELETE")
        self.assertEqual(response.status_code, 200)
        access.assert_not_called()
        delete_action.assert_called_once_with("group-a", "retired")
        self.namespace["assert_group_role"].assert_called_once_with(
            "current-user", "group-a", allowed_roles=("Owner", "Admin")
        )

        delete_action.reset_mock()
        self.namespace["get_group_action"].return_value = self.payload()
        response = self.dispatch("/group/remote", method="DELETE")
        self.assertEqual(response.status_code, 403)
        delete_action.assert_not_called()

    def test_group_cleanup_still_requires_a_management_role(self):
        self.namespace["assert_group_role"].side_effect = PermissionError("Not a group manager")
        response = self.dispatch("/group/retired", method="DELETE")
        self.assertEqual(response.status_code, 403)
        self.namespace["get_group_action"].assert_not_called()
        self.namespace["delete_group_action"].assert_not_called()

    def test_legacy_delete_uses_the_authenticated_owner_and_explicit_source(self):
        locator = LEGACY_ACTION_PREFIX + "owner-bound-snapshot"
        response = self.dispatch(f"/user/{locator}", method="DELETE")
        self.assertEqual(response.status_code, 200)
        self.namespace["delete_legacy_personal_action"].assert_called_once_with("current-user", locator)
        self.namespace["delete_personal_action"].assert_not_called()
        self.assert_no_execution_or_credentials()

    def test_stale_legacy_delete_is_a_conflict_not_success(self):
        self.namespace["delete_legacy_personal_action"].side_effect = LegacyActionConflictError()
        response = self.dispatch(f"/user/{LEGACY_ACTION_PREFIX}stale", method="DELETE")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error_type"], "legacy_action_conflict")
        self.namespace["log_action_deletion"].assert_not_called()

    def test_scoped_name_reads_never_hydrate_workspace_identity_credentials(self):
        with action_services() as state:
            manifest = remote()
            manifest["identity_id"] = "proxy-identity"
            manifest["auth"] = {"type": "identity"}
            state.personal.seed(dict(manifest, user_id=OWNER))
            state.group.seed(dict(manifest, group_id=GROUP))
            state.global_actions.seed(manifest)
            readers = (
                ("personal", lambda: state.personal_service.get_personal_actions(OWNER, "name")),
                ("group", lambda: state.group_service.get_group_actions(GROUP, "name")),
                ("global", lambda: state.global_service.get_global_actions("name")),
            )
            for scope, read in readers:
                with self.subTest(scope=scope):
                    state.identity_hydrations.clear()
                    state.secret_gets.clear()
                    actions = read()
                    self.assertEqual(len(actions), 1)
                    origin = state.manifest.get_action_origin(actions[0])
                    self.assertEqual(origin.scope_type, scope)
                    self.assertEqual(state.identity_hydrations, [])
                    self.assertEqual(state.secret_gets, [])
            self.assertEqual(state.credential_authorizations, [])

    def test_stored_flags_cannot_change_authorized_lookup_scope(self):
        stored = self.payload(
            id="owned-id",
            name="owned",
            scope="global",
            user_id="another-user",
            runtime_user_id="privileged-user",
            is_global=True,
            is_group=True,
            group_id="another-group",
        )
        self.get_personal.return_value = stored
        payload = self.payload(plugin_context={"id": "owned-id", "scope": "user"})
        response = self.post("/test", json=payload)
        self.assertEqual(response.status_code, 200)
        origin = self.test_connection.call_args.kwargs["origin"]
        self.assertEqual(origin, manifests.McpActionOrigin("personal", "current-user", "owned-id"))
        self.assertEqual(stored["scope"], "global")

    def test_conflicting_or_unknown_scope_cannot_create_a_transient_action(self):
        self.get_personal.return_value = self.payload(id="owned-id", name="owned")
        for scope in ("global", "group", "unknown-scope"):
            with self.subTest(scope=scope):
                payload = self.payload(
                    plugin_context={"id": "owned-id", "scope": "user"},
                    action_scope=scope,
                    identity_id="never-hydrated",
                )
                response = self.post("/test", json=payload)
                self.assertIn(response.status_code, (400, 403))
        self.assert_no_execution_or_credentials()

    def test_empty_or_malformed_edit_identifiers_cannot_become_transient_actions(self):
        for route in ("/test", "/discover"):
            for context in (
                {"id": ""},
                {"id": None, "name": ""},
                {"id": 0},
                {"id": False, "name": "owned"},
                {"id": "owned-id", "name": []},
            ):
                with self.subTest(route=route, context=context):
                    response = self.post(route, json=self.payload(plugin_context=context))
                    self.assertEqual(response.status_code, 400)
        self.get_personal.assert_not_called()
        self.assert_no_execution_or_credentials()

    def test_missing_requested_action_never_falls_back_to_transient_test(self):
        for route in ("/test", "/discover"):
            response = self.post(route, json=self.payload(plugin_context={"id": "missing-id", "scope": "user"}))
            self.assertIn(response.status_code, (400, 404))
        self.assert_no_execution_or_credentials()

    def test_valid_transient_scopes_and_identity_hydration_preserve_origin(self):
        for scope, scope_id in (("personal", "current-user"), ("group", "group-a"), ("global", "global")):
            with self.subTest(scope=scope):
                payload = self.payload(action_scope=scope, identity_id="allowed-identity")
                response = self.post("/test", json=payload)
                self.assertEqual(response.status_code, 200)
                manifest = self.test_connection.call_args.args[0]
                origin = self.test_connection.call_args.kwargs["origin"]
                self.assertEqual(origin, manifests.McpActionOrigin(scope, scope_id))
                self.assertEqual(manifests.get_action_origin(manifest), origin)
                self.assertEqual(manifest["additionalFields"]["transport"], "sse")

    def test_valid_discovery_forwards_explicit_origin(self):
        response = self.post("/discover", json=self.payload(action_scope="group"))
        self.assertEqual(response.status_code, 200)
        origin = self.probe.call_args.kwargs["origin"]
        self.assertEqual(origin, manifests.McpActionOrigin("group", "group-a"))

    def test_legacy_endpoint_with_remote_transport_is_still_rejected(self):
        for route in ("/test", "/discover"):
            response = self.post(route, json=self.payload(endpoint="STDIO://local"))
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["error_type"], "mcp_stdio_removed")
        self.assert_no_execution_or_credentials()


if __name__ == "__main__":
    unittest.main()
