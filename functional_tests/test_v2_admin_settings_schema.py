#!/usr/bin/env python3
# test_v2_admin_settings_schema.py
"""
Functional test for the Admin Settings field schema shape.
Version: 0.261.039
Implemented in: 0.261.039

The V2 admin surface renders whatever ``admin_settings_fields.py`` declares. A
malformed entry does not raise anything server-side; it produces a control that
silently fails to draw, or draws without the options it needs. These checks make
a malformed entry a test failure instead.

A declared default is also checked against the application's own default. The
schema default is what the V2 surface shows for a key the settings document does
not contain, so a mismatch means the toggle an administrator reads disagrees with
the behaviour the application is actually applying.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_MODULE = REPO_ROOT / "application" / "single_app" / "functions_settings.py"

# The literal defaults in functions_settings.py. It is one of the modules
# ``app_stubs`` replaces, because it reaches config.py and a live Cosmos client, so
# the values are read from source the way scripts/build_docs_inventory.py reads them.
APP_DEFAULT_RE = re.compile(
    r"^\s*'(?P<key>[a-z0-9_]+)'\s*:\s*"
    r"(?P<value>True|False|'[^']*'|\[\]|-?\d+)\s*,",
    re.MULTILINE,
)

fields_module = import_app_module("admin_settings_fields")

# Properties every field type must carry beyond the common ones, because the
# renderer cannot draw the control without them.
REQUIRED_PROPERTIES_BY_TYPE = {
    "select": ("options", "default"),
    "checkbox_set": ("options", "default"),
    "range": ("min", "max", "step", "default"),
    "number": ("default",),
    "color": ("default",),
    "text": ("default",),
    "textarea": ("default",),
    "switch": ("default",),
    "link_list": ("item_fields", "default"),
    "image": ("upload_target", "accept", "version_key"),
    "component": ("component",),
}

EXPECTED_DEFAULT_TYPES = {
    "switch": bool,
    "text": str,
    "textarea": str,
    "select": str,
    "color": str,
    "range": int,
    "number": int,
    "checkbox_set": list,
    "link_list": list,
}


def test_field_types_are_known():
    """An unrecognised type would render as nothing at all."""
    print("Testing that every field declares a known type...")

    assert_app_version_at_least("0.261.039")

    unknown = [
        f"{section_id}.{field.get('key') or field.get('component')}: {field.get('type')!r}"
        for section_id, field in fields_module.iter_fields()
        if field.get("type") not in fields_module.FIELD_TYPES
    ]

    assert not unknown, (
        "These fields declare a type the V2 renderer does not implement:\n  "
        + "\n  ".join(unknown)
    )

    total = sum(1 for _ in fields_module.iter_fields())
    print(f"  All {total} field(s) use a known type.")
    return True


def test_fields_carry_required_properties():
    """A select without options, or a range without bounds, cannot be drawn."""
    print("\nTesting required properties per field type...")

    problems = []
    for section_id, field in fields_module.iter_fields():
        field_type = field.get("type")
        identity = (
            f"{section_id}."
            f"{field.get('key') or field.get('component') or field.get('status_source')}"
        )

        if not field.get("label"):
            problems.append(f"{identity}: missing label")

        # Everything that edits a value must name the settings key it edits. A
        # bespoke component owns its own persistence, and a status readout is
        # computed by the server rather than stored, so neither has one.
        if field_type not in ("component", "status") and not field.get("key"):
            problems.append(f"{identity}: missing key")

        # A readout with no source would render permanently blank.
        if field_type == "status" and not field.get("status_source"):
            problems.append(f"{identity}: missing status_source")

        for prop in REQUIRED_PROPERTIES_BY_TYPE.get(field_type, ()):
            if prop not in field:
                problems.append(f"{identity}: missing '{prop}' required by type {field_type}")

    assert not problems, (
        "These field definitions are incomplete:\n  " + "\n  ".join(problems)
    )

    print("  Every field carries the properties its type requires.")
    return True


def test_defaults_match_their_field_type():
    """A default of the wrong type makes the control start in an invalid state."""
    print("\nTesting default value types...")

    problems = []
    for section_id, field in fields_module.iter_fields():
        expected = EXPECTED_DEFAULT_TYPES.get(field.get("type"))
        if expected is None or "default" not in field:
            continue

        default = field["default"]
        # bool is a subclass of int, so a switch default must not satisfy range.
        if expected is int and isinstance(default, bool):
            problems.append(f"{section_id}.{field['key']}: bool default for a numeric field")
            continue
        if not isinstance(default, expected):
            problems.append(
                f"{section_id}.{field['key']}: default {default!r} is not {expected.__name__}"
            )

    assert not problems, (
        "These defaults do not match their field type:\n  " + "\n  ".join(problems)
    )

    print("  Every default matches its field type.")
    return True


def test_select_defaults_are_offered_as_options():
    """A default outside the option list leaves the control with no selection."""
    print("\nTesting that select defaults are selectable...")

    problems = []
    for section_id, field in fields_module.iter_fields():
        if field.get("type") != "select":
            continue
        values = [option["value"] for option in field["options"]]
        if field["default"] not in values:
            problems.append(
                f"{section_id}.{field['key']}: default {field['default']!r} not in {values}"
            )

    assert not problems, (
        "These selects default to a value they do not offer:\n  " + "\n  ".join(problems)
    )

    print("  Every select defaults to one of its own options.")
    return True


def test_setting_keys_are_unique():
    """The same key in two sections would render two controls fighting over one value."""
    print("\nTesting settings key uniqueness...")

    seen = {}
    duplicates = []
    for section_id, field in fields_module.iter_fields():
        key = field.get("key")
        if not key:
            continue
        if key in seen:
            duplicates.append(f"{key}: {seen[key]} and {section_id}")
        seen[key] = section_id

    assert not duplicates, (
        "These keys are declared in more than one section:\n  " + "\n  ".join(duplicates)
    )

    print(f"  All {len(seen)} declared key(s) are unique.")
    return True


def _walk_dependency_conditions(dependency, path="depends_on"):
    """Yield every leaf condition in a dependency tree, with a readable path.

    A dependency is either a single ``{key, equals}`` condition or an ``any_of`` /
    ``all_of`` composition of them, and the composed forms nest. Walking the tree
    is what lets these checks reach a condition buried two levels down, which is
    where a typo would otherwise sit undetected and hide a control forever.
    """
    if not isinstance(dependency, dict):
        return

    for combinator in ("any_of", "all_of"):
        if combinator in dependency:
            nested = dependency[combinator]
            if not isinstance(nested, list) or not nested:
                yield path, {"__error": f"{combinator} must be a non-empty list"}
                return
            for index, condition in enumerate(nested):
                yield from _walk_dependency_conditions(
                    condition, f"{path}.{combinator}[{index}]"
                )
            return

    yield path, dependency


def test_dependencies_reference_real_fields():
    """A dependency on an undeclared key would hide the field permanently."""
    print("\nTesting visibility dependencies...")

    declared = fields_module.get_declared_setting_keys()
    problems = []
    checked = 0

    for section_id, field in fields_module.iter_fields():
        depends_on = field.get("depends_on")
        if not depends_on:
            continue
        identity = f"{section_id}.{field.get('key') or field.get('component')}"

        for path, condition in _walk_dependency_conditions(depends_on):
            checked += 1

            if "__error" in condition:
                problems.append(f"{identity}: {path}: {condition['__error']}")
                continue
            if "key" not in condition:
                problems.append(f"{identity}: {path} has no key")
                continue
            if condition["key"] not in declared:
                problems.append(
                    f"{identity}: {path} depends on undeclared key {condition['key']!r}"
                )
            if field.get("key") == condition["key"]:
                problems.append(f"{identity}: {path} depends on itself")
            if "equals" not in condition and "not_equals" not in condition:
                problems.append(
                    f"{identity}: {path} states neither equals nor not_equals"
                )

    assert not problems, (
        "These visibility dependencies are broken:\n  " + "\n  ".join(problems)
    )

    print(f"  All {checked} dependency condition(s) resolve to declared fields.")
    return True


def test_connection_tests_read_declared_keys():
    """A test payload naming a key that does not exist would send an empty value."""
    print("\nTesting connection test payloads...")

    declared = fields_module.get_declared_setting_keys()
    problems = []
    checked = 0

    for section_id, field in fields_module.iter_fields():
        if field.get("component") != "connection-test":
            continue
        identity = f"{section_id}.connection-test"
        checked += 1

        if not field.get("test_type"):
            problems.append(f"{identity}: no test_type declared")

        payload = field.get("test_payload") or {}
        if not payload:
            problems.append(f"{identity}: no test_payload declared")

        for path, source in payload.items():
            if not isinstance(source, dict):
                problems.append(f"{identity}: {path} is not an object")
                continue
            if "key" not in source and "value" not in source:
                problems.append(f"{identity}: {path} names neither a key nor a value")
                continue
            key = source.get("key")
            if key and key not in declared:
                problems.append(f"{identity}: {path} reads undeclared key {key!r}")

            for condition_path, condition in _walk_dependency_conditions(
                source.get("when"), f"{path}.when"
            ):
                if "__error" in condition:
                    problems.append(f"{identity}: {condition_path}: {condition['__error']}")
                elif condition.get("key") not in declared:
                    problems.append(
                        f"{identity}: {condition_path} reads undeclared key "
                        f"{condition.get('key')!r}"
                    )

    assert not problems, (
        "These connection tests would send the wrong payload:\n  " + "\n  ".join(problems)
    )

    print(f"  {checked} connection test(s) read only declared keys.")
    return True


def test_option_values_are_unique_within_a_field():
    """Duplicate option values make a control's selection ambiguous."""
    print("\nTesting option value uniqueness...")

    problems = []
    for section_id, field in fields_module.iter_fields():
        options = field.get("options")
        if not options:
            continue
        values = [option["value"] for option in options]
        if len(values) != len(set(values)):
            problems.append(f"{section_id}.{field['key']}: duplicate values in {values}")
        if any(not option.get("label") for option in options):
            problems.append(f"{section_id}.{field['key']}: an option is missing a label")

    assert not problems, (
        "These option lists are malformed:\n  " + "\n  ".join(problems)
    )

    print("  Every option list has unique values and complete labels.")
    return True


