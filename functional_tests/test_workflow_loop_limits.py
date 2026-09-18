# test_workflow_loop_limits.py
"""
Functional tests for strict workflow loop policy and non-secret editor options.
Version: 0.261.122
Implemented in: 0.261.117

Exercises production settings normalization, the Classic POST validation block,
the settings writer, and the editor projection without starting application clients.
"""

import ast
import copy
from contextlib import contextmanager, nullcontext
import logging
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Configure local paths before importing the production leaf modules.
from app_settings_store import AppSettingsStore, COSMOS_METADATA_FIELDS, SETTINGS_REVISION_FIELD
from functions_workflow_editor import build_workflow_editor_options
from functions_workflow_limits import (
    WorkflowLoopInputError,
    WorkflowLoopLimitError,
    assert_workflow_loop_item_count,
    effective_workflow_loop_limit,
    get_workflow_loop_item_limit,
    get_workflow_max_loop_items,
    validate_workflow_max_loop_items,
)
from test_support.app_stubs import import_app_module
from test_app_settings_store_consistency import FakeCosmos


def _production_function(filename, name, namespace):
    tree = ast.parse((APP_ROOT / filename).read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


class WorkflowLoopPolicyTests(unittest.TestCase):
    def test_default_and_supported_boundaries(self):
        self.assertEqual(get_workflow_max_loop_items({}), 500)
        for value in (1, 500, 1001, 5000, "1", "500", " 1475 ", "5000"):
            with self.subTest(value=value):
                self.assertEqual(validate_workflow_max_loop_items(value), int(value))

    def test_invalid_explicit_values_are_rejected_not_clamped(self):
        for value in (None, "", "abc", "1.5", "5001", "1e3", -1, 0, 5001, 1.5, 1.0, True, False, [], {}):
            with self.subTest(value=value), self.assertRaises(WorkflowLoopLimitError) as raised:
                validate_workflow_max_loop_items(value)
            self.assertEqual(raised.exception.code, "workflow_loop_limit_invalid")
            self.assertEqual(str(raised.exception), raised.exception.public_message)
            self.assertIn("1 to 5,000", raised.exception.public_message)

    def test_admitted_policy_wins_over_later_admin_changes(self):
        admitted = {"max_items": 1200}
        settings = {"workflow_max_loop_items": 20}
        self.assertEqual(effective_workflow_loop_limit(1000, policy=admitted, settings=settings), 1000)
        self.assertEqual(effective_workflow_loop_limit(1500, policy=admitted, settings=settings), 1200)
        self.assertEqual(effective_workflow_loop_limit(1000, settings=settings), 20)
        self.assertEqual(admitted, {"max_items": 1200})
        self.assertNotIn("max_total_tokens", admitted)

    def test_admission_accessor_matches_parent_loop_policy_shape(self):
        self.assertEqual(get_workflow_loop_item_limit({}), 500)
        settings = {"workflow_max_loop_items": 1400}
        admitted = {"version": 1, "max_items": get_workflow_loop_item_limit(settings)}
        settings["workflow_max_loop_items"] = 10
        self.assertEqual(effective_workflow_loop_limit(2000, policy=admitted, settings=settings), 1400)
        with self.assertRaises(WorkflowLoopLimitError):
            get_workflow_loop_item_limit({"workflow_max_loop_items": 5001})

    def test_exact_and_lower_bound_errors_are_actionable(self):
        self.assertEqual(assert_workflow_loop_item_count(500, limit=500), 500)
        self.assertEqual(assert_workflow_loop_item_count(1201, limit=1500), 1201)
        for exact in (True, False):
            with self.assertRaises(WorkflowLoopLimitError) as raised:
                assert_workflow_loop_item_count(501, limit=500, count_exact=exact)
            error = raised.exception
            self.assertIsInstance(error, WorkflowLoopInputError)
            self.assertEqual((error.count, error.count_exact, error.limit), (501, exact, 500))
            self.assertEqual(error.code, "workflow_loop_item_limit_exceeded")
            self.assertEqual("at least" in error.public_message, not exact)
            self.assertIn("Narrow the query", error.public_message)

    def test_v2_registry_rejects_invalid_and_preserves_absent_field(self):
        fields = import_app_module("admin_settings_fields")
        field = fields.get_field_definition("workflow_max_loop_items")
        self.assertEqual((field["default"], field["min"], field["max"], field["step"]), (500, 1, 5000, 1))
        self.assertNotIn("depends_on", field)
        current = {"workflow_max_loop_items": 1800}
        normalized, errors, _warnings = fields.normalize_admin_settings_updates(
            {"allow_user_workflows": True}, current,
        )
        self.assertFalse(errors)
        self.assertNotIn("workflow_max_loop_items", normalized)
        self.assertEqual(current["workflow_max_loop_items"], 1800)
        for value in (0, 5001, True, "secret-endpoint", 10.25, ""):
            normalized, errors, _warnings = fields.normalize_admin_settings_updates(
                {"workflow_max_loop_items": value}, current,
            )
            self.assertIn("workflow_max_loop_items", errors)
            self.assertNotIn("workflow_max_loop_items", normalized)
            self.assertNotIn("secret-endpoint", errors["workflow_max_loop_items"])
        normalized, errors, _warnings = fields.normalize_admin_settings_updates(
            {"workflow_max_loop_items": "1700"}, current,
        )
        self.assertFalse(errors)
        self.assertEqual(normalized["workflow_max_loop_items"], 1700)

    def test_classic_post_validation_and_absent_preservation(self):
        source = ast.parse((APP_ROOT / "route_frontend_admin_settings.py").read_text(encoding="utf-8"))
        validation = next(
            node for node in ast.walk(source)
            if isinstance(node, ast.Try)
            and any(
                isinstance(child, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "workflow_max_loop_items"
                        for target in child.targets)
                for child in node.body
            )
        )
        wrapper = ast.parse("def validate_form(form_data, settings):\n    pass\n").body[0]
        wrapper.body = [validation, ast.Return(value=ast.Name(id="workflow_max_loop_items", ctx=ast.Load()))]
        flashes = []
        namespace = {
            "WorkflowLoopLimitError": WorkflowLoopLimitError,
            "validate_workflow_max_loop_items": validate_workflow_max_loop_items,
            "get_workflow_max_loop_items": get_workflow_max_loop_items,
            "flash": lambda message, category: flashes.append((message, category)),
            "redirect": lambda path: ("redirect", path),
            "url_for": lambda endpoint: endpoint,
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])), "classic_post", "exec"), namespace)
        validate = namespace["validate_form"]
        self.assertEqual(validate({}, {"workflow_max_loop_items": 2100}), 2100)
        self.assertEqual(validate({}, {}), 500)
        self.assertEqual(validate({"workflow_max_loop_items": "2600"}, {}), 2600)
        self.assertEqual(validate({"workflow_max_loop_items": "invalid-secret"}, {})[0], "redirect")
        self.assertEqual(flashes[0][1], "danger")
        self.assertNotIn("invalid-secret", flashes[0][0])

    def test_settings_writer_validates_before_storage_and_preserves_absent_value(self):
        class ClosedError(Exception):
            pass

        storage = FakeCosmos()
        storage.document["workflow_max_loop_items"] = 1800
        namespace = {
            "copy": copy, "logging": logging, "contextmanager": contextmanager,
            "COSMOS_METADATA_FIELDS": COSMOS_METADATA_FIELDS,
            "SETTINGS_REVISION_FIELD": SETTINGS_REVISION_FIELD,
            "_get_app_settings_store": lambda: AppSettingsStore(storage),
            "validate_workflow_max_loop_items": validate_workflow_max_loop_items,
            "cosmos_settings_container": storage,
            "validate_content_screening_settings": lambda *_args: None,
            "coerce_multi_model_endpoint_enablement": lambda _old, requested: requested,
            "is_tabular_processing_enabled": lambda _settings: False,
            "MatchConditions": SimpleNamespace(IfNotModified="etag"),
            "CosmosAccessConditionFailedError": ClosedError,
            "ScreeningConflictError": ClosedError,
            "ScreeningError": ClosedError,
            "AIConnectionError": ClosedError,
            "EMBEDDING_SELECTION_KEY": "embedding_model_selection",
            "log_event": lambda *_args, **_kwargs: None,
        }
        for name in (
            "normalize_group_workflow_assignment_settings",
            "normalize_agents_page_promoted_popular_settings",
            "normalize_document_access_index_required_settings",
            "normalize_inbound_mcp_settings",
            "normalize_public_workspace_display_settings",
            "normalize_key_vault_reminder_settings",
            "normalize_model_endpoint_identity_header_settings",
        ):
            namespace[name] = lambda _settings: None
        writer = _production_function("functions_settings.py", "update_settings", namespace)
        with self.assertRaises(WorkflowLoopLimitError):
            writer({"workflow_max_loop_items": False})
        self.assertFalse(storage.writes)
        embedding = ModuleType("functions_embedding_compatibility")
        embedding.embedding_settings_write_guard = lambda *_args, **_kwargs: nullcontext()
        with patch.dict(sys.modules, {"functions_embedding_compatibility": embedding}):
            self.assertTrue(writer({"allow_user_workflows": True}))
            self.assertEqual(storage.document["workflow_max_loop_items"], 1800)
            self.assertTrue(writer({"workflow_max_loop_items": "2500"}))
            self.assertEqual(storage.document["workflow_max_loop_items"], 2500)

    def test_editor_capabilities_and_eligibility_are_safe_and_backwards_compatible(self):
        options = build_workflow_editor_options(
            scope_type="personal", scope_id="owner", can_manage=True, max_tasks=50,
            max_loop_items=1450, endpoints=[],
            agents=[
                {"id": "local", "name": "Local", "agent_type": "local", "loop_eligible": False},
                {"id": "hosted", "name": "Hosted", "agent_type": "foundry", "loop_eligible": True},
                {"id": "unknown", "name": "Unknown", "loop_eligible": True, "secret": "PRIVATE"},
            ],
        )
        self.assertEqual(options["supported_node_kinds"], ["task", "if", "route", "for_each", "collect"])
        self.assertEqual(options["supported_iterable_kinds"], ["input", "documents", "workspace_query"])
        self.assertEqual(options["supported_query_modes"], ["all_matches", "best_n"])
        self.assertEqual(options["supported_binding_sources"], ["node_output", "loop_item"])
        self.assertEqual(options["supported_input_processing_modes"], ["full", "saved_record_report"])
        self.assertEqual(options["flow_limits"]["max_loop_items"], 1450)
        self.assertEqual([agent["loop_eligible"] for agent in options["agents"]], [True, False, False])
        self.assertEqual(len(options["agents"]), 3, "Non-loop hosted agents must remain selectable.")
        self.assertNotIn("PRIVATE", repr(options))
        default = build_workflow_editor_options(
            scope_type="group", scope_id="group", can_manage=False, max_tasks=50, agents=[], endpoints=[],
        )
        self.assertEqual(default["flow_limits"]["max_loop_items"], 500)

    def test_model_and_default_loop_eligibility_is_derived_from_supported_choices(self):
        options = build_workflow_editor_options(
            scope_type="personal", scope_id="owner", can_manage=True, max_tasks=50, agents=[],
            endpoints=[{
                "id": "endpoint", "provider": "aoai",
                "models": [
                    {"id": "chat", "modelName": "gpt-4.1", "loop_eligible": False},
                    {"id": "disabled", "modelName": "gpt-4.1", "enabled": False, "loop_eligible": True},
                    {"id": "image", "modelName": "gpt-image-1", "enabled_capabilities": ["image_generation"], "loop_eligible": True},
                ],
            }],
            default_model={"label": "Configured default", "valid": True, "loop_eligible": False},
        )
        self.assertEqual([model["model_id"] for model in options["models"]], ["chat"])
        self.assertTrue(options["models"][0]["loop_eligible"])
        self.assertTrue(options["default_model"]["loop_eligible"])
        unavailable = build_workflow_editor_options(
            scope_type="personal", scope_id="owner", can_manage=True, max_tasks=50, agents=[], endpoints=[],
            default_model={"valid": False, "loop_eligible": True},
        )
        self.assertFalse(unavailable["default_model"]["valid"])
        self.assertFalse(unavailable["default_model"]["loop_eligible"])


if __name__ == "__main__":
    unittest.main()
