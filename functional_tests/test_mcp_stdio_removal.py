# test_mcp_stdio_removal.py
#!/usr/bin/env python3
"""
Functional tests for remote-only MCP configuration and manifest boundaries.
Version: 0.261.029
Implemented in: 0.261.029

Exercises real normalization and schema validation without cloud, credentials,
or native MCP processes. Runtime authorization and legacy management have
separate behavioral suites.
"""

import ast
import copy
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

from functions_action_manifest import (
    McpActionOrigin,
    McpConfigurationError,
    McpStdioRemovedError,
    bind_action_origin,
    copy_action_manifest,
    get_action_execution_status,
    get_action_origin,
    is_retired_mcp_stdio,
    resolve_action_type,
)
from functions_mcp_operations import (
    classify_mcp_exception,
    get_mcp_error_http_status,
    normalize_mcp_additional_fields,
    normalize_mcp_transport,
    validate_mcp_endpoint_for_transport,
)
from json_schema_validation import (
    apply_plugin_validation_defaults,
    validate_plugin,
    validate_plugin_auth_type_allowed,
)


MCP_ALIASES = ("mcp", "MCP", " McpPlugin ", "mcp_plugin", "model-context-protocol")


def remote_manifest(transport="streamable_http"):
    return {
        "name": "remote_action",
        "displayName": "Remote action",
        "type": "mcp",
        "description": "Offline configuration fixture",
        "endpoint": "https://mcp.example.test/mcp",
        "auth": {"type": "NoAuth"},
        "metadata": {"type": "mcp"},
        "additionalFields": {"transport": transport, "auth_method": "none"},
    }