def read_application_defaults():
    """Return the literal defaults the settings document is seeded with."""
    defaults = {}
    for match in APP_DEFAULT_RE.finditer(SETTINGS_MODULE.read_text(encoding="utf-8")):
        key, raw = match.group("key"), match.group("value")
        if key in defaults:
            # The first occurrence is the seeded default; later ones are migrations
            # and per-branch overrides.
            continue
        if raw == "True":
            defaults[key] = True
        elif raw == "False":
            defaults[key] = False
        elif raw == "[]":
            defaults[key] = []
        elif raw.lstrip("-").isdigit():
            defaults[key] = int(raw)
        else:
            defaults[key] = raw[1:-1]
    assert defaults, "No settings defaults were found; the extraction likely broke."
    return defaults


def test_declared_defaults_match_the_application():
    """A drifted default shows a toggle that disagrees with what the app does."""
    print("\nTesting declared defaults against functions_settings.py...")

    assert_app_version_at_least("0.261.047")

    app_defaults = read_application_defaults()

    mismatches = []
    compared = 0
    for section_id, field in fields_module.iter_fields():
        key = field.get("key")
        if not key or "default" not in field or key not in app_defaults:
            continue
        compared += 1
        if field["default"] != app_defaults[key]:
            mismatches.append(
                f"{section_id}.{key}: schema {field['default']!r} != "
                f"application {app_defaults[key]!r}"
            )

    assert not mismatches, (
        "These schema defaults disagree with the defaults the application seeds into "
        "the settings document, so the V2 admin surface would show the wrong state "
        "for a key the document does not contain yet:\n  " + "\n  ".join(mismatches)
    )

    assert compared, "No declared defaults were compared; the extraction likely broke."
    print(f"  All {compared} declared default(s) match the application.")
    return True


if __name__ == "__main__":
    tests = [
        test_field_types_are_known,
        test_fields_carry_required_properties,
        test_defaults_match_their_field_type,
        test_select_defaults_are_offered_as_options,
        test_setting_keys_are_unique,
        test_dependencies_reference_real_fields,
        test_connection_tests_read_declared_keys,
        test_option_values_are_unique_within_a_field,
        test_declared_defaults_match_the_application,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
