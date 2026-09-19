# test_mcp_user_settings_ingestion.py
#!/usr/bin/env python3
"""
Functional tests for the legacy action user-settings request boundary.
Version: 0.261.029
Implemented in: 0.261.029

Executes the actual route and sanitizer with Flask request dispatch and isolated
storage. Azure bootstrap and unrelated preference helpers are not initialized;
fresh-module import and route policy behavior have separate regression suites.
"""

import ast
from contextlib import contextmanager
from copy import deepcopy
import logging
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify, request


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

import functions_action_manifest as manifests
import functions_legacy_action_management as legacy
from test_mcp_legacy_stdio_management import OWNER, action_services, remote, retired, source_plugins


def load_definitions(filename, names, namespace):
    source_path = APP_DIR / filename
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    definitions = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    if len(definitions) != len(names):
        raise RuntimeError(f"Required definitions were not found in {filename}.")
    for definition in definitions:
        definition.decorator_list = []
    module = ast.Module(body=definitions, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(source_path), "exec"), namespace)


def retired_fixture():
    return {
        "name": "retained",
        "type": "",
        "metadata": {"type": "McpPlugin"},
        "endpoint": "stdio://private-process",
        "auth": {"type": "key", "key": "private-credential"},
        "additionalFields": {
            "transport": " STDIO ",
            "command": "private-command",
            "args": ["private-argument"],
            "env": {"PRIVATE": "private-environment"},
        },
    }