class McpStdioRemovalTests(unittest.TestCase):
    def setUp(self):
        presets = types.ModuleType("functions_mcp_presets")
        presets.normalize_mcp_preset_id = Mock(side_effect=lambda value: str(value or "generic"))
        presets.mcp_server_preset_exists = Mock(return_value=True)
        self.presets = presets
        self.module_patch = patch.dict(sys.modules, {"functions_mcp_presets": presets})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)

    def test_effective_type_is_shared_by_defaults_and_auth_validation(self):
        for alias in MCP_ALIASES:
            for declared in ({"type": alias}, {"metadata": {"type": alias}}, {"type": " ", "metadata": {"type": alias}}):
                with self.subTest(declared=declared):
                    manifest = remote_manifest()
                    manifest.pop("type")
                    manifest.pop("metadata")
                    manifest.update(declared)
                    effective_type = resolve_action_type(manifest)
                    normalized = apply_plugin_validation_defaults(manifest)
                    self.assertEqual(effective_type, "mcp")
                    self.assertEqual(normalized["type"], "mcp")
                    manifest["auth"] = {"type": "user"}
                    error = validate_plugin_auth_type_allowed(manifest)
                    self.assertIsNotNone(error)

    def test_type_precedence_and_unrelated_runtime_types_are_preserved(self):
        for action_type in ("sql_query", "sql_schema", "http"):
            manifest = {"type": action_type, "metadata": {"type": "mcp"}}
            effective_type = resolve_action_type(manifest)
            self.assertEqual(effective_type, action_type)
        for invalid in ([], {}, 123, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                resolve_action_type({"type": invalid})

    def test_retired_transport_never_reaches_catalog_or_remote_defaults(self):
        for transport in ("stdio", "STDIO", " StDiO \t"):
            with self.subTest(transport=transport), self.assertRaises(McpStdioRemovedError):
                normalize_mcp_additional_fields({"transport": transport, "command": "unused"})
        self.presets.normalize_mcp_preset_id.assert_not_called()
        self.presets.mcp_server_preset_exists.assert_not_called()

    def test_unknown_explicit_transport_is_not_http(self):
        for transport in ("unsupported", "stdin", "std_io", 0, False, [], {}):
            with self.subTest(transport=transport), self.assertRaises(McpConfigurationError):
                normalize_mcp_transport(transport)

    def test_remote_aliases_are_idempotent(self):
        aliases = {
            None: "streamable_http",
            "": "streamable_http",
            "http": "streamable_http",
            "streamable-http": "streamable_http",
            "sse": "sse",
            "SSE": "sse",
            "server_sent_events": "sse",
            "eventsource": "sse",
            "ws": "websocket",
            "wss": "websocket",
            "websocket": "websocket",
        }
        for alias, expected in aliases.items():
            with self.subTest(alias=alias):
                normalized = normalize_mcp_transport(alias)
                repeated = normalize_mcp_transport(normalized)
                self.assertEqual(normalized, expected)
                self.assertEqual(repeated, expected)

    def test_remote_normalization_retires_only_process_settings(self):
        tool_schema = {"type": "object", "properties": {"command": {"type": "string"}, "env": {"type": "object"}}}
        fields = {
            "transport": "sse",
            "command": "inert",
            "args": ["inert"],
            "env": {"TOKEN": "inert-test-value"},
            "mcp_tools": [{"name": "example", "input_schema": tool_schema}],
        }
        original = copy.deepcopy(fields)
        normalized = normalize_mcp_additional_fields(fields)
        self.assertEqual(fields, original)
        self.assertFalse({"command", "args", "env"}.intersection(normalized))
        self.assertEqual(normalized["mcp_tools"][0]["input_schema"], tool_schema)

    def test_legacy_endpoints_are_not_reinterpreted_as_remote(self):
        for transport in ("http", "sse", "websocket", None):
            with self.subTest(transport=transport), self.assertRaises(McpStdioRemovedError):
                validate_mcp_endpoint_for_transport(" STDIO://local ", transport)
        for transport, endpoint in (("http", "https://example.test/mcp"), ("sse", "https://example.test/events"), ("websocket", "wss://example.test/mcp")):
            errors = validate_mcp_endpoint_for_transport(endpoint, transport)
            self.assertEqual(errors, [])

    def test_schema_validation_rejects_legacy_and_aliased_stdio(self):
        for alias in MCP_ALIASES:
            manifest = remote_manifest("stdio")
            manifest["type"] = alias
            error = validate_plugin(manifest)
            self.assertIn("no longer supported", error)
            manifest["additionalFields"]["transport"] = "http"
            manifest["endpoint"] = "stdio://local"
            error = validate_plugin(manifest)
            self.assertIn("no longer supported", error)

    def test_health_validation_does_not_trust_a_stale_type_argument(self):
        source_path = APP_DIR / "semantic_kernel_plugins" / "plugin_health_checker.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        checker = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PluginHealthChecker")
        validate = next(node for node in checker.body if isinstance(node, ast.FunctionDef) and node.name == "validate_plugin_manifest")
        validate.decorator_list = []
        # Isolate the MCP branch from unrelated plugin SDK imports; lifecycle tests
        # separately exercise real-module bootstrap with network access blocked.
        namespace = dict(globals())
        for node in ast.walk(validate):
            if isinstance(node, ast.Name) and node.id.isupper():
                namespace.setdefault(node.id, f"unrelated-{node.id}")
        namespace.update(vars(sys.modules["functions_mcp_operations"]))
        namespace.update(vars(sys.modules["functions_action_manifest"]))
        module = ast.Module(body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            validate,
        ], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(source_path), "exec"), namespace)
        for alias in MCP_ALIASES:
            manifest = remote_manifest("stdio")
            manifest.pop("type")
            manifest["metadata"]["type"] = alias
            valid, errors = namespace["validate_plugin_manifest"](manifest, "")
            self.assertFalse(valid)
            self.assertIn("no longer supported", errors[0])
            manifest["additionalFields"] = {"transport": "sse", "auth_method": "bearer"}
            valid, errors = namespace["validate_plugin_manifest"](manifest, "unrelated")
            self.assertFalse(valid)
            self.assertTrue(any("auth" in error for error in errors))

    def test_origin_is_not_client_serializable_authority(self):
        raw = {
            "id": "personal-id", "type": "MCP", "scope": "global",
            "scope_id": "global", "is_global": True, "is_group": True,
            "group_id": "forged-group", "runtime_user_id": "forged-user",
            "action_origin": {"scope_type": "global"},
        }
        untrusted_origin = get_action_origin(raw)
        bound = bind_action_origin(raw, "personal", "owner")
        clone = copy_action_manifest(bound)
        encoded = json.dumps(clone)
        decoded = json.loads(encoded)
        self.assertIsNone(untrusted_origin)
        self.assertEqual(get_action_origin(clone), McpActionOrigin("personal", "owner", "personal-id"))
        self.assertIsNone(get_action_origin(decoded))
        self.assertNotIn("action_origin", decoded)
        self.assertNotIn("runtime_user_id", decoded)
        self.assertFalse(decoded["is_global"])
        self.assertFalse(decoded["is_group"])
        self.assertEqual(decoded["scope_id"], "owner")
        self.assertEqual(decoded["user_id"], "owner")
        self.assertNotIn("group_id", decoded)

    def test_management_inspection_does_not_normalize_or_execute(self):
        manifest = remote_manifest("STDIO")
        manifest["additionalFields"]["command"] = "never-run"
        retired = is_retired_mcp_stdio(manifest)
        status = get_action_execution_status(manifest)
        self.assertTrue(retired)
        self.assertEqual(status["state"], "unsupported")
        self.assertEqual(status["code"], "mcp_stdio_removed")
        self.assertNotIn("never-run", json.dumps(status))
        self.presets.normalize_mcp_preset_id.assert_not_called()

    def test_configuration_and_authorization_errors_are_non_retryable(self):
        cases = (
            (McpStdioRemovedError(), "mcp_stdio_removed", 400),
            (McpConfigurationError(), "validation", 400),
            (ValueError("private-detail"), "validation", 400),
            (PermissionError("private-detail"), "authorization", 403),
        )
        for exception, category, status in cases:
            for operation in ("tool_call", "tool_discovery", "capability_probe"):
                with self.subTest(category=category, operation=operation):
                    error = classify_mcp_exception(exception, operation)
                    http_status = get_mcp_error_http_status(error["category"])
                    self.assertEqual(error["category"], category)
                    self.assertFalse(error["retryable"])
                    self.assertEqual(http_status, status)
                    self.assertNotIn("private-detail", json.dumps(error))


if __name__ == "__main__":
    unittest.main()
