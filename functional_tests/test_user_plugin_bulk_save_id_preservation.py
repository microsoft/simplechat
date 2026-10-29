# test_user_plugin_bulk_save_id_preservation.py
#!/usr/bin/env python3
"""
Functional tests for personal action bulk-save identity and preflight safety.
Version: 0.261.037
Implemented in: 0.240.019
Updated in: 0.261.037

Runs the real bulk route body with Flask request dispatch and isolated storage.
Preserves rename coverage and verifies invalid batches cause no writes/deletes.
Blueprint authentication is independently covered by the route policy suite.
"""

from copy import deepcopy
import logging
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify, request
from azure.cosmos import exceptions as cosmos_exceptions


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

import functions_action_manifest as manifests
import functions_legacy_action_management as legacy
import functions_mcp_operations as operations
import json_schema_validation as schema_validation
from test_mcp_action_route_security import load_route_functions


def action_fixture(name="original", action_id="existing-id"):
    return {
        "id": action_id,
        "name": name,
        "displayName": name,
        "type": "mcp",
        "description": "Offline bulk-save fixture",
        "endpoint": "https://mcp.example.test/mcp",
        "auth": {"type": "NoAuth"},
        "metadata": {"type": "mcp"},
        "additionalFields": {"transport": "sse", "auth_method": "none"},
    }


