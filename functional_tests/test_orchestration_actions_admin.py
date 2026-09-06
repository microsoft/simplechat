# test_orchestration_actions_admin.py
"""
Functional coverage for the orchestration action admin opt-in.
Version: 0.261.096
Implemented in: 0.261.096

Validate the declarative schema, template-form normalizer and generic V2 partial
updates without initializing the application or contacting Azure.
"""

import ast
import copy
import sys
import unittest
from pathlib import Path

from werkzeug.datastructures import MultiDict

# Shared test imports must follow the functional-test path setup.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
ACTION_FLAG = "enable_chat_orchestration_actions"
CAPABILITIES_KEY = "chat_orchestration_enabled_capabilities"
FIELDS = import_app_module("admin_settings_fields")
REGISTRY = import_app_module("functions_orchestration_registry")
INT_UTILS = import_app_module("admin_settings_int_utils")


def _form_normalizer():
    """Load the actual pure normalizer without importing the Azure-backed route module."""
    path = APP_ROOT / "route_frontend_admin_settings.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "normalize_chat_orchestration_settings"
    )
    namespace = {
        "safe_int_with_source": INT_UTILS.safe_int_with_source,
        "all_capability_ids": REGISTRY.all_capability_ids,
        "TERMINAL_CAPABILITY_ID": REGISTRY.TERMINAL_CAPABILITY_ID,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[function.name]


NORMALIZE_FORM = _form_normalizer()


class OrchestrationActionsAdminTests(unittest.TestCase):
    def test_opt_in_is_default_off_and_needs_both_prerequisites(self):
        field = FIELDS.get_field_definition(ACTION_FLAG)
        self.assertEqual(field["type"], "switch")
        self.assertIs(field["default"], False)
        self.assertEqual(field["label"], "Enable Action Access")
        for orchestration, semantic_kernel in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(orchestration=orchestration, semantic_kernel=semantic_kernel):
                self.assertEqual(
                    FIELDS.field_dependencies_are_satisfied(field, {
                        "enable_chat_orchestration": orchestration,
                        "enable_semantic_kernel": semantic_kernel,
                    }),
                    orchestration and semantic_kernel,
                )

    def test_schema_and_template_projection_include_the_action_capability(self):
        options = FIELDS.get_field_definition(CAPABILITIES_KEY)["options"]
        action_options = [item for item in options if item["value"] == "action_invoke"]
        self.assertEqual(action_options, [{"value": "action_invoke", "label": "Use an action"}])
        projection = REGISTRY.build_capability_client_projection(REGISTRY.CAPABILITY_REGISTRY)
        action = next(item for item in projection if item["id"] == "action_invoke")
        self.assertEqual(action["label"], action_options[0]["label"])
        self.assertEqual(action["phase"], "knowledge")

    def test_v2_switch_coercion_changes_only_the_submitted_setting(self):
        current = {ACTION_FLAG: True, CAPABILITIES_KEY: ["web_search"]}
        for value, expected in ((True, True), (False, False), ("on", True), ("false", False)):
            with self.subTest(value=value):
                normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates(
                    {ACTION_FLAG: value}, current
                )
                self.assertEqual(errors, {})
                self.assertEqual(normalized, {ACTION_FLAG: expected})

    def test_v2_absent_fields_and_hidden_opt_in_are_preserved(self):
        current = {
            ACTION_FLAG: True,
            "enable_chat_orchestration": False,
            "enable_semantic_kernel": False,
            CAPABILITIES_KEY: ["action_invoke"],
        }
        before = copy.deepcopy(current)
        normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates(
            {"chat_orchestration_max_steps": 4}, current
        )
        self.assertEqual(errors, {})
        self.assertEqual(normalized, {"chat_orchestration_max_steps": 4})
        self.assertEqual(current, before)
        self.assertIs({**current, **normalized}[ACTION_FLAG], True)

    def test_v2_capability_selection_does_not_opt_in_or_clear_the_switch(self):
        for enabled in (False, True):
            for selection in ([], ["action_invoke"]):
                with self.subTest(enabled=enabled, selection=selection):
                    current = {ACTION_FLAG: enabled}
                    normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates(
                        {CAPABILITIES_KEY: selection}, current
                    )
                    self.assertEqual(errors, {})
                    self.assertEqual(normalized, {CAPABILITIES_KEY: selection})
                    self.assertIs({**current, **normalized}[ACTION_FLAG], enabled)

        normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates({
            CAPABILITIES_KEY: ["action_invoke", "web_search", "action_invoke"]
        })
        self.assertEqual(errors, {})
        self.assertEqual(normalized[CAPABILITIES_KEY], ["web_search", "action_invoke"])
        _normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates({
            CAPABILITIES_KEY: ["unregistered_action"]
        })
        self.assertIn(CAPABILITIES_KEY, errors)

    def test_template_form_round_trips_the_opt_in_and_terminal_step(self):
        form = MultiDict([
            ("enable_chat_orchestration", "on"),
            (ACTION_FLAG, "on"),
            (CAPABILITIES_KEY, "action_invoke"),
        ])
        enabled = NORMALIZE_FORM(form)
        self.assertIs(enabled[ACTION_FLAG], True)
        self.assertEqual(enabled[CAPABILITIES_KEY], ["action_invoke", "respond"])

        form.pop(ACTION_FLAG)
        disabled = NORMALIZE_FORM(form, {ACTION_FLAG: True})
        self.assertIs(disabled[ACTION_FLAG], False)
        self.assertEqual(disabled[CAPABILITIES_KEY], ["action_invoke", "respond"])

    def test_template_empty_and_full_capability_lists_still_require_opt_in(self):
        for selection in ([], REGISTRY.all_capability_ids()):
            with self.subTest(selection=selection):
                form = MultiDict((CAPABILITIES_KEY, value) for value in selection)
                normalized = NORMALIZE_FORM(form)
                self.assertEqual(normalized[CAPABILITIES_KEY], [])
                self.assertIs(normalized[ACTION_FLAG], False)
                form[ACTION_FLAG] = "on"
                self.assertIs(NORMALIZE_FORM(form)[ACTION_FLAG], True)


if __name__ == "__main__":
    unittest.main()
