# test_plugin_type_discovery_custom_databricks.py
#!/usr/bin/env python3
"""
Functional test for custom Databricks-prefixed plugin type discovery.
Version: 0.250.103
Implemented in: 0.250.103

This test ensures custom plugin types such as databricks_table_dscmo do not
receive the built-in Databricks discovery defaults or visual treatment that
drive the Databricks action creation experience.
"""

import ast
import json
from pathlib import Path
import sys
import tempfile
import textwrap
import traceback

from flask import Flask, jsonify

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "application" / "single_app"))
ROUTE_BACKEND_PLUGINS_FILE = REPO_ROOT / "application" / "single_app" / "route_backend_plugins.py"
VIEW_UTILS_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "view-utils.js"

from functions_plugins import get_merged_plugin_settings  # noqa: E402
from functions_databricks_operations import is_builtin_databricks_discovery_type  # noqa: E402
from semantic_kernel_plugins.base_plugin import BasePlugin  # noqa: E402


def load_get_plugin_types_for_test():
    """Load get_plugin_types without importing the full route module and app config."""
    source = ROUTE_BACKEND_PLUGINS_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(ROUTE_BACKEND_PLUGINS_FILE))
    function_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_plugin_types"
    )
    test_module = ast.Module(body=[function_node], type_ignores=[])
    ast.fix_missing_locations(test_module)

    namespace = {
        "os": __import__("os"),
        "importlib": __import__("importlib"),
        "current_app": __import__("flask").current_app,
        "jsonify": jsonify,
        "BasePlugin": BasePlugin,
        "debug_print": lambda *args, **kwargs: None,
        "is_builtin_databricks_discovery_type": is_builtin_databricks_discovery_type,
    }
    exec(compile(test_module, str(ROUTE_BACKEND_PLUGINS_FILE), "exec"), namespace)
    return namespace["get_plugin_types"]


