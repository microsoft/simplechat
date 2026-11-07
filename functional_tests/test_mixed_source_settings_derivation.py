#!/usr/bin/env python3
# test_mixed_source_settings_derivation.py
"""
Functional test for the mixed-source admin settings clean-up.
Version: 0.261.266
Implemented in: 0.261.266

The V2 admin page drew five mixed-source switches under Knowledge > Web & Research >
Deep Research, labelled only with their key names, because nothing declared them and the
fallback scan matched the word "source". Two of them did nothing: one had been retired in
0.250.071 and survived only in stored settings, and one depended on a hidden switch.

This test ensures that:

- Mixed-source Chat and Search, follow-up continuity and cross-format Compare follow
  Enhanced Citations on every settings load and save, because that is when the
  spreadsheet engine they need exists.
- SIMPLECHAT_DISABLE_MIXED_SOURCE turns them off at read time without changing what is
  stored.
- The retired switches are purged from stored settings.
- A one-time upgrade turns relevance candidates on and Analyze All off, and an
  administrator's later choice survives every subsequent load.
- The two real choices are declared with descriptions where they belong, in both admin
  interfaces, and the classic save persists them.
"""

import ast
import copy
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
SETTINGS_FILE = APP_ROOT / "functions_settings.py"
WORKFLOW_RUNNER_FILE = APP_ROOT / "functions_workflow_runner.py"
ADMIN_ROUTE_FILE = APP_ROOT / "route_frontend_admin_settings.py"
PANES_DIR = APP_ROOT / "templates" / "admin" / "_panes"

IMPLEMENTED_VERSION = "0.261.266"
KILL_SWITCH = "SIMPLECHAT_DISABLE_MIXED_SOURCE"
DERIVED_KEYS = (
    "enable_mixed_source_chat_search",
    "enable_mixed_source_conversation_continuity",
    "enable_cross_format_compare",
    "enable_cross_format_compare_one_to_many",
)
RETIRED_KEYS = ("enable_mixed_source_analyze", "enable_mixed_source_manifest")
SETTINGS_NAMES = {
    "is_tabular_processing_enabled",
    "_env_flag_enabled",
    "is_mixed_source_chat_search_enabled",
    "is_mixed_source_conversation_continuity_enabled",
    "is_cross_format_compare_enabled",
    "is_cross_format_compare_one_to_many_enabled",
    "is_mixed_source_relevance_candidates_enabled",
    "normalize_mixed_source_derived_settings",
    "normalize_mixed_source_settings_upgrade",
    "_apply_mixed_source_env_kill_switch",
    "normalize_retired_orchestration_settings",
    "deep_merge_dicts",
    "MIXED_SOURCE_DERIVED_SETTING_KEYS",
    "MIXED_SOURCE_KILL_SWITCH_ENV",
    "MIXED_SOURCE_SETTINGS_VERSION_KEY",
    "MIXED_SOURCE_SETTINGS_VERSION",
    "RETIRED_SETTING_KEYS",
}


def _settings_source():
    return SETTINGS_FILE.read_text(encoding="utf-8")


def load_settings_functions():
    """Load the production helpers without importing config or Azure clients."""
    tree = ast.parse(_settings_source(), filename=str(SETTINGS_FILE))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in SETTINGS_NAMES:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in SETTINGS_NAMES
            for target in node.targets
        ):
            selected.append(node)
    namespace = {"os": os}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SETTINGS_FILE), "exec"), namespace)
    missing = sorted(name for name in SETTINGS_NAMES if name not in namespace)
    assert not missing, f"functions_settings.py no longer defines: {missing}"
    return namespace


def _get_settings_node():
    tree = ast.parse(_settings_source(), filename=str(SETTINGS_FILE))
    return next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_settings"
    )


def read_default_settings(keys):
    """Return the literal defaults get_settings() ships for the named keys."""
    get_settings = _get_settings_node()
    defaults_node = next(
        statement.value for statement in get_settings.body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "default_settings" for target in statement.targets)
    )
    found = {}
    for key_node, value_node in zip(defaults_node.keys, defaults_node.values):
        if isinstance(key_node, ast.Constant) and key_node.value in keys:
            found[key_node.value] = ast.literal_eval(value_node)
    return found


def all_default_keys():
    get_settings = _get_settings_node()
    defaults_node = next(
        statement.value for statement in get_settings.body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "default_settings" for target in statement.targets)
    )
    return {
        key_node.value for key_node in defaults_node.keys
        if isinstance(key_node, ast.Constant)
    }


