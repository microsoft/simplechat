# test_orchestration_harness_admission.py
"""
Functional coverage for the new-plan orchestration harness rollout control.
Version: 0.261.127
Implemented in: 0.261.127

Exercise default merging and saves through the real settings store with fake
Cosmos I/O, both admin normalizers, safe browser projection, and fail-closed
admission. Saved-plan execution and recovery are outside this admission API.
Refs microsoft/simplechat#1509.
"""

import copy
from contextlib import nullcontext
from itertools import product
from pathlib import Path
import socket
import subprocess
import sys
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import patch

from werkzeug.datastructures import MultiDict

# Existing test loaders isolate the Azure-backed settings/form owners.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_app_settings_store_consistency import (
    AppSettingsStore,
    FakeCosmos,
    load_get_settings,
    load_update_settings,
)
from test_orchestration_actions_admin import NORMALIZE_FORM
from test_support.app_stubs import import_app_module
from test_tabular_execution_settings_sanitization import load_sanitize_settings_for_user


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
MAIN_FLAG = "enable_chat_orchestration"
HARNESS_FLAG = "enable_chat_orchestration_harness"
FIELDS = import_app_module("admin_settings_fields")
ADMISSION = import_app_module("functions_orchestration_admission")

IMPORT_PROBE = r"""
import builtins
import importlib
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if (
        name in {"config", "functions_settings", "functions_appinsights"}
        or name.startswith("route_")
        or (name.startswith("functions_orchestration_")
            and name != "functions_orchestration_admission")
    ):
        raise AssertionError("Admission imported a runtime owner: " + name)
    return real_import(name, *args, **kwargs)

def no_network(*args, **kwargs):
    raise AssertionError("Admission attempted network access")

with patch.object(builtins, "__import__", guarded_import), patch.object(socket.socket, "connect", no_network):
    admission = importlib.import_module("functions_orchestration_admission")
    settings = {
        "enable_chat_orchestration": True,
        "enable_chat_orchestration_harness": True,
    }
    default = admission.get_new_plan_contract_version(settings)
    ready = admission.get_new_plan_contract_version(settings, admission_ready=True)
    settings["enable_chat_orchestration_harness"] = False
    rollback = admission.get_new_plan_contract_version(settings, admission_ready=True)
    if (default, ready, rollback) != (1, 2, 1):
        raise AssertionError("Incorrect admission or rollback")
"""


