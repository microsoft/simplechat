# test_tabular_parity_stale_settings_migration.py
#!/usr/bin/env python3
"""
Functional test for the tabular durable-preflight parity stale-settings migration.
Version: 0.250.198
Implemented in: 0.250.198

deep_merge_dicts() (used by get_settings() to merge code-level defaults into a
persisted Cosmos settings document) only fills in keys that are *missing* from
the stored document; it never overwrites a key that already exists. The four
tabular durable-preflight parity flags (tabular_request_planner_mode,
enable_tabular_search_shared_preflight, enable_tabular_analyze_durable_preflight,
enable_tabular_hierarchical_analysis) were originally introduced with off/False
defaults, so any deployment whose settings document already stored those keys
kept the old off/False values forever, even after the code-level defaults were
later raised to active/True. Every tabular Analyze/Search request in such a
deployment silently kept falling back to the legacy bounded foreground path.

This test ensures normalize_tabular_parity_durable_preflight_defaults() corrects
stale persisted values to the active defaults, leaves already-correct settings
untouched (no unnecessary Cosmos upsert), and that it is wired into
get_settings()'s merge/upsert flow.
"""

import ast
from pathlib import Path

from test_support.versioning import assert_app_version_at_least

ROOT_DIR = Path(__file__).resolve().parents[1]
SETTINGS_FILE = ROOT_DIR / "application" / "single_app" / "functions_settings.py"
IMPLEMENTED_VERSION = "0.250.198"

ACTIVE_DEFAULTS = {
    "tabular_request_planner_mode": "active",
    "enable_tabular_search_shared_preflight": True,
    "enable_tabular_analyze_durable_preflight": True,
    "enable_tabular_hierarchical_analysis": True,
}

STALE_PRE_ACTIVATION_VALUES = {
    "tabular_request_planner_mode": "off",
    "enable_tabular_search_shared_preflight": False,
    "enable_tabular_analyze_durable_preflight": False,
    "enable_tabular_hierarchical_analysis": False,
}


def load_migration_function():
    """Load normalize_tabular_parity_durable_preflight_defaults() without importing
    the full functions_settings module (it constructs Azure clients at import time)."""
    source = SETTINGS_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SETTINGS_FILE))

    selected_nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "normalize_tabular_parity_durable_preflight_defaults":
            selected_nodes.append(node)
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "TABULAR_PARITY_DURABLE_PREFLIGHT_ACTIVE_DEFAULTS"
        ):
            selected_nodes.append(node)

    assert len(selected_nodes) == 2, (
        "Expected both TABULAR_PARITY_DURABLE_PREFLIGHT_ACTIVE_DEFAULTS and "
        "normalize_tabular_parity_durable_preflight_defaults() to be present"
    )

    namespace = {}
    exec(
        compile(ast.Module(body=selected_nodes, type_ignores=[]), str(SETTINGS_FILE), "exec"),
        namespace,
    )
    return namespace["normalize_tabular_parity_durable_preflight_defaults"], namespace[
        "TABULAR_PARITY_DURABLE_PREFLIGHT_ACTIVE_DEFAULTS"
    ]


def test_active_defaults_constant_matches_expected_values():
    """The active-defaults map must match the values get_settings() ships."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    _, active_defaults = load_migration_function()
    assert active_defaults == ACTIVE_DEFAULTS


def test_stale_pre_activation_settings_are_upgraded():
    """A settings document persisted before the parity defaults were raised gets corrected."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    normalize_fn, _ = load_migration_function()

    settings = dict(STALE_PRE_ACTIVATION_VALUES)
    settings["unrelated_key"] = "left_alone"

    changed = normalize_fn(settings)

    assert changed is True, "Stale off/False parity flags must be reported as changed"
    for key, expected_value in ACTIVE_DEFAULTS.items():
        assert settings[key] == expected_value, f"{key} was not upgraded to its active default"
    assert settings["unrelated_key"] == "left_alone"


def test_already_active_settings_are_left_untouched():
    """Settings that already match the active defaults report no change (avoids Cosmos churn)."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    normalize_fn, _ = load_migration_function()

    settings = dict(ACTIVE_DEFAULTS)
    changed = normalize_fn(settings)

    assert changed is False, "Already-active parity flags must not be reported as changed"
    assert settings == ACTIVE_DEFAULTS


def test_partial_drift_is_corrected():
    """Only the flags that drifted from active should be corrected; others stay reported as changed."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    normalize_fn, _ = load_migration_function()

    settings = dict(ACTIVE_DEFAULTS)
    settings["enable_tabular_hierarchical_analysis"] = False

    changed = normalize_fn(settings)

    assert changed is True
    assert settings["enable_tabular_hierarchical_analysis"] is True
    assert settings["tabular_request_planner_mode"] == "active"


def test_non_dict_input_is_handled_safely():
    """Defensive guard: non-dict input must not raise and must report no change."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    normalize_fn, _ = load_migration_function()

    assert normalize_fn(None) is False
    assert normalize_fn("not-a-dict") is False


def test_migration_is_wired_into_get_settings_merge_flow():
    """normalize_tabular_parity_durable_preflight_defaults() must run on every settings load
    and trigger the Cosmos upsert when it corrects stale values."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    source = SETTINGS_FILE.read_text(encoding="utf-8")

    assert "tabular_parity_durable_preflight_settings_updated = normalize_tabular_parity_durable_preflight_defaults(merged)" in source, (
        "get_settings() must call normalize_tabular_parity_durable_preflight_defaults(merged) "
        "during its merge/migration step"
    )

    get_settings_start = source.index("def get_settings(")
    upsert_condition_start = source.index("cosmos_settings_container.upsert_item(merged)", get_settings_start)
    condition_block = source[get_settings_start:upsert_condition_start]

    assert "or tabular_parity_durable_preflight_settings_updated" in condition_block, (
        "tabular_parity_durable_preflight_settings_updated must be included in the "
        "upsert-trigger condition so corrected values are persisted back to Cosmos DB"
    )


if __name__ == "__main__":
    tests = [
        test_active_defaults_constant_matches_expected_values,
        test_stale_pre_activation_settings_are_upgraded,
        test_already_active_settings_are_left_untouched,
        test_partial_drift_is_corrected,
        test_non_dict_input_is_handled_safely,
        test_migration_is_wired_into_get_settings_merge_flow,
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL: {test.__name__}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"ERROR: {test.__name__}: {exc}")

    total = len(tests)
    print(f"\n{total - failures}/{total} tests passed")
    import sys
    sys.exit(0 if failures == 0 else 1)
