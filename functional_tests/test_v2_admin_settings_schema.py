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

import ast
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
    "secret": ("default",),
    "switch": ("default",),
    "link_list": ("item_fields", "default"),
    # An id_list resolves names through a search endpoint, so the renderer cannot
    # draw its picker without knowing where to search and what the response holds.
    "id_list": (
        "default",
        "id_kind",
        "search_endpoint",
        "results_key",
        "item_noun",
        "item_noun_plural",
    ),
    "group_picker": ("default", "search_endpoint"),
    "image": ("upload_target", "accept", "version_key"),
    "component": ("component",),
}

EXPECTED_DEFAULT_TYPES = {
    "switch": bool,
    "text": str,
    "textarea": str,
    "secret": str,
    "select": str,
    "color": str,
    "range": int,
    "number": int,
    "checkbox_set": list,
    "link_list": list,
    "id_list": list,
    "group_picker": list,
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
        if not field.get("depends_on"):
            continue
        identity = f"{section_id}.{field.get('key') or field.get('component')}"

        # A field may carry one condition or a list of them, so both shapes are read
        # through the schema's own iterator rather than assumed here.
        for condition in fields_module.iter_field_dependencies(field):
            checked += 1

            if "key" not in condition:
                problems.append(f"{identity}: depends_on has no key")
                continue
            if condition["key"] not in declared:
                problems.append(
                    f"{identity}: depends on undeclared key {condition['key']!r}"
                )
            if field.get("key") == condition["key"]:
                problems.append(f"{identity}: depends on itself")

    assert not problems, (
        "These visibility dependencies are broken:\n  " + "\n  ".join(problems)
    )

    print(f"  All {checked} dependency reference(s) resolve to declared fields.")
    return True


def test_string_dependencies_name_an_offered_option():
    """A string condition that no option produces would hide the field forever."""
    print("\nTesting string visibility dependencies against their select options...")

    fields_by_key = {
        field["key"]: field
        for _section_id, field in fields_module.iter_fields()
        if field.get("key")
    }

    problems = []
    checked = 0
    for section_id, field in fields_module.iter_fields():
        identity = f"{section_id}.{field.get('key') or field.get('component')}"
        for depends_on in fields_module.iter_field_dependencies(field):
            expected = depends_on.get("equals")
            if not isinstance(expected, str):
                continue

            checked += 1
            gate = fields_by_key.get(depends_on.get("key"))

            if gate is None:
                problems.append(f"{identity}: gate field is not declared")
                continue
            if gate.get("type") != "select":
                problems.append(
                    f"{identity}: gate {gate['key']!r} is a {gate.get('type')!r}, but a "
                    "string condition only makes sense against a select"
                )
                continue

            values = [option["value"] for option in gate.get("options", [])]
            if expected not in values:
                problems.append(
                    f"{identity}: waits for {gate['key']}=={expected!r}, which is not "
                    f"one of {values}"
                )

    assert not problems, (
        "These string dependencies can never be satisfied, so the field would "
        "never render:\n  " + "\n  ".join(problems)
    )

    assert checked, (
        "No string dependencies were compared; the Enhanced Citations storage "
        "credentials should each be gated on an authentication type."
    )
    print(f"  All {checked} string dependency condition(s) are reachable.")
    return True


def test_gated_fields_inherit_their_gate_s_own_conditions():
    """The renderer evaluates each field's conditions alone, not recursively.

    So a field gated on a sibling is visible whenever that sibling's *value* matches,
    even when the sibling is itself hidden. Gating the Enhanced Citations connection
    string on the authentication type alone left it on screen while Enhanced Citations
    was off, because the authentication type defaults to ``key`` whether the capability
    is on or not -- offering a credential field for a disabled feature.

    A field must therefore repeat every condition its gate carries.
    """
    print("\nTesting that gated fields inherit their gate's conditions...")

    fields_by_key = {
        field["key"]: field
        for _section_id, field in fields_module.iter_fields()
        if field.get("key")
    }

    def condition_set(field, seen=None):
        """Every (key, equals) a field declares, plus everything its gates declare."""
        seen = seen if seen is not None else set()
        for condition in fields_module.iter_field_dependencies(field):
            key = condition.get("key")
            entry = (key, condition.get("equals", True))
            if entry in seen:
                continue
            seen.add(entry)
            parent = fields_by_key.get(key)
            if parent is not None:
                condition_set(parent, seen)
        return seen

    problems = []
    checked = 0
    for section_id, field in fields_module.iter_fields():
        own = {
            (condition.get("key"), condition.get("equals", True))
            for condition in fields_module.iter_field_dependencies(field)
        }
        if not own:
            continue

        checked += 1
        inherited = condition_set(field)
        missing = sorted(
            f"{key}=={value!r}" for key, value in inherited - own
        )
        if missing:
            problems.append(
                f"{section_id}.{field.get('key') or field.get('component')}: also needs "
                + ", ".join(missing)
            )

    assert not problems, (
        "These fields are gated on another field that is itself gated, but do not "
        "repeat its conditions. Because visibility is evaluated per field rather than "
        "recursively, they stay on screen when their gate is hidden:\n  "
        + "\n  ".join(problems)
    )

    assert checked, "No gated fields were compared; the extraction likely broke."
    print(f"  All {checked} gated field(s) carry their gate's conditions.")
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
            # Parsed rather than unquoted, so escape sequences become the characters
            # they stand for. A default holding a newline would otherwise compare as
            # the two characters backslash-n and never match the schema.
            try:
                defaults[key] = ast.literal_eval(raw)
            except (SyntaxError, ValueError):
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
        test_string_dependencies_name_an_offered_option,
        test_gated_fields_inherit_their_gate_s_own_conditions,
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