def _source_segment(function_name, *, nested_in=None):
    source = _settings_source()
    tree = ast.parse(source, filename=str(SETTINGS_FILE))
    scope = tree
    if nested_in:
        scope = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == nested_in
        )
    node = next(
        item for item in ast.walk(scope)
        if isinstance(item, ast.FunctionDef) and item.name == function_name
    )
    return ast.get_source_segment(source, node) or ""


def simulate_settings_load(functions, stored, defaults):
    """Replay the mixed-source steps get_settings() applies to a stored document."""
    persisted = copy.deepcopy(stored)
    functions["deep_merge_dicts"](defaults, persisted)
    functions["normalize_retired_orchestration_settings"](persisted)
    functions["normalize_mixed_source_derived_settings"](persisted)
    functions["normalize_mixed_source_settings_upgrade"](persisted)
    returned = functions["_apply_mixed_source_env_kill_switch"](copy.deepcopy(persisted))
    return persisted, returned


def _defaults_for_simulation():
    keys = set(DERIVED_KEYS) | {
        "enable_enhanced_citations",
        "enable_mixed_source_relevance_candidates",
        "enable_mixed_source_analyze_all",
        "enable_mixed_source_development_telemetry",
        "mixed_source_settings_version",
    }
    defaults = read_default_settings(keys)
    assert set(defaults) == keys, f"Missing defaults: {sorted(keys - set(defaults))}"
    return defaults