class McpUserSettingsIngestionTests(unittest.TestCase):
    def setUp(self):
        self.document = {
            "id": "current-user",
            "settings": {
                "plugins": [retired_fixture(), retired_fixture()],
                "darkModeEnabled": True,
                "private_api_key": "private-settings-secret",
            },
        }
        self.update_settings = Mock(return_value=True)
        self.update_group = Mock()
        self.update_public_workspace = Mock()
        self.logger = Mock()
        self.namespace = {
            **vars(manifests),
            **vars(legacy),
            "logging": logging,
            "jsonify": jsonify,
            "request": request,
            "log_event": self.logger,
            "get_current_user_id": lambda: "current-user",
            "get_user_settings": lambda user_id: deepcopy(self.document),
            "update_user_settings": self.update_settings,
            "update_active_group_for_user": self.update_group,
            "update_active_public_workspace_for_user": self.update_public_workspace,
            "LATEST_FEATURES_HIDDEN_VERSION_SETTING": "latestFeaturesHiddenVersion",
            "AI_NOTICE_USER_SETTINGS_KEY": "aiNoticeDismissal",
            "TABULAR_GENERATION_BACKEND_SETTING_KEYS": frozenset(),
            "get_public_workspace_label_context": lambda settings: {"singular": "Workspace"},
        }
        load_definitions("functions_settings.py", {"sanitize_settings_for_user"}, self.namespace)
        load_definitions("route_backend_users.py", {"user_settings"}, self.namespace)
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.add_url_rule(
            "/settings", view_func=self.namespace["user_settings"], methods=["GET", "POST"]
        )

    def dispatch(self, method="GET", payload=None):
        with self.app.test_request_context("/settings", method=method, json=payload):
            return self.app.full_dispatch_request()

    def assert_no_writes(self):
        self.update_settings.assert_not_called()
        self.update_group.assert_not_called()
        self.update_public_workspace.assert_not_called()

    @contextmanager
    def stored_actions(self, plugins=None):
        with action_services(plugins) as state:
            state.settings["allow_user_plugins"] = True
            namespace = {
                **vars(state.manifest),
                **vars(state.management),
                "get_current_user_id": lambda: state.actor,
                "get_settings": lambda: deepcopy(state.settings),
                "get_user_settings": state.personal_service.get_user_settings,
            }
            previous_callback = self.update_settings.side_effect
            self.update_settings.side_effect = state.personal_service.user_settings_service.update_user_settings
            try:
                with patch.dict(self.namespace, namespace):
                    yield state
            finally:
                self.update_settings.side_effect = previous_callback

    def assert_no_action_or_settings_writes(self, state):
        self.assert_no_writes()
        self.assertEqual(state.personal.writes + state.source.writes, [])
        self.assertEqual(state.secret_saves + state.secret_gets, [])
        self.assertEqual(state.identity_hydrations, [])

    def test_new_stdio_import_rejects_the_whole_request_before_active_scope_changes(self):
        with self.stored_actions() as state:
            incoming = retired("new-stdio")
            incoming["type"] = ""
            incoming["metadata"] = {"type": "McpPlugin"}
            incoming.update(is_global=True, scope="global", runtime_user_id="privileged-user")
            response = self.dispatch("POST", {"settings": {
                "plugins": [remote("valid-first"), incoming],
                "activeGroupOid": "requested-group",
                "activePublicWorkspaceOid": "requested-workspace",
                "darkModeEnabled": True,
            }})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["error_type"], "mcp_stdio_removed")
            self.assert_no_action_or_settings_writes(state)

    def test_invalid_import_shapes_and_unknown_transports_do_not_mutate_settings(self):
        invalid_transport = remote()
        invalid_transport["additionalFields"]["transport"] = "unknown"
        for incoming in ({}, [None], [invalid_transport]):
            with self.subTest(incoming=incoming), self.stored_actions() as state:
                response = self.dispatch("POST", {"settings": {
                    "plugins": incoming, "activeGroupOid": "requested-group",
                }})
                self.assertEqual(response.status_code, 400)
                self.assert_no_action_or_settings_writes(state)

    def test_valid_remote_import_is_canonical_personal_and_preserves_retired_sources(self):
        original = retired()
        with self.stored_actions([original]) as state:
            incoming = remote("new-remote")
            incoming.pop("type")
            incoming["metadata"]["type"] = "Model_Context_Protocol"
            incoming.update(scope="global", scope_id="forged", user_id="different-user", runtime_user_id="admin")
            incoming["additionalFields"]["command"] = "ignored-process-setting"
            response = self.dispatch("POST", {"settings": {"plugins": [incoming]}})
            self.assertEqual(response.status_code, 200)
            stored = source_plugins(state)
            self.assertEqual(stored[0], original)
            self.assertEqual(stored[1]["type"], "mcp")
            self.assertEqual(stored[1]["scope_id"], OWNER)
            self.assertEqual(stored[1]["user_id"], OWNER)
            self.assertFalse(stored[1]["is_global"])
            self.assertNotIn("runtime_user_id", stored[1])
            self.assertNotIn("command", stored[1]["additionalFields"])
            self.assertEqual(state.personal.writes, [])
            self.assertEqual(state.secret_saves + state.secret_gets, [])

    def test_disabled_personal_actions_block_imports_but_not_unchanged_retired_preferences(self):
        original = retired()
        with self.stored_actions([original]) as state:
            state.settings["allow_user_plugins"] = False
            response = self.dispatch("POST", {"settings": {
                "plugins": [remote("new-remote")], "activeGroupOid": "requested-group",
            }})
            self.assertEqual(response.status_code, 403)
            self.assert_no_action_or_settings_writes(state)

            state.denied_types.add("mcp")
            snapshot = state.management.legacy_action_snapshots(OWNER, [original])[0]
            view = state.management.legacy_action_management_view(snapshot)
            response = self.dispatch("POST", {"settings": {
                "plugins": [view], "darkModeEnabled": True,
            }})
            self.assertEqual(response.status_code, 200)
            self.update_settings.assert_called_once_with(OWNER, {"darkModeEnabled": True})
            stored = source_plugins(state)
            self.assertEqual(stored, [original])
            self.assertEqual(state.secret_saves + state.secret_gets, [])

    def test_omitted_retired_records_do_not_create_a_settings_write(self):
        original = retired()
        with self.stored_actions([original]) as state:
            state.denied_types.add("mcp")
            response = self.dispatch("POST", {"settings": {"plugins": []}})
            self.assertEqual(response.status_code, 200)
            self.assert_no_action_or_settings_writes(state)
            stored = source_plugins(state)
            self.assertEqual(stored, [original])

    def test_usage_or_destination_denials_precede_all_request_writes(self):
        for denial in ("type", "destination", "preconfiguration"):
            with self.subTest(denial=denial), self.stored_actions() as state:
                if denial == "type":
                    state.denied_types.add("mcp")
                else:
                    state.settings[f"deny_{denial}"] = True
                response = self.dispatch("POST", {"settings": {
                    "plugins": [remote()], "activeGroupOid": "requested-group",
                }})
                self.assertEqual(response.status_code, 403)
                self.assert_no_action_or_settings_writes(state)

    def test_stale_management_views_fail_before_preference_or_scope_updates(self):
        original = retired()
        with self.stored_actions([original]) as state:
            snapshot = state.management.legacy_action_snapshots(OWNER, [original])[0]
            view = state.management.legacy_action_management_view(snapshot)
            document = state.source.read_item(OWNER, OWNER)
            document["settings"]["plugins"][0]["description"] = "Changed after the view was loaded"
            state.source.seed(document)
            response = self.dispatch("POST", {"settings": {
                "plugins": [view], "darkModeEnabled": True, "activeGroupOid": "requested-group",
            }})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.get_json()["error_type"], "legacy_action_conflict")
            self.assert_no_action_or_settings_writes(state)

    def test_non_object_body_is_a_deliberate_client_error(self):
        response = self.dispatch("POST", [])
        self.assertEqual(response.status_code, 400)
        self.assert_no_writes()

    def test_get_returns_safe_owner_bound_views_without_modifying_sources(self):
        original = deepcopy(self.document)
        response = self.dispatch()
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        views = result["settings"]["plugins"]
        snapshots = legacy.legacy_action_snapshots("current-user", self.document["settings"]["plugins"])
        expected = [legacy.legacy_action_management_view(snapshot) for snapshot in snapshots]
        self.assertEqual(views, expected)
        self.assertNotEqual(views[0]["id"], views[1]["id"])
        self.assertEqual(views[0]["execution_status"]["code"], "mcp_stdio_removed")
        self.assertTrue(result["settings"]["darkModeEnabled"])
        for private_value in (
            "private-process", "private-credential", "private-command",
            "private-argument", "private-environment", "private-settings-secret",
        ):
            self.assertNotIn(private_value, response.get_data(as_text=True))
        self.assertEqual(self.document, original)
        self.assert_no_writes()

    def test_get_avoids_sanitizer_fields_in_legacy_action_round_trips(self):
        response = self.dispatch()
        result = response.get_json()
        self.assertIn("public_workspace_labels", result["settings"])
        for view in result["settings"]["plugins"]:
            self.assertNotIn("public_workspace_labels", view)
            self.assertNotIn("public_workspace_labels", view["metadata"])
            self.assertNotIn("public_workspace_labels", view["auth"])
        self.assert_no_writes()

    def test_invalid_legacy_source_is_not_exposed_or_reported_as_success(self):
        self.document["settings"]["plugins"] = {"command": "private-command"}
        response = self.dispatch()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"error": "Failed to retrieve user settings"})
        self.logger.assert_called_once()
        self.assert_no_writes()

    def test_null_legacy_collection_remains_an_empty_safe_list(self):
        self.document["settings"]["plugins"] = None
        response = self.dispatch()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["settings"]["plugins"], [])
        self.assert_no_writes()

    def test_non_action_preferences_keep_existing_update_behavior(self):
        response = self.dispatch("POST", {"settings": {"darkModeEnabled": False}})
        self.assertEqual(response.status_code, 200)
        self.update_settings.assert_called_once_with("current-user", {"darkModeEnabled": False})
        self.update_group.assert_not_called()
        self.update_public_workspace.assert_not_called()


if __name__ == "__main__":
    unittest.main()