class OrchestrationHarnessAdmissionTests(unittest.TestCase):
    def setUp(self):
        def deny_network(*_args, **_kwargs):
            raise AssertionError("Admission/settings tests must not contact external services")

        network_patch = patch.object(socket.socket, "connect", deny_network)
        network_patch.start()
        self.addCleanup(network_patch.stop)
        compatibility_patch = patch.dict(sys.modules, {
            "functions_embedding_compatibility": SimpleNamespace(
                embedding_settings_write_guard=lambda *_args, **_kwargs: nullcontext(),
            ),
        })
        compatibility_patch.start()
        self.addCleanup(compatibility_patch.stop)
        self.cosmos = FakeCosmos()
        self.store = AppSettingsStore(self.cosmos)
        self.get_settings = load_get_settings(self.store)
        self.update_settings = load_update_settings(self.store)
        self.sanitize = load_sanitize_settings_for_user()

    def test_existing_deployments_merge_default_off_without_changing_legacy_opt_in(self):
        for main_enabled in (False, True):
            with self.subTest(main_enabled=main_enabled):
                self.cosmos.document[MAIN_FLAG] = main_enabled
                self.cosmos.document.pop(HARNESS_FLAG, None)
                loaded = self.get_settings()
                version = ADMISSION.get_new_plan_contract_version(loaded, admission_ready=True)
                self.assertIsNotNone(loaded)
                self.assertIs(loaded[MAIN_FLAG], main_enabled)
                self.assertIs(loaded[HARNESS_FLAG], False)
                self.assertIs(self.cosmos.document[HARNESS_FLAG], False)
                self.assertEqual(version, 1)

    def test_admin_schema_declares_a_default_off_preview_with_main_prerequisite(self):
        field = FIELDS.get_field_definition(HARNESS_FLAG)
        self.assertEqual(field["type"], "switch")
        self.assertIs(field["default"], False)
        self.assertEqual(field["label"], "Gather / Reason / Render harness (preview)")
        for main_enabled in (False, True):
            visible = FIELDS.field_dependencies_are_satisfied(field, {MAIN_FLAG: main_enabled})
            self.assertIs(visible, main_enabled)

    def test_v2_save_round_trips_canonical_booleans_and_form_shaped_strings(self):
        cases = (
            (True, True), (False, False), ("on", True), ("true", True),
            (" TRUE ", True), ("false", False), ("off", False), ("0", False),
            ("malformed", False), ("", False), (None, False),
        )
        for submitted, expected in cases:
            with self.subTest(submitted=submitted):
                current = self.get_settings()
                normalized, errors, _warnings = FIELDS.normalize_admin_settings_updates(
                    {HARNESS_FLAG: submitted}, current
                )
                self.assertEqual(errors, {})
                self.assertEqual(normalized, {HARNESS_FLAG: expected})
                saved = self.update_settings(normalized)
                loaded = self.get_settings(use_cosmos=True)
                self.assertIs(saved, True)
                self.assertIs(loaded[HARNESS_FLAG], expected)

    def test_template_save_accepts_only_checked_on_and_clears_unchecked(self):
        cases = (
            ("on", True), ("false", False), ("true", False), ("ON", False),
            ("malformed", False), ("", False), (None, False),
        )
        for submitted, expected in cases:
            with self.subTest(submitted=submitted):
                self.get_settings()
                enabled_saved = self.update_settings({HARNESS_FLAG: True})
                form = MultiDict([(MAIN_FLAG, "on")])
                if submitted is not None:
                    form[HARNESS_FLAG] = submitted
                normalized = NORMALIZE_FORM(form, {HARNESS_FLAG: True})
                saved = self.update_settings(normalized)
                loaded = self.get_settings()
                self.assertIs(enabled_saved, True)
                self.assertIs(saved, True)
                self.assertIs(normalized[HARNESS_FLAG], expected)
                self.assertIs(loaded[HARNESS_FLAG], expected)
                self.assertIs(loaded[MAIN_FLAG], True)

    def test_partial_updates_preserve_hidden_opt_in_and_existing_budgets(self):
        self.get_settings()
        saved = self.update_settings({
            MAIN_FLAG: False,
            HARNESS_FLAG: True,
            "chat_orchestration_enabled_capabilities": ["web_search"],
            "chat_orchestration_max_steps": 3,
            "chat_orchestration_total_timeout_seconds": 120,
            "chat_orchestration_planner_deployment": "pilot-planner",
        })
        current = self.get_settings()
        before = copy.deepcopy(current)
        updates, errors, _warnings = FIELDS.normalize_admin_settings_updates(
            {"chat_orchestration_max_replans": 1}, current
        )
        partial_saved = self.update_settings(updates)
        loaded = self.get_settings()
        self.assertIs(saved, True)
        self.assertEqual(errors, {})
        self.assertEqual(updates, {"chat_orchestration_max_replans": 1})
        self.assertEqual(current, before)
        self.assertIs(partial_saved, True)
        for key in (
            MAIN_FLAG, HARNESS_FLAG, "chat_orchestration_enabled_capabilities",
            "chat_orchestration_max_steps", "chat_orchestration_total_timeout_seconds",
            "chat_orchestration_planner_deployment",
        ):
            self.assertEqual(loaded[key], before[key])

        disabled, errors, _warnings = FIELDS.normalize_admin_settings_updates(
            {HARNESS_FLAG: False}, loaded
        )
        self.assertEqual(errors, {})
        self.assertEqual(disabled, {HARNESS_FLAG: False})

    def test_browser_projection_exposes_only_a_boolean_without_mutating_admin_settings(self):
        cases = (
            True, False, "false", "true", "on", 1, None, [],
            {"endpoint": "https://private.invalid", "api_key": "synthetic-secret"},
        )
        for value in cases:
            with self.subTest(value=value):
                raw = {
                    HARNESS_FLAG: value,
                    "app_title": "SimpleChat",
                    "api_key": "synthetic-secret",
                    "client_secret": "synthetic-secret",
                    "connection_string": "synthetic-connection",
                }
                before = copy.deepcopy(raw)
                sanitized = self.sanitize(raw)
                self.assertIs(sanitized[HARNESS_FLAG], value is True)
                self.assertEqual(sanitized["app_title"], "SimpleChat")
                self.assertNotIn("api_key", sanitized)
                self.assertNotIn("client_secret", sanitized)
                self.assertNotIn("connection_string", sanitized)
                self.assertEqual(raw, before)

    def test_admission_requires_both_settings_and_explicit_server_readiness(self):
        for main_enabled, harness_enabled, ready in product((False, True), repeat=3):
            with self.subTest(main=main_enabled, harness=harness_enabled, ready=ready):
                settings = {MAIN_FLAG: main_enabled, HARNESS_FLAG: harness_enabled}
                before = copy.deepcopy(settings)
                selected = ADMISSION.get_new_plan_contract_version(
                    MappingProxyType(settings), admission_ready=ready
                )
                expected = 2 if main_enabled and harness_enabled and ready else 1
                self.assertEqual(selected, expected)
                self.assertEqual(settings, before)
        selected_without_readiness = ADMISSION.get_new_plan_contract_version({
            MAIN_FLAG: True, HARNESS_FLAG: True,
        })
        self.assertEqual(selected_without_readiness, 1)

    def test_shipped_runtime_admits_only_explicit_preview_opt_in(self):
        for main_enabled, harness_enabled in product((False, True), repeat=2):
            with self.subTest(main=main_enabled, harness=harness_enabled):
                selected = ADMISSION.get_new_plan_contract_version(
                    {MAIN_FLAG: main_enabled, HARNESS_FLAG: harness_enabled},
                    admission_ready=ADMISSION.HARNESS_ADMISSION_READY,
                )
                self.assertEqual(selected, 2 if main_enabled and harness_enabled else 1)

    def test_missing_or_malformed_values_fail_closed_without_truthiness(self):
        for settings in (None, {}, {MAIN_FLAG: True}, {HARNESS_FLAG: True}, "true", [True]):
            selected = ADMISSION.get_new_plan_contract_version(settings, admission_ready=True)
            self.assertEqual(selected, 1)
        for value in ("false", "true", "on", "malformed", "", 0, 1, None, [], {"enabled": True}):
            for key in (MAIN_FLAG, HARNESS_FLAG):
                with self.subTest(key=key, value=value):
                    settings = {MAIN_FLAG: True, HARNESS_FLAG: True, key: value}
                    selected = ADMISSION.get_new_plan_contract_version(settings, admission_ready=True)
                    self.assertEqual(selected, 1)
            selected = ADMISSION.get_new_plan_contract_version(
                {MAIN_FLAG: True, HARNESS_FLAG: True}, admission_ready=value
            )
            self.assertEqual(selected, 1)

    def test_real_helper_imports_without_runtime_owners_or_io_in_normal_and_optimized_python(self):
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                command = [sys.executable, "-B"]
                if optimized:
                    command.append("-O")
                result = subprocess.run(
                    command + ["-c", IMPORT_PROBE, str(APP_ROOT)],
                    cwd=APP_ROOT.parents[1], capture_output=True, text=True,
                    timeout=30, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