def test_derived_behaviors_follow_enhanced_citations():
    """Each derived behavior is on exactly when spreadsheet processing exists."""
    print("Testing that the derived mixed-source behaviors follow Enhanced Citations...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    functions = load_settings_functions()
    derive = functions["normalize_mixed_source_derived_settings"]

    assert tuple(functions["MIXED_SOURCE_DERIVED_SETTING_KEYS"]) == DERIVED_KEYS

    stored_off = {"enable_enhanced_citations": True, **{key: False for key in DERIVED_KEYS}}
    assert derive(stored_off) is True
    assert all(stored_off[key] is True for key in DERIVED_KEYS)
    assert derive(stored_off) is False, "A second pass must not report a change"

    stored_on = {"enable_enhanced_citations": False, **{key: True for key in DERIVED_KEYS}}
    assert derive(stored_on) is True
    assert all(stored_on[key] is False for key in DERIVED_KEYS)

    # A string left by an old save is corrected to a real boolean.
    stringly = {"enable_enhanced_citations": True, "enable_cross_format_compare": "true"}
    derive(stringly)
    assert stringly["enable_cross_format_compare"] is True

    # The runtime gates read the derived values unchanged.
    assert functions["is_mixed_source_chat_search_enabled"](stored_off) is True
    assert functions["is_cross_format_compare_one_to_many_enabled"](stored_off) is True
    assert functions["is_mixed_source_chat_search_enabled"](stored_on) is False
    print("  Derived behaviors follow Enhanced Citations.")
    return True


def test_subordinate_switches_need_their_parent():
    """Relevance candidates and continuity have no effect without Chat and Search."""
    print("\nTesting subordinate gating...")
    functions = load_settings_functions()
    without_chat = {
        "enable_mixed_source_chat_search": False,
        "enable_mixed_source_relevance_candidates": True,
        "enable_mixed_source_conversation_continuity": True,
    }
    assert functions["is_mixed_source_relevance_candidates_enabled"](without_chat) is False
    assert functions["is_mixed_source_conversation_continuity_enabled"](without_chat) is False
    with_chat = {**without_chat, "enable_mixed_source_chat_search": True}
    assert functions["is_mixed_source_relevance_candidates_enabled"](with_chat) is True
    assert functions["is_mixed_source_conversation_continuity_enabled"](with_chat) is True
    print("  Subordinate switches follow their parent.")
    return True


def test_kill_switch_applies_at_read_time_only():
    """The env kill switch overrides each read and never reaches the stored document."""
    print("\nTesting the SIMPLECHAT_DISABLE_MIXED_SOURCE kill switch...")
    functions = load_settings_functions()
    assert functions["MIXED_SOURCE_KILL_SWITCH_ENV"] == KILL_SWITCH
    defaults = _defaults_for_simulation()
    stored = {"enable_enhanced_citations": True, "mixed_source_settings_version": 1}

    original = os.environ.get(KILL_SWITCH)
    try:
        for value in ("1", "true", "YES", " on "):
            os.environ[KILL_SWITCH] = value
            persisted, returned = simulate_settings_load(functions, stored, defaults)
            assert all(persisted[key] is True for key in DERIVED_KEYS), (
                "The kill switch must not change what is persisted"
            )
            assert all(returned[key] is False for key in DERIVED_KEYS), (
                f"The kill switch value {value!r} must turn the derived behaviors off"
            )
        for value in ("", "0", "false", "off"):
            os.environ[KILL_SWITCH] = value
            _, returned = simulate_settings_load(functions, stored, defaults)
            assert all(returned[key] is True for key in DERIVED_KEYS)
    finally:
        if original is None:
            os.environ.pop(KILL_SWITCH, None)
        else:
            os.environ[KILL_SWITCH] = original

    # Wiring: applied to every read, and only there.
    format_result = _source_segment("_format_result", nested_in="get_settings")
    loader = _source_segment("normalize_loaded_settings", nested_in="get_settings")
    updater = _source_segment("update_settings")
    assert "_apply_mixed_source_env_kill_switch(settings_payload)" in format_result
    assert "_apply_mixed_source_env_kill_switch" not in loader
    assert "_apply_mixed_source_env_kill_switch" not in updater
    print("  The kill switch is read-time only.")
    return True


def test_loads_and_saves_both_derive():
    """Loading and saving both rewrite the derived values, like the tabular plugin flag."""
    print("\nTesting load and save wiring...")
    loader = _source_segment("normalize_loaded_settings", nested_in="get_settings")
    updater = _source_segment("update_settings")
    assert "normalize_mixed_source_derived_settings(merged)" in loader
    assert "normalize_mixed_source_settings_upgrade(merged)" in loader
    assert "normalize_mixed_source_derived_settings(settings_item)" in updater
    # The one-time upgrade must run only on load: a save is an administrator's choice.
    assert "normalize_mixed_source_settings_upgrade" not in updater
    print("  Loads and saves both derive; only loads upgrade.")
    return True


def test_retired_switches_are_purged_and_gone_from_defaults():
    """The dead switches are removed from stored settings and never re-seeded."""
    print("\nTesting retired switch removal...")
    functions = load_settings_functions()
    for key in RETIRED_KEYS:
        assert key in functions["RETIRED_SETTING_KEYS"], f"{key} is not retired"

    stored = {key: True for key in RETIRED_KEYS}
    stored["enable_enhanced_citations"] = True
    persisted, returned = simulate_settings_load(functions, stored, _defaults_for_simulation())
    for key in RETIRED_KEYS:
        assert key not in persisted
        assert key not in returned

    defaults = all_default_keys()
    for key in RETIRED_KEYS:
        assert key not in defaults, f"{key} is still seeded by get_settings()"
    print("  Retired switches are purged.")
    return True


def test_one_time_upgrade_respects_later_choices():
    """Relevance candidates turn on once; a later administrator choice is kept."""
    print("\nTesting the one-time mixed-source settings upgrade...")
    functions = load_settings_functions()
    defaults = _defaults_for_simulation()
    assert defaults["enable_mixed_source_relevance_candidates"] is True
    assert defaults["enable_mixed_source_analyze_all"] is False
    assert defaults["enable_mixed_source_development_telemetry"] is False
    assert defaults["mixed_source_settings_version"] == 0

    # A deployment from before the upgrade: the inert switch stored off, the switch that
    # did nothing visible stored on, no marker.
    stored = {
        "enable_enhanced_citations": True,
        "enable_mixed_source_relevance_candidates": False,
        "enable_mixed_source_analyze_all": True,
        "enable_mixed_source_development_telemetry": True,
    }
    persisted, _ = simulate_settings_load(functions, stored, defaults)
    assert persisted["enable_mixed_source_relevance_candidates"] is True
    assert persisted["enable_mixed_source_analyze_all"] is False
    assert persisted["mixed_source_settings_version"] == functions["MIXED_SOURCE_SETTINGS_VERSION"]
    # Telemetry is a real choice the upgrade leaves alone.
    assert persisted["enable_mixed_source_development_telemetry"] is True

    # The administrator turns relevance candidates off afterwards; it stays off.
    persisted["enable_mixed_source_relevance_candidates"] = False
    persisted["enable_mixed_source_analyze_all"] = True
    reloaded, _ = simulate_settings_load(functions, persisted, defaults)
    assert reloaded["enable_mixed_source_relevance_candidates"] is False
    assert reloaded["enable_mixed_source_analyze_all"] is True
    assert functions["normalize_mixed_source_settings_upgrade"](reloaded) is False

    # A brand-new deployment starts from the defaults and lands in the same place.
    fresh, _ = simulate_settings_load(functions, {}, defaults)
    assert fresh["enable_mixed_source_relevance_candidates"] is True
    assert fresh["enable_mixed_source_analyze_all"] is False
    assert all(fresh[key] is False for key in DERIVED_KEYS), "Enhanced Citations defaults off"

    # A malformed marker is treated as not yet upgraded rather than trusted.
    for marker in (True, "1", None, 0):
        candidate = {"mixed_source_settings_version": marker}
        assert functions["normalize_mixed_source_settings_upgrade"](candidate) is True
        assert candidate["mixed_source_settings_version"] == 1
    print("  The upgrade runs once and later choices stick.")
    return True


def test_admin_surfaces_describe_the_two_real_choices():
    """Both interfaces describe the two real switches where they belong."""
    print("\nTesting admin declarations...")
    fields_module = import_app_module("admin_settings_fields")
    declared = {}
    for section_id, field in fields_module.iter_fields():
        if field.get("key"):
            declared.setdefault(field["key"], (section_id, field))

    defaults = read_default_settings({
        "enable_mixed_source_relevance_candidates",
        "enable_mixed_source_development_telemetry",
    })
    expectations = {
        "enable_mixed_source_relevance_candidates": ("enhanced-citations-section", "citation"),
        "enable_mixed_source_development_telemetry": ("application-insights-section", "logging"),
    }
    for key, (section_id, pane_id) in expectations.items():
        assert key in declared, f"{key} is not declared"
        actual_section, field = declared[key]
        assert actual_section == section_id, f"{key} is declared under {actual_section}"
        assert field["type"] == "switch"
        assert field["default"] == defaults[key], f"{key} schema default differs from get_settings()"
        help_text = str(field.get("help") or "")
        assert len(help_text) > 120, f"{key} needs a description of what it does and costs"
        assert field["label"].lower() not in help_text.lower()
        pane = (PANES_DIR / f"{pane_id}.html").read_text(encoding="utf-8")
        assert f'name="{key}"' in pane, f"{key} has no classic control in {pane_id}.html"
        assert f'aria-describedby="{key}_help"' in pane
        assert f'id="{key}_help"' in pane

    relevance = declared["enable_mixed_source_relevance_candidates"][1]
    assert relevance["depends_on"] == {"key": "enable_enhanced_citations", "equals": True}

    suppressed = fields_module.SUPPRESSED_CAPABILITY_KEYS
    for key in DERIVED_KEYS:
        assert key in suppressed, f"{key} would be drawn as a switch that reverts"
        assert key not in declared
    assert "enable_enhanced_citations" in suppressed["enable_mixed_source_chat_search"]
    assert KILL_SWITCH in suppressed["enable_mixed_source_chat_search"]
    assert "enable_mixed_source_analyze_all" in suppressed
    assert "enable_mixed_source_analyze_all" not in declared

    citations_help = declared["enable_enhanced_citations"][1]["help"]
    assert "spreadsheet" in citations_help.lower(), (
        "Enhanced Citations must say it also turns on spreadsheet analysis"
    )
    print("  Both real choices are described where they belong.")
    return True


def test_classic_save_persists_both_switches():
    """The server-rendered form writes both keys, so neither interface drifts."""
    print("\nTesting the classic save handler...")
    source = ADMIN_ROUTE_FILE.read_text(encoding="utf-8")
    for key in (
        "enable_mixed_source_relevance_candidates",
        "enable_mixed_source_development_telemetry",
    ):
        assert f"'{key}': form_data.get('{key}') == 'on'" in source, f"{key} is not saved"
    print("  The classic save persists both switches.")
    return True


def test_compare_limitation_names_its_prerequisite():
    """Without spreadsheet processing, mixed Compare says what to enable."""
    print("\nTesting the cross-format Compare limitation message...")
    source = WORKFLOW_RUNNER_FILE.read_text(encoding="utf-8")
    assert "requires spreadsheet processing" in source
    assert "Enhanced Citations" in source
    assert "while cross-format Compare is disabled" not in source
    print("  The limitation names Enhanced Citations.")
    return True


if __name__ == "__main__":
    tests = [
        test_derived_behaviors_follow_enhanced_citations,
        test_subordinate_switches_need_their_parent,
        test_kill_switch_applies_at_read_time_only,
        test_loads_and_saves_both_derive,
        test_retired_switches_are_purged_and_gone_from_defaults,
        test_one_time_upgrade_respects_later_choices,
        test_admin_surfaces_describe_the_two_real_choices,
        test_classic_save_persists_both_switches,
        test_compare_limitation_names_its_prerequisite,
    ]
    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as error:
            print(f"FAILED {test.__name__}: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
