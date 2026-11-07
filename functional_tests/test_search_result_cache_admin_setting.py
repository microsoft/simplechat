# test_search_result_cache_admin_setting.py
#!/usr/bin/env python3
"""
Functional test for the search result cache admin setting.
Version: 0.261.263
Implemented in: 0.261.263

``enable_search_result_caching`` had no declared field, so the V2 admin
surface's ``enable_*`` fallback scan drew it as a bare switch labelled from its
key. The scan matched "search" in both Web Search and Azure AI Search, and Web
Search won the tie, so a cache that sits in front of the workspace indexes was
filed beside the setting that reaches the public internet. Its lifetime,
``search_cache_ttl_seconds``, was read at runtime but editable nowhere.

This test ensures both settings are declared together under Azure AI Search,
explain what they do, start from the same defaults the application applies,
save within safe bounds, and are recorded as V2-only rather than appearing in
one interface by accident.
"""

import ast
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
SETTINGS_MODULE = APP_ROOT / "functions_settings.py"
CACHE_MODULE = APP_ROOT / "utils_cache.py"
TEMPLATES_ROOT = APP_ROOT / "templates"

SECTION_ID = "azure-ai-search-section"
GROUP_ID = "search-result-cache"
SWITCH_KEY = "enable_search_result_caching"
LIFETIME_KEY = "search_cache_ttl_seconds"
EXPECTED_DEFAULTS = {SWITCH_KEY: True, LIFETIME_KEY: 300}

APP_DEFAULT_RE = re.compile(
    r"^\s*'(?P<key>[a-z0-9_]+)'\s*:\s*(?P<value>True|False|-?\d+)\s*,",
    re.MULTILINE,
)

fields_module = import_app_module("admin_settings_fields")
normalize = fields_module.normalize_admin_settings_updates


def section_fields(section_id):
    return [
        field
        for declared_section, field in fields_module.iter_fields()
        if declared_section == section_id
    ]


def group_id_of(field):
    group = field.get("group")
    if isinstance(group, str):
        return group
    return (group or {}).get("id")


def declared_field(key):
    matches = [
        (section_id, field)
        for section_id, field in fields_module.iter_fields()
        if field.get("key") == key
    ]
    assert len(matches) == 1, f"{key} must be declared exactly once, found {len(matches)}."
    return matches[0]


def read_runtime_fallbacks():
    """Return the defaults ``utils_cache.get_cache_settings`` applies.

    ``utils_cache`` imports ``config`` and a live Cosmos client, so the function
    is read from source rather than imported.
    """
    tree = ast.parse(CACHE_MODULE.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "get_cache_settings"
    )

    lookups = {}
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and len(node.args) == 2
            and all(isinstance(arg, ast.Constant) for arg in node.args)
        ):
            lookups[node.args[0].value] = node.args[1].value

    handler_returns = [
        tuple(element.value for element in node.value.elts)
        for handler in ast.walk(function)
        if isinstance(handler, ast.ExceptHandler)
        for node in ast.walk(handler)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Tuple)
        and all(isinstance(element, ast.Constant) for element in node.value.elts)
    ]
    return lookups, handler_returns


def test_both_settings_are_declared_together_under_azure_ai_search():
    """Declaring the key is what takes it out of the fallback scan's guess."""
    print("Testing where the search result cache is declared...")

    assert_app_version_at_least("0.261.263")

    for key in (SWITCH_KEY, LIFETIME_KEY):
        section_id, field = declared_field(key)
        assert section_id == SECTION_ID, f"{key} is declared under {section_id!r}"
        assert group_id_of(field) == GROUP_ID, f"{key} is not in the {GROUP_ID!r} group"

    declared = fields_module.get_declared_setting_keys()
    suppressed = set(fields_module.get_suppressed_capability_keys())
    assert SWITCH_KEY in declared, "The fallback scan would still guess a home for the switch."
    assert SWITCH_KEY not in suppressed, "The switch is an editable setting, not a suppressed one."

    print(f"  Both keys are declared under {SECTION_ID} in the {GROUP_ID} group.")
    return True


def test_the_connection_stays_first_and_the_cache_follows_it():
    """An administrator configuring search needs the endpoint before the tuning."""
    print("\nTesting the Azure AI Search field order...")

    fields = section_fields(SECTION_ID)
    groups = [group_id_of(field) for field in fields]
    keys = [field.get("key") or field.get("component") for field in fields]

    connection = [index for index, group in enumerate(groups) if group == "connection"]
    cache = [index for index, group in enumerate(groups) if group == GROUP_ID]
    assert connection == list(range(len(connection))), (
        f"The connection group is no longer contiguous at the top.\n  groups: {groups}"
    )
    assert cache == list(range(len(connection), len(connection) + 2)), (
        f"The cache group should directly follow the connection group.\n  groups: {groups}"
    )
    assert keys[cache[0]] == SWITCH_KEY and keys[cache[1]] == LIFETIME_KEY, (
        f"The switch should lead its lifetime.\n  order: {keys}"
    )

    print("  Connection first, then the cache switch, then its lifetime.")
    return True


