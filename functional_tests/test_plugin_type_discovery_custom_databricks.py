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

from pathlib import Path
import sys
import traceback


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "application" / "single_app"))
VIEW_UTILS_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "view-utils.js"

from functions_databricks_operations import is_builtin_databricks_discovery_type  # noqa: E402


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


if __name__ == "__main__":
    try:
        tests = [
            test_custom_databricks_prefixed_type_uses_standard_discovery,
            test_databricks_icon_classification_uses_exact_types,
        ]
        results = [bool(test()) for test in tests]
        success = all(results)
        print(f"Results: {sum(results)}/{len(results)} tests passed")
    except Exception as exc:
        print(f"Test failed: {exc}")
        traceback.print_exc()
        success = False
    sys.exit(0 if success else 1)
