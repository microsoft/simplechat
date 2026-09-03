#!/usr/bin/env python3
# test_v2_admin_settings_schema.py
"""
Functional test for the Admin Settings field schema shape.
Version: 0.261.038
Implemented in: 0.261.038

The V2 admin surface renders whatever ``admin_settings_fields.py`` declares. A
malformed entry does not raise anything server-side; it produces a control that
silently fails to draw, or draws without the options it needs. These checks make
a malformed entry a test failure instead.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least


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

    assert_app_version_at_least("0.261.038")

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
        identity = f"{section_id}.{field.get('key') or field.get('component')}"

        if not field.get("label"):
            problems.append(f"{identity}: missing label")

        # Everything except a bespoke component must name the settings key it edits.
        if field_type != "component" and not field.get("key"):
            problems.append(f"{identity}: missing key")

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
        checked += 1
        identity = f"{section_id}.{field.get('key') or field.get('component')}"

        if "key" not in depends_on:
            problems.append(f"{identity}: depends_on has no key")
            continue
        if depends_on["key"] not in declared:
            problems.append(f"{identity}: depends on undeclared key {depends_on['key']!r}")
        if field.get("key") == depends_on["key"]:
            problems.append(f"{identity}: depends on itself")

    assert not problems, (
        "These visibility dependencies are broken:\n  " + "\n  ".join(problems)
    )

    print(f"  All {checked} dependency reference(s) resolve to declared fields.")
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


if __name__ == "__main__":
    tests = [
        test_field_types_are_known,
        test_fields_carry_required_properties,
        test_defaults_match_their_field_type,
        test_select_defaults_are_offered_as_options,
        test_setting_keys_are_unique,
        test_dependencies_reference_real_fields,
        test_option_values_are_unique_within_a_field,
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
