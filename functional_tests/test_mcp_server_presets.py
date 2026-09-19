# test_mcp_server_presets.py
"""
Offline functional tests for declarative MCP server presets.
Version: 0.261.029
Implemented in: 0.250.062
Remote-only compatibility implemented in: 0.261.029

Validate real catalog/schema loading, isolated invalid presets, legacy remote
compatibility, and explicit retirement diagnostics without cloud or file writes.
"""

import copy
import importlib.util
import io
import json
import os
import sys
import types
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
PRESET_DIR = APP_DIR / "mcp_presets" / "definitions"
REMOTE_TRANSPORTS = {"streamable_http", "sse", "websocket"}


def _load_app_module(name):
    spec = importlib.util.spec_from_file_location(name, APP_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _virtual_custom_catalog(catalog, definitions, schemas=None):
    """Exercise directory and schema lookup using in-memory local fixture files."""
    directory = ROOT_DIR / "functional_tests" / "preset_catalog_fixture"
    files = {
        str(directory / f"{preset_id}.json"): json.dumps(definition)
        for preset_id, definition in definitions.items()
    }
    files.update({
        str(directory / "implementation_schemas" / file_name): json.dumps(schema)
        for file_name, schema in (schemas or {}).items()
    })
    real_open = open
    real_isdir = os.path.isdir
    real_isfile = os.path.isfile
    real_listdir = os.listdir

    def open_fixture(file_path, *args, **kwargs):
        content = files.get(str(file_path))
        if content is not None:
            return io.StringIO(content)
        return real_open(file_path, *args, **kwargs)

    def list_fixture(directory_path):
        if str(directory_path) == str(directory):
            return [Path(file_path).name for file_path in files if Path(file_path).parent == directory]
        return real_listdir(directory_path)

    with (
        patch.dict(os.environ, {catalog.MCP_PRESET_PATHS_ENV: str(directory)}),
        patch("builtins.open", side_effect=open_fixture),
        patch("os.path.isdir", side_effect=lambda path: str(path) == str(directory) or real_isdir(path)),
        patch("os.path.isfile", side_effect=lambda path: str(path) in files or real_isfile(path)),
        patch("os.listdir", side_effect=list_fixture),
    ):
        catalog.clear_mcp_server_preset_cache()
        try:
            yield
        finally:
            catalog.clear_mcp_server_preset_cache()


class McpServerPresetTests(unittest.TestCase):
    def setUp(self):
        scope = ExitStack()
        self.addCleanup(scope.close)
        scope.enter_context(patch.object(sys, "path", [str(APP_DIR), *sys.path]))
        scope.enter_context(patch("socket.create_connection", side_effect=AssertionError("Network is forbidden.")))
        scope.enter_context(patch("socket.socket.connect", side_effect=AssertionError("Network is forbidden.")))
        logger = types.ModuleType("functions_appinsights")
        logger.log_event = Mock()
        scope.enter_context(patch.dict(sys.modules, {"functions_appinsights": logger}))
        self.catalog = _load_app_module("functions_mcp_presets")
        scope.enter_context(patch.dict(sys.modules, {"functions_mcp_presets": self.catalog}))
        self.operations = _load_app_module("functions_mcp_operations")
        scope.enter_context(patch.dict(os.environ, {self.catalog.MCP_PRESET_PATHS_ENV: ""}))
        self.logs = logger.log_event
        self.addCleanup(self.catalog.clear_mcp_server_preset_cache)

    def make_preset(self, preset_id, transport="sse"):
        preset = copy.deepcopy(self.catalog.MCP_FALLBACK_GENERIC_PRESET)
        preset["id"] = preset_id
        preset["defaults"]["transport"] = transport
        return preset

    def test_builtin_mcp_server_presets(self):
        presets = self.catalog.load_mcp_server_presets()
        preset_ids = {preset["id"] for preset in presets}
        self.assertIn("generic", preset_ids)
        self.assertIn("splunk", preset_ids)
        for value, expected in (("splunk", "splunk"), ("splunk_enterprise", "splunk"), ("../unsafe", "generic")):
            normalized = self.operations.normalize_mcp_server_profile(value)
            self.assertEqual(normalized, expected)

        splunk = self.catalog.get_mcp_server_preset("splunk")
        self.assertEqual(splunk["defaults"]["transport"], "streamable_http")
        self.assertEqual(splunk["defaults"]["auth_method"], "bearer")
        self.assertEqual(splunk["implementation"]["id"], "splunk")
        self.assertEqual(splunk["additionalSettings"]["compatibilityProfile"], "splunk_mcp")
        self.assertEqual(splunk["additionalSettings"]["customHeaderValueHandling"], "secret")

        response = self.catalog.build_mcp_server_presets_response()
        self.assertEqual(response["defaultPreset"], "generic")
        self.assertEqual({preset["id"] for preset in response["presets"]}, preset_ids)
        for preset in response["presets"]:
            self.assertIn("source", preset)
            self.assertNotIn("stdioAllowed", preset["constraints"])
            self.assertLessEqual(set(preset["constraints"]["allowedTransports"]), REMOTE_TRANSPORTS)
            self.assertIn(preset["defaults"]["transport"], REMOTE_TRANSPORTS)
            self.assertFalse({"command", "args", "env", "auth", "endpoint"} & preset["defaults"].keys())

        for preset_file in PRESET_DIR.glob("*.json"):
            preset = json.loads(preset_file.read_text(encoding="utf-8"))
            self.assertEqual(preset["id"], preset_file.stem)
            self.assertNotIn("stdioAllowed", preset["constraints"])
            self.assertNotIn("stdio", preset["constraints"]["allowedTransports"])

    def test_custom_path_and_implementation_failure_isolation(self):
        custom = self.make_preset("contoso")
        custom["constraints"]["allowedTransports"] = ["sse", "stdio"]
        custom["constraints"]["stdioAllowed"] = False
        custom["implementation"] = {"id": "contoso", "schemaVersion": "1.0.0"}
        custom["additionalSettings"] = {"routingMode": "contoso_gateway"}
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["routingMode"],
            "properties": {"routingMode": {"enum": ["contoso_gateway"]}},
        }
        invalid = copy.deepcopy(custom)
        invalid["id"] = "invalid_contoso"
        invalid["additionalSettings"] = {"routingMode": "invalid"}
        unknown = copy.deepcopy(custom)
        unknown["id"] = "unknown_schema"
        unknown["implementation"]["id"] = "missing_schema"
        definitions = {preset["id"]: preset for preset in (custom, invalid, unknown)}
        with _virtual_custom_catalog(self.catalog, definitions, {"contoso.preset.schema.json": schema}):
            loaded = {preset["id"]: preset for preset in self.catalog.load_mcp_server_presets()}
            normalized = self.operations.normalize_mcp_server_profile("contoso")
        self.assertIn("generic", loaded)
        self.assertIn("splunk", loaded)
        self.assertIn("contoso", loaded)
        self.assertNotIn("invalid_contoso", loaded)
        self.assertNotIn("unknown_schema", loaded)
        self.assertEqual(normalized, "contoso")
        self.assertEqual(loaded["contoso"]["defaults"]["transport"], "sse")
        self.assertEqual(loaded["contoso"]["constraints"]["allowedTransports"], ["sse"])
        self.assertEqual(loaded["contoso"]["additionalSettings"], custom["additionalSettings"])
        self.assertEqual(custom["constraints"]["allowedTransports"], ["sse", "stdio"])

    def test_legacy_remote_presets_keep_defaults_without_mutating_source(self):
        definitions = {}
        for index, transport in enumerate(sorted(REMOTE_TRANSPORTS)):
            preset = self.make_preset(f"remote_{index}", transport)
            preset["constraints"]["allowedTransports"] = [" StDiO ", transport]
            preset["constraints"]["stdioAllowed"] = index % 2 == 0
            definitions[preset["id"]] = preset
        original = copy.deepcopy(definitions)
        with _virtual_custom_catalog(self.catalog, definitions):
            loaded = {preset["id"]: preset for preset in self.catalog.load_mcp_server_presets()}
        for preset_id, preset in definitions.items():
            self.assertEqual(loaded[preset_id]["defaults"]["transport"], preset["defaults"]["transport"])
            self.assertEqual(loaded[preset_id]["constraints"]["allowedTransports"], [preset["defaults"]["transport"]])
            self.assertNotIn("stdioAllowed", loaded[preset_id]["constraints"])
        self.assertEqual(definitions, original)

        nested = self.make_preset("nested")
        nested["additionalSettings"] = {"toolArguments": {"command": "tool-command", "args": ["value"], "env": {"name": "value"}}}
        sanitized = self.catalog._normalize_remote_mcp_preset(nested)
        self.assertEqual(sanitized["additionalSettings"], nested["additionalSettings"])
        self.assertIsNot(sanitized["additionalSettings"], nested["additionalSettings"])

    def test_unavailable_presets_are_skipped_with_safe_diagnostics(self):
        default_stdio = self.make_preset("retired_default", " StDiO ")
        default_stdio["defaults"]["command"] = "DO_NOT_LOG_PROCESS_VALUE"
        only_stdio = self.make_preset("retired_only")
        only_stdio["constraints"]["allowedTransports"] = ["stdio"]
        no_transports = self.make_preset("retired_empty")
        no_transports["constraints"]["allowedTransports"] = []
        contradictory = self.make_preset("contradictory", "websocket")
        contradictory["constraints"]["allowedTransports"] = ["sse", "stdio"]
        malformed = self.make_preset("malformed")
        malformed["constraints"]["allowedTransports"] = [{"transport": "sse"}, "sse"]
        valid = self.make_preset("still_available")
        definitions = {preset["id"]: preset for preset in (default_stdio, only_stdio, no_transports, contradictory, malformed, valid)}
        with _virtual_custom_catalog(self.catalog, definitions):
            loaded = {preset["id"]: preset for preset in self.catalog.load_mcp_server_presets()}
        self.assertTrue({"generic", "splunk", "still_available"} <= loaded.keys())
        for preset_id in definitions.keys() - {"still_available"}:
            self.assertNotIn(preset_id, loaded)
        messages = "\n".join(call.args[0] for call in self.logs.call_args_list)
        self.assertIn("default transport is stdio", messages)
        self.assertIn("no supported remote transport", messages)
        self.assertNotIn("DO_NOT_LOG_PROCESS_VALUE", messages)

    def test_fallback_and_emitted_schemas_are_remote_only(self):
        with patch.object(self.catalog, "_iter_preset_definition_paths", return_value=[]):
            presets = self.catalog.load_mcp_server_presets()
        self.assertEqual(len(presets), 1)
        self.assertEqual(presets[0]["source"], "fallback")
        self.assertNotIn("stdioAllowed", presets[0]["constraints"])
        self.assertEqual(set(presets[0]["constraints"]["allowedTransports"]), REMOTE_TRANSPORTS)

        schema = self.catalog._load_mcp_preset_schema()
        constraints = schema["properties"]["constraints"]
        self.assertNotIn("stdioAllowed", constraints["required"])
        self.assertNotIn("stdioAllowed", constraints["properties"])
        action_schema = json.loads(
            (APP_DIR / "static" / "json" / "schemas" / "mcp_plugin.additional_settings.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(action_schema["properties"]["transport"]["enum"]), REMOTE_TRANSPORTS)
        self.assertFalse({"command", "args", "env"} & action_schema["properties"].keys())
        self.assertTrue(action_schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
