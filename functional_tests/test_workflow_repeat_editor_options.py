# test_workflow_repeat_editor_options.py
"""
Functional tests for Repeat administration and non-secret editor capabilities.
Version: 0.261.120
Implemented in: 0.261.120

Exercises real registry normalization, Classic POST validation, editor projection,
and authorized scope adapters with fictional stores and no application clients.
The settings-writer regression is shared with test_workflow_loop_limits.py.
"""

import ast
import copy
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Configure local paths before importing the production leaf modules and shared fixture.
from functions_workflow_editor import build_workflow_editor_options, get_workflow_editor_options
from functions_workflow_limits import (
    WORKFLOW_REPEAT_ITERATIONS_DEFAULT,
    WORKFLOW_REPEAT_LIMIT_SETTING,
    WorkflowLoopLimitError,
    get_workflow_max_repeat_iterations,
    validate_workflow_max_repeat_iterations,
)
from test_support.app_stubs import import_app_module
from test_workflow_loop_limits import _classic_limit_validator


def _options(**updates):
    arguments = {
        "scope_type": "personal", "scope_id": "fictional-owner", "can_manage": True,
        "max_tasks": 50, "agents": [], "endpoints": [],
    }
    return build_workflow_editor_options(**{**arguments, **updates})


class WorkflowRepeatEditorOptionsTests(unittest.TestCase):
    def test_independent_administrator_defaults_match_storage_and_registry(self):
        fields = import_app_module("admin_settings_fields")
        repeat = fields.get_field_definition(WORKFLOW_REPEAT_LIMIT_SETTING)
        loop = fields.get_field_definition("workflow_max_loop_items")
        self.assertEqual(repeat["label"], "Workflow Repeat Iteration Limit")
        self.assertEqual((repeat["default"], repeat["min"], repeat["max"], repeat["step"]), (25, 1, 1000, 1))
        self.assertNotIn("depends_on", repeat)
        self.assertEqual((loop["default"], loop["min"], loop["max"]), (500, 1, 5000))

        tree = ast.parse((APP_ROOT / "functions_settings.py").read_text(encoding="utf-8"))
        get_settings = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "get_settings")
        defaults = next(
            node.value for node in get_settings.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "default_settings" for target in node.targets)
        )
        value = next(
            value for key, value in zip(defaults.keys, defaults.values)
            if isinstance(key, ast.Constant) and key.value == WORKFLOW_REPEAT_LIMIT_SETTING
        )
        self.assertEqual(
            eval(
                compile(ast.Expression(body=value), "repeat_default", "eval"),
                {"WORKFLOW_REPEAT_ITERATIONS_DEFAULT": WORKFLOW_REPEAT_ITERATIONS_DEFAULT},
            ),
            25,
        )

    def test_registry_accepts_only_supported_whole_numbers_without_clamping(self):
        fields = import_app_module("admin_settings_fields")
        current = {"workflow_max_loop_items": 1800, WORKFLOW_REPEAT_LIMIT_SETTING: 200}
        for value in (1, 25, 1000, "1", " 700 ", "1000"):
            with self.subTest(value=value):
                normalized, errors, warnings = fields.normalize_admin_settings_updates(
                    {WORKFLOW_REPEAT_LIMIT_SETTING: value}, current,
                )
                self.assertFalse(errors)
                self.assertFalse(warnings)
                self.assertEqual(normalized[WORKFLOW_REPEAT_LIMIT_SETTING], int(value))
                self.assertNotIn("workflow_max_loop_items", normalized)
        for value in (None, "", " ", "1.5", "1e3", "invalid-secret", -1, 0, 1001, 25.0, True, False, [], {}):
            with self.subTest(value=value):
                normalized, errors, _warnings = fields.normalize_admin_settings_updates(
                    {WORKFLOW_REPEAT_LIMIT_SETTING: value}, current,
                )
                self.assertNotIn(WORKFLOW_REPEAT_LIMIT_SETTING, normalized)
                self.assertIn("1 to 1,000", errors[WORKFLOW_REPEAT_LIMIT_SETTING])
                self.assertNotIn("invalid-secret", errors[WORKFLOW_REPEAT_LIMIT_SETTING])
        self.assertEqual(current, {"workflow_max_loop_items": 1800, WORKFLOW_REPEAT_LIMIT_SETTING: 200})

    def test_unrelated_admin_updates_do_not_insert_or_reset_repeat_policy(self):
        fields = import_app_module("admin_settings_fields")
        for current in ({}, {WORKFLOW_REPEAT_LIMIT_SETTING: 700, "workflow_max_loop_items": 1800}):
            with self.subTest(current=current):
                before = copy.deepcopy(current)
                normalized, errors, _warnings = fields.normalize_admin_settings_updates(
                    {"allow_user_workflows": True}, current,
                )
                self.assertFalse(errors)
                self.assertNotIn(WORKFLOW_REPEAT_LIMIT_SETTING, normalized)
                self.assertEqual(current, before)

    def test_classic_post_preserves_absent_policy_and_reports_safe_errors(self):
        validate, flashes = _classic_limit_validator(
            WORKFLOW_REPEAT_LIMIT_SETTING,
            validate_workflow_max_repeat_iterations,
            get_workflow_max_repeat_iterations,
        )
        current = {WORKFLOW_REPEAT_LIMIT_SETTING: 700, "workflow_max_loop_items": 1800}
        self.assertEqual(validate({}, {}), 25)
        self.assertEqual(validate({}, current), 700)
        for value in ("1", "25", "1000"):
            self.assertEqual(validate({WORKFLOW_REPEAT_LIMIT_SETTING: value}, current), int(value))
        for value in ("", "0", "1001", "25.0", "invalid-secret"):
            response = validate({WORKFLOW_REPEAT_LIMIT_SETTING: value}, current)
            self.assertEqual(response, ("redirect", "frontend_admin_settings.admin_settings"))
            message, category = flashes[-1]
            self.assertEqual(category, "danger")
            self.assertIn("1 to 1,000", message)
            self.assertNotIn("invalid-secret", message)
        self.assertEqual(current, {WORKFLOW_REPEAT_LIMIT_SETTING: 700, "workflow_max_loop_items": 1800})

        tree = ast.parse((APP_ROOT / "route_frontend_admin_settings.py").read_text(encoding="utf-8"))
        persisted = [
            value
            for node in ast.walk(tree) if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and key.value == WORKFLOW_REPEAT_LIMIT_SETTING
        ]
        self.assertEqual(len(persisted), 1)
        self.assertIsInstance(persisted[0], ast.Name)
        self.assertEqual(persisted[0].id, WORKFLOW_REPEAT_LIMIT_SETTING)

    def test_editor_advertises_repeat_without_changing_existing_capabilities(self):
        options = _options(max_loop_items=1800, max_repeat_iterations=700)
        self.assertEqual(options["supported_node_kinds"], ["task", "if", "route", "for_each", "collect", "repeat_until"])
        self.assertEqual(options["supported_binding_sources"], ["node_output", "loop_item", "repeat_state"])
        self.assertEqual(options["flow_limits"]["max_repeat_iterations"], 700)
        self.assertEqual(options["flow_limits"]["hard_repeat_iterations"], 1000)
        self.assertEqual(options["flow_limits"]["max_loop_items"], 1800)
        self.assertEqual(options["supported_definition_versions"], [1, 2, 3])
        self.assertEqual(options["supported_iterable_kinds"], ["input", "documents", "workspace_query"])
        self.assertEqual(options["publication_source_capabilities"][-1], {
            "source_kind": "saved_output", "output_kinds": ["records"], "artifact_formats": ["json"],
        })
        for scope in ("personal", "group"):
            with self.subTest(scope=scope):
                defaults = _options(scope_type=scope, can_manage=False)
                self.assertEqual(defaults["flow_limits"]["max_repeat_iterations"], 25)
                self.assertEqual(defaults["flow_limits"]["max_loop_items"], 500)
                self.assertFalse(defaults["can_manage"])

    def test_invalid_explicit_editor_policy_fails_instead_of_becoming_default(self):
        for value in (None, "", 0, 1001, True, 25.0, "invalid-secret"):
            with self.subTest(value=value), self.assertRaises(WorkflowLoopLimitError) as raised:
                _options(max_repeat_iterations=value)
            self.assertEqual(raised.exception.code, "workflow_repeat_limit_invalid")
            self.assertNotIn("invalid-secret", raised.exception.public_message)
        self.assertEqual(_options(max_repeat_iterations=1)["flow_limits"]["max_repeat_iterations"], 1)
        self.assertEqual(_options(max_repeat_iterations=1000)["flow_limits"]["max_repeat_iterations"], 1000)

    def test_hosted_nonloop_choices_and_nonsecret_projection_are_unchanged(self):
        options = _options(agents=[
            {"id": "local", "name": "Local", "agent_type": "local", "loop_eligible": False},
            {"id": "hosted", "name": "Hosted", "agent_type": "foundry", "loop_eligible": True},
            {"id": "unknown", "name": "Unknown", "loop_eligible": True, "secret": "PRIVATE"},
        ])
        self.assertEqual([agent["id"] for agent in options["agents"]], ["local", "hosted", "unknown"])
        self.assertEqual([agent["loop_eligible"] for agent in options["agents"]], [True, False, False])
        self.assertNotIn("PRIVATE", json.dumps(options))

    def test_authorized_scope_adapter_reads_current_independent_limits(self):
        group = ModuleType("functions_group")
        group.assert_group_role = Mock(return_value="User")
        group_workflows = ModuleType("functions_group_workflows")
        group_workflows.GROUP_WORKFLOW_MEMBER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
        group_workflows._build_model_endpoint_candidates = Mock(return_value=[])
        group_workflows.get_group_workflow_agent_options = Mock(return_value=[])
        personal_workflows = ModuleType("functions_personal_workflows")
        personal_workflows._build_default_model_summary = Mock(return_value={"valid": True})
        personal_workflows._build_model_endpoint_candidates = Mock(return_value=[])
        personal_workflows._build_selectable_agents = Mock(return_value=[])
        personal_workflows.get_workflow_max_tasks = Mock(return_value=50)
        settings_module = ModuleType("functions_settings")
        settings_module.get_group_workflow_management_roles = Mock(return_value=["Owner", "Admin"])
        modules = {
            module.__name__: module
            for module in (group, group_workflows, personal_workflows, settings_module)
        }
        settings = {
            WORKFLOW_REPEAT_LIMIT_SETTING: 750, "workflow_max_loop_items": 1700,
            "private_secret": "PRIVATE",
        }
        before = copy.deepcopy(settings)
        with patch.dict(sys.modules, modules):
            for group_id in ("", "fictional-group"):
                with self.subTest(group_id=group_id):
                    result = get_workflow_editor_options("fictional-owner", settings, group_id=group_id)
                    self.assertEqual(result["flow_limits"]["max_repeat_iterations"], 750)
                    self.assertEqual(result["flow_limits"]["max_loop_items"], 1700)
                    self.assertEqual(result["scope"]["id"], group_id or "fictional-owner")
                    self.assertEqual(result["can_manage"], not group_id)
                    self.assertNotIn("PRIVATE", json.dumps(result))
            group.assert_group_role.assert_called_once_with(
                "fictional-owner", "fictional-group",
                allowed_roles=group_workflows.GROUP_WORKFLOW_MEMBER_ROLES,
            )
            group.assert_group_role.side_effect = PermissionError("Not a current group member.")
            with self.assertRaises(PermissionError):
                get_workflow_editor_options("fictional-owner", settings, group_id="fictional-group")
        self.assertEqual(settings, before)


if __name__ == "__main__":
    unittest.main()