class UserPluginBulkSaveTests(unittest.TestCase):
    def setUp(self):
        self.current = [action_fixture()]
        self.saved = []
        self.deleted = []
        self.validated = []
        self.legacy_views = []
        self.reconfigured = []
        self.preflight_reconfiguration = Mock()
        self.type_access = Mock()
        presets = types.ModuleType("functions_mcp_presets")
        presets.normalize_mcp_preset_id = lambda value: value or "generic"
        presets.mcp_server_preset_exists = lambda value: True
        module_patch = patch.dict(sys.modules, {"functions_mcp_presets": presets})
        module_patch.start()
        self.addCleanup(module_patch.stop)

        def validate_plugin(manifest):
            self.validated.append(deepcopy(manifest))
            return schema_validation.validate_plugin(manifest)

        def save_personal_action(user_id, manifest):
            saved = deepcopy(manifest)
            self.saved.append(saved)
            return saved

        self.namespace = {
            **vars(schema_validation),
            **vars(manifests),
            **vars(operations),
            **vars(legacy),
            "logging": logging,
            "jsonify": jsonify,
            "request": request,
            "get_current_user_id": lambda: "current-user",
            "get_global_actions": lambda *args, **kwargs: [],
            "get_personal_actions": lambda *args, **kwargs: [
                legacy.retired_action_management_view(action, "personal", "current-user") or deepcopy(action)
                for action in self.current
            ],
            "get_personal_action_record": lambda user_id, action_id: next(
                (deepcopy(action) for action in self.current if action.get("id") == action_id), None
            ),
            "list_legacy_personal_actions": lambda user_id: deepcopy(self.legacy_views),
            "reconfigure_legacy_personal_action": lambda user_id, locator, manifest: self.reconfigured.append(
                (user_id, locator, deepcopy(manifest))
            ),
            "prepare_legacy_personal_action_reconfiguration": self.preflight_reconfiguration,
            "save_personal_action": save_personal_action,
            "delete_personal_action": lambda user_id, action_id: self.deleted.append(action_id),
            "SecretReturnType": types.SimpleNamespace(NAME="name"),
            "PLUGIN_STORAGE_MANAGED_FIELDS": schema_validation.PLUGIN_STORAGE_MANAGED_FIELDS,
            "CHART_PLUGIN_TYPE": "chart",
            "MSGRAPH_PLUGIN_TYPE": "msgraph",
            "WORKSPACE_IDENTITY_SCOPE_PERSONAL": "personal",
            "_validate_action_identity_for_scope": Mock(),
            "ensure_action_type_access": self.type_access,
            "validate_plugin": validate_plugin,
            "PluginHealthChecker": types.SimpleNamespace(validate_plugin_manifest=Mock(return_value=(True, []))),
            "_enforce_mcp_destination_policy": Mock(),
            "_redact_plugin_for_logging": lambda plugin: {"name": plugin.get("name")},
            "debug_print": Mock(),
            "log_event": Mock(),
            "log_action_update": Mock(),
            "log_action_creation": Mock(),
            "log_action_deletion": Mock(),
            "ACTION_VALIDATION_ERROR_MESSAGE": "Invalid action configuration.",
            "ACTION_PERMISSION_ERROR_MESSAGE": "Not authorized.",
            "ACTION_KEY_VAULT_ERROR_MESSAGE": "Unable to store secrets.",
        }
        load_route_functions(self.namespace, {
            "_apply_plugin_runtime_defaults", "_handle_mcp_configuration_error",
            "_handle_legacy_action_error", "set_user_plugins",
        })
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_error_handler(manifests.McpConfigurationError, self.namespace["_handle_mcp_configuration_error"])
        self.app.register_error_handler(legacy.LegacyActionConflictError, self.namespace["_handle_legacy_action_error"])
        self.app.add_url_rule("/plugins", view_func=self.namespace["set_user_plugins"], methods=["POST"])

    def post(self, payload):
        with self.app.test_request_context("/plugins", method="POST", json=payload):
            return self.app.full_dispatch_request()

    def legacy_retired_view(self):
        original = action_fixture("legacy", "legacy-original-id")
        original["additionalFields"] = {"transport": "stdio", "command": "never-run"}
        snapshot = legacy.legacy_action_snapshots("current-user", [original])[0]
        view = legacy.legacy_action_management_view(snapshot)
        self.legacy_views = [view]
        return view

    def test_legacy_conversion_conflicts_are_preflighted_before_other_writes(self):
        for conflict in (legacy.LegacyActionConflictError, legacy.LegacyActionSecretConflictError):
            with self.subTest(conflict=conflict):
                view = self.legacy_retired_view()
                self.preflight_reconfiguration.side_effect = conflict()
                replacement = action_fixture("converted", view["id"])
                response = self.post([action_fixture("ordinary_edit"), replacement])
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.get_json()["error_type"], conflict.code)
                self.assertEqual(self.saved, [])
                self.assertEqual(self.deleted, [])
                self.assertEqual(self.reconfigured, [])

    def test_missing_legacy_graph_id_is_rejected_before_batch_mutations(self):
        point_read = Mock(side_effect=cosmos_exceptions.CosmosResourceNotFoundError(status_code=404))
        self.namespace["cosmos_personal_actions_container"] = types.SimpleNamespace(read_item=point_read)
        self.namespace["azure_cosmos"] = types.SimpleNamespace(exceptions=cosmos_exceptions)
        submitted = {
            **action_fixture("legacy_graph", "missing-legacy-id"),
            "type": "msgraph", "metadata": {"type": "msgraph"},
        }
        response = self.post([submitted])
        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error"], schema_validation.LEGACY_ACTION_CREATION_MESSAGE)
        point_read.assert_called_once_with(item="missing-legacy-id", partition_key="current-user")
        self.assertEqual(self.saved, [])
        self.assertEqual(self.deleted, [])
        self.assertEqual(self.validated, [])

    def test_non_missing_storage_errors_are_not_treated_as_absent_legacy_actions(self):
        submitted = {**action_fixture("legacy_graph", "legacy-id"), "type": "msgraph"}
        self.namespace["azure_cosmos"] = types.SimpleNamespace(exceptions=cosmos_exceptions)
        for status in (403, 429, 500):
            with self.subTest(status=status):
                failure = cosmos_exceptions.CosmosHttpResponseError(status_code=status)
                point_read = Mock(side_effect=failure)
                self.namespace["cosmos_personal_actions_container"] = types.SimpleNamespace(read_item=point_read)
                with self.assertRaises(cosmos_exceptions.CosmosHttpResponseError) as caught:
                    self.post([submitted])
                self.assertIs(caught.exception, failure)
                point_read.assert_called_once_with(item="legacy-id", partition_key="current-user")
        self.assertEqual(self.saved, [])
        self.assertEqual(self.deleted, [])

    def test_valid_legacy_conversion_uses_its_locator_after_preflight(self):
        view = self.legacy_retired_view()
        replacement = action_fixture("converted", view["id"])
        response = self.post([action_fixture(), replacement])
        self.assertEqual(response.status_code, 200)
        self.preflight_reconfiguration.assert_called_once()
        self.assertEqual(self.preflight_reconfiguration.call_args.args[:2], ("current-user", view["id"]))
        self.assertEqual(len(self.reconfigured), 1)
        self.assertEqual(self.reconfigured[0][:2], ("current-user", view["id"]))
        self.assertEqual([item["id"] for item in self.saved], ["existing-id"])
        self.assertEqual(self.deleted, [])

    def test_bulk_save_preserves_existing_id_on_rename(self):
        for plugin_type in ("mcp", "sql_schema", "sql_query"):
            with self.subTest(plugin_type=plugin_type):
                self.saved.clear()
                self.deleted.clear()
                self.validated.clear()
                renamed = action_fixture("renamed_plugin")
                renamed.update(type=plugin_type, created_by="stale-user", modified_at="old", user_id="stale-user")
                if plugin_type != "mcp":
                    renamed["auth"] = {"type": "identity", "identity": "fixture-identity"}
                    renamed["endpoint"] = f"sql://{plugin_type}"
                response = self.post([renamed])
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"success": True})
                self.assertEqual(len(self.saved), 1)
                self.assertEqual(self.saved[0]["id"], "existing-id")
                self.assertEqual(self.saved[0]["name"], "renamed_plugin")
                self.assertEqual(self.validated[0]["id"], "existing-id")
                self.assertEqual(self.deleted, [])
                for field in ("created_by", "modified_at", "user_id"):
                    self.assertNotIn(field, self.saved[0])
                    self.assertNotIn(field, self.validated[0])

    def test_metadata_type_is_resolved_before_retirement_and_validation(self):
        invalid = action_fixture("new_stdio", "new-id")
        invalid.pop("type")
        invalid["metadata"]["type"] = "McpPlugin"
        invalid["additionalFields"] = {"transport": "STDIO", "command": "never-run"}
        response = self.post([action_fixture("valid_change"), invalid])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error_type"], "mcp_stdio_removed")
        self.assertEqual(self.saved, [])
        self.assertEqual(self.deleted, [])

    def test_unknown_transport_does_not_default_to_http(self):
        invalid = action_fixture()
        invalid["additionalFields"]["transport"] = "not-a-transport"
        response = self.post([invalid])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.saved, [])
        self.assertEqual(self.deleted, [])

    def test_non_list_request_cannot_delete_actions(self):
        response = self.post({"unexpected": "object"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.saved, [])
        self.assertEqual(self.deleted, [])

    def test_governance_denial_is_checked_for_entire_batch_before_saving(self):
        self.type_access.side_effect = [None, PermissionError("Denied fixture")]
        response = self.post([action_fixture(), action_fixture("denied", "denied-id")])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.saved, [])
        self.assertEqual(self.deleted, [])

    def test_unchanged_retired_action_does_not_block_a_remote_edit(self):
        retired = action_fixture("retired", "retired-id")
        retired["additionalFields"] = {"transport": "stdio", "command": "never-run", "env": {"PRIVATE": "not-in-view"}}
        self.current.append(retired)
        original = deepcopy(retired)
        view = legacy.retired_action_management_view(retired, "personal", "current-user")
        response = self.post([view, action_fixture("updated_remote")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual([action["name"] for action in self.saved], ["updated_remote"])
        self.assertEqual(self.deleted, [])
        self.assertEqual(retired, original)

    def test_omitting_a_retired_action_does_not_delete_it(self):
        retired = action_fixture("retired", "retired-id")
        retired["additionalFields"]["transport"] = "stdio"
        self.current.append(retired)
        response = self.post([action_fixture("updated_remote")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.deleted, [])

    def test_retired_process_fields_cannot_be_changed_through_pass_through(self):
        retired = action_fixture("retired", "retired-id")
        retired["additionalFields"] = {"transport": "stdio", "command": "old-inert-command"}
        self.current.append(retired)
        view = legacy.retired_action_management_view(retired, "personal", "current-user")
        view["additionalFields"]["command"] = "changed-inert-command"
        response = self.post([action_fixture("valid_change"), view])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.saved, [])
        self.assertEqual(self.deleted, [])

    def test_unchanged_legacy_projection_is_not_saved_as_an_executable_action(self):
        retired = action_fixture("legacy_stdio", "old-id")
        retired["additionalFields"]["transport"] = "stdio"
        snapshots = legacy.legacy_action_snapshots("current-user", [retired])
        view = legacy.legacy_action_management_view(snapshots[0])
        self.legacy_views.append(view)
        response = self.post([view, action_fixture("updated_remote")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(self.reconfigured, [])
        self.assertEqual(self.deleted, [])

    def test_duplicate_identifiers_are_rejected_before_writes(self):
        response = self.post([action_fixture("one"), action_fixture("two")])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.saved, [])
        self.assertEqual(self.deleted, [])


if __name__ == "__main__":
    unittest.main()