def test_each_control_explains_itself():
    """A bare key-named switch is what this change replaces."""
    print("\nTesting labels, help and the group description...")

    _section_id, switch = declared_field(SWITCH_KEY)
    _section_id, lifetime = declared_field(LIFETIME_KEY)

    assert switch["type"] == "switch", switch["type"]
    assert switch["label"] == "Cache workspace search results", switch["label"]
    assert lifetime["type"] == "number", lifetime["type"]
    assert lifetime["label"] == "Cache lifetime (seconds)", lifetime["label"]

    group = switch["group"]
    assert isinstance(group, dict), "The group's first field must declare it in full."
    assert group.get("variant") == "behavior", group
    assert group.get("label") == "Search result cache", group

    for owner, text in (
        ("switch help", switch.get("help")),
        ("lifetime help", lifetime.get("help")),
        ("group help", group.get("help")),
    ):
        assert text and len(text.split()) >= 20, f"The {owner} is missing or too thin: {text!r}"

    print("  Every control carries a real explanation.")
    return True


def test_the_lifetime_is_bounded_and_only_shown_while_caching_is_on():
    """A lifetime under a switched-off cache describes nothing."""
    print("\nTesting the lifetime field's bounds and visibility...")

    _section_id, lifetime = declared_field(LIFETIME_KEY)
    assert lifetime["min"] == 60 and lifetime["max"] == 3600, lifetime
    assert lifetime["depends_on"] == {"key": SWITCH_KEY, "equals": True}, lifetime["depends_on"]

    shown = fields_module.field_dependencies_are_satisfied(lifetime, {SWITCH_KEY: True})
    hidden = fields_module.field_dependencies_are_satisfied(lifetime, {SWITCH_KEY: False})
    assert shown is True and hidden is False, (shown, hidden)

    print("  The lifetime is 60 to 3,600 seconds and follows the switch.")
    return True


def test_declared_defaults_match_what_the_application_applies():
    """The admin page must show the state the cache is actually in."""
    print("\nTesting defaults against functions_settings.py and utils_cache.py...")

    source = SETTINGS_MODULE.read_text(encoding="utf-8")
    app_defaults = {
        match.group("key"): ast.literal_eval(match.group("value"))
        for match in APP_DEFAULT_RE.finditer(source)
        if match.group("key") in EXPECTED_DEFAULTS
    }
    assert app_defaults == EXPECTED_DEFAULTS, app_defaults

    lookups, handler_returns = read_runtime_fallbacks()
    assert lookups == EXPECTED_DEFAULTS, lookups
    assert handler_returns == [(True, 300)], handler_returns

    for key, expected in EXPECTED_DEFAULTS.items():
        _section_id, field = declared_field(key)
        assert field["default"] == expected, (key, field["default"])

    print("  On, with a 300 second lifetime, in all three places.")
    return True


def test_saves_are_coerced_and_clamped():
    """A lifetime of zero or hours would make the cache useless or stale."""
    print("\nTesting PATCH normalization...")

    for raw, expected in ((5, 60), (99999, 3600), ("600", 600), (300, 300)):
        result, errors, _ = normalize({LIFETIME_KEY: raw})
        assert not errors, errors
        assert result[LIFETIME_KEY] == expected, (raw, result)

    _result, errors, _ = normalize({LIFETIME_KEY: "five minutes"})
    assert LIFETIME_KEY in errors, errors

    for raw, expected in ((False, False), ("false", False), ("on", True)):
        result, errors, _ = normalize({SWITCH_KEY: raw})
        assert not errors, errors
        assert result[SWITCH_KEY] is expected, (raw, result)

    print("  The lifetime clamps to its bounds and the switch saves a real boolean.")
    return True


def test_the_v2_only_record_is_explained_and_still_true():
    """A V2-only field must say why, and must not quietly gain a classic control."""
    print("\nTesting the V2-only record...")

    for key in (SWITCH_KEY, LIFETIME_KEY):
        reason = fields_module.V2_ONLY_FIELDS.get(key)
        assert reason and reason.strip(), f"{key} has no V2_ONLY_FIELDS reason."

    templates = [
        TEMPLATES_ROOT / "admin_settings.html",
        *TEMPLATES_ROOT.joinpath("admin").rglob("*.html"),
    ]
    offenders = []
    for path in templates:
        markup = path.read_text(encoding="utf-8")
        for key in (SWITCH_KEY, LIFETIME_KEY):
            if re.search(rf"\bname=[\"']{key}[\"']", markup):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {key}")

    assert not offenders, (
        "A classic form now submits these keys. Wire the classic save handler and "
        "remove the V2_ONLY_FIELDS entries:\n  " + "\n  ".join(offenders)
    )

    print("  Both keys are recorded as V2-only, and no classic form submits them.")
    return True


if __name__ == "__main__":
    tests = [
        test_both_settings_are_declared_together_under_azure_ai_search,
        test_the_connection_stays_first_and_the_cache_follows_it,
        test_each_control_explains_itself,
        test_the_lifetime_is_bounded_and_only_shown_while_caching_is_on,
        test_declared_defaults_match_what_the_application_applies,
        test_saves_are_coerced_and_clamped,
        test_the_v2_only_record_is_explained_and_still_true,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
