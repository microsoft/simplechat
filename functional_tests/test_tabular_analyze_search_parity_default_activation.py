# test_tabular_analyze_search_parity_default_activation.py
#!/usr/bin/env python3
"""
Functional test for tabular Analyze/Search durable-preflight parity defaults.
Version: 0.250.186
Implemented in: 0.250.186

This test ensures the tabular Analyze/Search parity durable-preflight controls
default to active (no admin UI toggle required) and that the
SIMPLECHAT_DISABLE_TABULAR_PARITY_DURABLE_PREFLIGHT environment variable can
force them back off for emergency rollback.
"""

import ast
import sys
from pathlib import Path

from test_support.versioning import assert_app_version_at_least

ROOT_DIR = Path(__file__).resolve().parents[1]
SETTINGS_FILE = ROOT_DIR / "application" / "single_app" / "functions_settings.py"
IMPLEMENTED_VERSION = "0.250.186"


def _find_get_settings_default_dict(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_settings":
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and stmt.targets[0].id == "default_settings"
                ):
                    return stmt.value
    raise AssertionError("Could not locate default_settings dict in get_settings()")


def load_default_settings_literal():
    """Extract selected literal values from the default_settings dict via AST.

    The dict also contains non-literal expressions (helper function calls), so
    only the specific keys under test are evaluated.
    """
    source = SETTINGS_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SETTINGS_FILE))
    dict_node = _find_get_settings_default_dict(tree)

    wanted_keys = {
        "tabular_request_planner_mode",
        "enable_tabular_search_shared_preflight",
        "enable_tabular_analyze_durable_preflight",
        "enable_tabular_mixed_deferred_composition_planning",
        "enable_tabular_multifile_execution_unit_planning",
    }
    result = {}
    for key_node, value_node in zip(dict_node.keys, dict_node.values):
        if isinstance(key_node, ast.Constant) and key_node.value in wanted_keys:
            result[key_node.value] = ast.literal_eval(value_node)
    return result


def load_kill_switch_helpers():
    """Load the env kill-switch helpers without importing the full Flask app."""
    source = SETTINGS_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SETTINGS_FILE))
    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_env_flag_enabled", "_apply_tabular_parity_env_kill_switch"}
    ]
    assert len(selected_nodes) == 2, "Expected both env kill-switch helpers to be present"

    namespace = {"os": __import__("os")}
    exec(
        compile(ast.Module(body=selected_nodes, type_ignores=[]), str(SETTINGS_FILE), "exec"),
        namespace,
    )
    return namespace["_apply_tabular_parity_env_kill_switch"]


def test_tabular_parity_durable_preflight_defaults_active():
    """The durable-preflight parity controls ship active with no admin UI toggle."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    default_settings = load_default_settings_literal()

    assert default_settings["tabular_request_planner_mode"] == "active", (
        "tabular_request_planner_mode must default to active"
    )
    assert default_settings["enable_tabular_search_shared_preflight"] is True, (
        "enable_tabular_search_shared_preflight must default to True"
    )
    assert default_settings["enable_tabular_analyze_durable_preflight"] is True, (
        "enable_tabular_analyze_durable_preflight must default to True"
    )
    # Unimplemented planning-only controls stay off; enabling them has no execution effect yet.
    assert default_settings["enable_tabular_mixed_deferred_composition_planning"] is False
    assert default_settings["enable_tabular_multifile_execution_unit_planning"] is False

    admin_settings_html = (ROOT_DIR / "application" / "single_app" / "templates" / "admin_settings.html").read_text(
        encoding="utf-8"
    )
    assert "tabular_request_planner_mode" not in admin_settings_html, (
        "Always-on parity settings should not gain an admin UI toggle"
    )


def test_env_kill_switch_forces_parity_off(monkeypatch):
    """The emergency env var overrides stored settings back to legacy behavior."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    apply_kill_switch = load_kill_switch_helpers()

    settings = {
        "tabular_request_planner_mode": "active",
        "enable_tabular_search_shared_preflight": True,
        "enable_tabular_analyze_durable_preflight": True,
    }

    monkeypatch.delenv("SIMPLECHAT_DISABLE_TABULAR_PARITY_DURABLE_PREFLIGHT", raising=False)
    unaffected = apply_kill_switch(dict(settings))
    assert unaffected["tabular_request_planner_mode"] == "active"
    assert unaffected["enable_tabular_search_shared_preflight"] is True
    assert unaffected["enable_tabular_analyze_durable_preflight"] is True

    monkeypatch.setenv("SIMPLECHAT_DISABLE_TABULAR_PARITY_DURABLE_PREFLIGHT", "true")
    forced_off = apply_kill_switch(dict(settings))
    assert forced_off["tabular_request_planner_mode"] == "off"
    assert forced_off["enable_tabular_search_shared_preflight"] is False
    assert forced_off["enable_tabular_analyze_durable_preflight"] is False


if __name__ == "__main__":
    failures = 0
    for test in (test_tabular_parity_durable_preflight_defaults_active,):
        try:
            test()
            print(f"PASS: {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL: {test.__name__}: {exc}")

    class _FakeMonkeypatch:
        def __init__(self):
            self._saved = {}

        def setenv(self, name, value):
            import os

            self._saved.setdefault(name, os.environ.get(name))
            os.environ[name] = value

        def delenv(self, name, raising=False):
            import os

            self._saved.setdefault(name, os.environ.get(name))
            os.environ.pop(name, None)

    fake_monkeypatch = _FakeMonkeypatch()
    try:
        test_env_kill_switch_forces_parity_off(fake_monkeypatch)
        print(f"PASS: {test_env_kill_switch_forces_parity_off.__name__}")
    except AssertionError as exc:
        failures += 1
        print(f"FAIL: {test_env_kill_switch_forces_parity_off.__name__}: {exc}")

    sys.exit(1 if failures else 0)