def scaffold_fake_databricks_prefixed_plugin(root_path: Path) -> Path:
    """Create a temporary plugin plus matching schema and definition files."""
    plugin_dir = root_path / "semantic_kernel_plugins"
    schema_dir = root_path / "static" / "json" / "schemas"
    plugin_dir.mkdir(parents=True)
    schema_dir.mkdir(parents=True)

    plugin_file = plugin_dir / "databricks_table_dscmo_plugin.py"
    plugin_file.write_text(
        textwrap.dedent(
            '''
            # databricks_table_dscmo_plugin.py
            """Temporary test plugin for custom Databricks-prefixed discovery."""

            from typing import Any, Dict, Optional

            from semantic_kernel_plugins.base_plugin import BasePlugin


            class DatabricksTableDscmoPlugin(BasePlugin):
                def __init__(self, manifest: Optional[Dict[str, Any]] = None):
                    super().__init__(manifest)
                    additional_fields = self.manifest.get("additionalFields", {})
                    self.received_databricks_manifest = bool(additional_fields.get("warehouse_id"))

                @property
                def display_name(self) -> str:
                    if self.received_databricks_manifest:
                        return "Databricks UI Fake DSCMO"
                    return "Standard Fake DSCMO"

                @property
                def metadata(self) -> Dict[str, Any]:
                    description = (
                        "Databricks-specific metadata"
                        if self.received_databricks_manifest
                        else "Standard DSCMO metadata"
                    )
                    return {
                        "name": "databricks_table_dscmo",
                        "type": "databricks_table_dscmo",
                        "description": description,
                        "methods": []
                    }
            '''
        ).lstrip(),
        encoding="utf-8",
    )

    (schema_dir / "databricks_table_dscmo.definition.json").write_text(
        json.dumps(
            {
                "$schema": "./plugin.definition.schema.json",
                "allowedAuthTypes": ["key", "identity"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (schema_dir / "databricks_table_dscmo_plugin.additional_settings.schema.json").write_text(
        json.dumps(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "title": "DSCMO Plugin Additional Settings",
                "type": "object",
                "properties": {
                    "dscmo_table": {
                        "type": "string",
                        "default": "customers",
                        "description": "Fake DSCMO table name."
                    }
                },
                "required": ["dscmo_table"],
                "additionalProperties": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (schema_dir / "databricks_table_dscmo_plugin.metadata.schema.json").write_text(
        json.dumps(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "title": "DSCMO Plugin Metadata",
                "type": "object",
                "properties": {
                    "ui_variant": {
                        "type": "string",
                        "default": "standard",
                        "description": "Expected UI variant."
                    }
                },
                "required": ["ui_variant"],
                "additionalProperties": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return schema_dir


def test_custom_databricks_prefixed_type_uses_standard_discovery() -> bool:
    """Verify only exact built-in Databricks types get Databricks discovery defaults."""
    print("Testing custom Databricks-prefixed plugin discovery classification...")

    built_in_types = ["databricks", "databricks_table", "DATABRICKS_TABLE"]
    custom_types = ["databricks_table_dscmo", "databricks_custom", "custom_databricks_table"]

    for plugin_type in built_in_types:
        if not is_builtin_databricks_discovery_type(plugin_type):
            print(f"Expected built-in Databricks type classification for: {plugin_type}")
            return False

    for plugin_type in custom_types:
        if is_builtin_databricks_discovery_type(plugin_type):
            print(f"Unexpected Databricks type classification for custom type: {plugin_type}")
            return False

    print("Custom Databricks-prefixed plugin discovery classification test passed!")
    return True


def test_databricks_icon_classification_uses_exact_types() -> bool:
    """Verify visual type classification does not broad-match custom Databricks names."""
    print("Testing Databricks action icon classification...")

    content = VIEW_UTILS_FILE.read_text(encoding="utf-8")
    exact_match_marker = 'if (t === "databricks" || t === "databricks_table") return "bi-bricks";'
    broad_match_marker = 'if (t.includes("databricks")) return "bi-bricks";'

    if exact_match_marker not in content:
        print("Missing exact Databricks icon classification marker.")
        return False
    if broad_match_marker in content:
        print("Found broad Databricks icon classification marker.")
        return False

    print("Databricks action icon classification test passed!")
    return True


def test_fake_databricks_prefixed_plugin_uses_standard_discovery_path() -> bool:
    """Scaffold a temporary plugin and verify discovery keeps it standard."""
    print("Testing fake Databricks-prefixed plugin scaffold through discovery...")

    get_plugin_types = load_get_plugin_types_for_test()
    with tempfile.TemporaryDirectory() as temp_dir:
        root_path = Path(temp_dir)
        schema_dir = scaffold_fake_databricks_prefixed_plugin(root_path)
        app = Flask("custom-databricks-plugin-test", root_path=str(root_path))

        with app.app_context():
            response = get_plugin_types()
            plugin_types = response.get_json()

        fake_plugin = next(
            (plugin_type for plugin_type in plugin_types if plugin_type.get("type") == "databricks_table_dscmo"),
            None,
        )
        if fake_plugin is None:
            print("Fake databricks_table_dscmo plugin was not discovered.")
            return False
        if fake_plugin.get("display") != "Standard Fake DSCMO":
            print(f"Fake plugin used the wrong UI path: {fake_plugin}")
            return False
        if fake_plugin.get("description") != "Standard DSCMO metadata":
            print(f"Fake plugin used the wrong metadata path: {fake_plugin}")
            return False

        merged_settings = get_merged_plugin_settings("databricks_table_dscmo", {}, str(schema_dir))
        if merged_settings.get("additionalFields", {}).get("dscmo_table") != "customers":
            print(f"Fake additional settings schema did not merge correctly: {merged_settings}")
            return False
        if merged_settings.get("metadata", {}).get("ui_variant") != "standard":
            print(f"Fake metadata schema did not merge correctly: {merged_settings}")
            return False

    print("Fake Databricks-prefixed plugin scaffold discovery test passed!")
    return True


if __name__ == "__main__":
    try:
        tests = [
            test_custom_databricks_prefixed_type_uses_standard_discovery,
            test_databricks_icon_classification_uses_exact_types,
            test_fake_databricks_prefixed_plugin_uses_standard_discovery_path,
        ]
        results = [bool(test()) for test in tests]
        success = all(results)
        print(f"Results: {sum(results)}/{len(results)} tests passed")
    except Exception as exc:
        print(f"Test failed: {exc}")
        traceback.print_exc()
        success = False
    sys.exit(0 if success else 1)
