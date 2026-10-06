#!/usr/bin/env python3
# test_v2_admin_operations_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings Operations group.
Version: 0.261.260
Implemented in: 0.261.260

The V2 React admin surface renders from ``admin_settings_fields.py`` rather than
from the server-rendered panes, so the two can drift apart silently: a field added
to a V1 pane simply never appears in V2, and nothing fails.

Operations was almost entirely undescribed. The fallback ``enable_*`` scan drew
three unexplained switches under Debug Logging -- one of them Application
Insights, which left its own section empty and therefore not rendered at all --
and Automatic Data Refresh, whose keys are not named ``enable_*``, did not appear
in V2 in any form. The auto-turnoff timers, the stored-log cleanup and the setup
guides existed on the server-rendered page only.

This test does for Operations what ``test_v2_admin_security_parity.py`` does for
Security: it reads the two panes that make up the group and requires every form
field V1 submits to be claimed by the schema, with matching options, bounds and
visibility chains. It also pins the parts that are particular to this group: the
values the server calculates rather than accepts, the guides each section header
offers, and the descriptors the bespoke readouts depend on.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
PANES_DIR = APP_ROOT / "templates" / "admin" / "_panes"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"
FIELDS_TSX = V2_SRC / "components" / "admin" / "fields.tsx"
GUIDE_REGISTRY_TSX = V2_SRC / "components" / "admin" / "guides" / "sectionGuides.tsx"
ROUTE_V2 = APP_ROOT / "route_backend_v2.py"
OPERATIONS_DOCS = REPO_ROOT / "docs" / "admin" / "operations.md"
DOCS_SITE_BASE = "https://microsoft.github.io/simplechat"

OPERATIONS_GROUP_ID = "operations"

# The tabs that make up the Operations group, and the sections each contributes.
OPERATIONS_PANES = {
    "control-center-config": (
        "control-center-auto-refresh-section",
        "control-center-overview-section",
    ),
    "logging": (
        "application-insights-section",
        "debug-logging-section",
        "file-processing-logs-section",
        "health-check-section",
        "swagger-section",
    ),
}

# Each of these is nested inside an enclosing block in the server-rendered pane, so
# V2 has to carry every gate on the field itself to hide it in the same situations.
EXPECTED_DEPENDENCY_CHAINS = {
    "control_center_auto_refresh_time": {("control_center_auto_refresh_enabled", True)},
    "control_center_auto_refresh_timezone": {("control_center_auto_refresh_enabled", True)},
    "debug_logging_timer_enabled": {("enable_debug_logging", True)},
    "debug_timer_value": {
        ("enable_debug_logging", True),
        ("debug_logging_timer_enabled", True),
    },
    "debug_timer_unit": {
        ("enable_debug_logging", True),
        ("debug_logging_timer_enabled", True),
    },
    "file_processing_logs_timer_enabled": {("enable_file_processing_logs", True)},
    "file_timer_value": {
        ("enable_file_processing_logs", True),
        ("file_processing_logs_timer_enabled", True),
    },
    "file_timer_unit": {
        ("enable_file_processing_logs", True),
        ("file_processing_logs_timer_enabled", True),
    },
}

# Values the server works out on save. Each must be refused when submitted, or a
# save could move a scheduled refresh or extend a debug session without touching
# the controls that are meant to.
DERIVED_KEYS = (
    "control_center_auto_refresh_next_run",
    "control_center_auto_refresh_hour",
    "control_center_auto_refresh_minute",
    "debug_logging_turnoff_time",
    "file_processing_logs_turnoff_time",
)

# Runtime flags the Operations readouts read. Sent by ``_build_runtime_flags``.
OPERATIONS_RUNTIME_FLAGS = {
    "appinsights_connection_configured",
    "appinsights_global_logging_active",
    "swagger_routes_registered",
}

ENDPOINT_ACCESS_VALUES = {"protected", "public", "signed_in"}

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")
OPTION_RE = re.compile(r'<option value="([^"]*)"')
SELECT_BLOCK_RE = re.compile(
    r'<select[^>]*\sname="(?P<name>[^"]+)"(?P<body>.*?)</select>',
    re.DOTALL,
)
NUMBER_BLOCK_RE = re.compile(r'<input[^>]*type="number"(?P<attrs>[^>]*)>', re.DOTALL)
ATTR_RE = re.compile(r'(\w[\w-]*)="([^"]*)"')
ROUTE_DECORATOR_RE = re.compile(r"""\.route\(\s*['"]([^'"]+)['"]""")

fields_module = import_app_module("admin_settings_fields")


def read_pane(pane_id):
    """Return the raw markup for one Admin Settings pane."""
    pane_path = PANES_DIR / f"{pane_id}.html"
    assert pane_path.is_file(), f"Missing Admin Settings pane: {pane_path}"
    return pane_path.read_text(encoding="utf-8")


def collect_pane_field_names(markup):
    """Return literal form field names submitted by a pane."""
    return {name for name in FIELD_NAME_RE.findall(markup) if not JINJA_RE.search(name)}


def operations_section_ids():
    return {section_id for sections in OPERATIONS_PANES.values() for section_id in sections}


def operations_fields():
    """Return ``(section_id, field)`` for every field the Operations sections declare."""
    section_ids = operations_section_ids()
    return [
        (section_id, field)
        for section_id, field in fields_module.iter_fields()
        if section_id in section_ids
    ]


def operations_schema_fields():
    """Return ``{key: field}`` for every keyed field the Operations sections declare."""
    return {field["key"]: field for _section_id, field in operations_fields() if field.get("key")}


def dependency_pairs(field):
    """Return the ``(key, equals)`` pairs a field's ``depends_on`` carries."""
    return {
        (condition["key"], condition.get("equals", True))
        for condition in fields_module.iter_field_dependencies(field)
    }


def test_operations_panes_match_navigation():
    """The panes this test reads must be the ones ADMIN_NAV puts in the group."""
    print("Testing Operations pane list against ADMIN_NAV...")

    assert_app_version_at_least("0.261.260")

    group = next((g for g in ADMIN_NAV if g["id"] == OPERATIONS_GROUP_ID), None)
    assert group, "ADMIN_NAV no longer defines an 'operations' group."

    nav_tabs = {tab["id"]: tuple(s["id"] for s in tab["sections"]) for tab in group["tabs"]}
    assert nav_tabs == OPERATIONS_PANES, (
        "The Operations group's tabs or sections changed. Update OPERATIONS_PANES and "
        f"the schema together.\n  ADMIN_NAV: {nav_tabs}\n  test: {OPERATIONS_PANES}"
    )

    print(f"  {len(nav_tabs)} tab(s) and their sections match ADMIN_NAV.")


def test_every_operations_section_is_described():
    """A section with nothing declared falls back to guesses, or renders not at all."""
    print("\nTesting that every Operations section declares its controls...")

    schema = fields_module.get_admin_settings_fields()
    empty = sorted(section_id for section_id in operations_section_ids() if not schema.get(section_id))
    assert not empty, (
        "These Operations sections declare no fields, so V2 draws them from the "
        "enable_* scan or skips them entirely:\n  " + "\n  ".join(empty)
    )

    print(f"  All {len(operations_section_ids())} section(s) are described.")


def test_every_v1_operations_field_is_claimed():
    """A field only V1 has is a setting the V2 surface cannot reach."""
    print("\nTesting that every V1 Operations field is claimed by the schema...")

    claimed = fields_module.get_legacy_field_names()
    excused = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    unclaimed = []
    total = 0
    for pane_id in OPERATIONS_PANES:
        for name in sorted(collect_pane_field_names(read_pane(pane_id))):
            total += 1
            if name not in claimed and name not in excused:
                unclaimed.append(f"{pane_id}.html: {name}")

    assert not unclaimed, (
        "These fields exist in the server-rendered Operations panes but nothing in "
        "admin_settings_fields.py claims them. Declare each one, or record why it has "
        "no V2 equivalent in LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT:\n  "
        + "\n  ".join(unclaimed)
    )
    assert total >= 17, f"Only {total} V1 field(s) were found; the pane extraction likely broke."

    print(f"  All {total} V1 Operations field(s) are claimed by the schema.")


def test_schema_does_not_invent_operations_fields():
    """A V2 field with no V1 counterpart writes a setting nothing else reads."""
    print("\nTesting that the schema does not invent Operations fields...")

    pane_fields = set()
    for pane_id in OPERATIONS_PANES:
        pane_fields |= collect_pane_field_names(read_pane(pane_id))

    invented = []
    for key, field in sorted(operations_schema_fields().items()):
        legacy_names = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
        if any(name in pane_fields for name in legacy_names):
            continue
        if key in fields_module.V2_ONLY_FIELDS:
            continue
        invented.append(f"{key} (type {field.get('type')})")

    assert not invented, (
        "These schema fields have no counterpart in the server-rendered Operations "
        "panes. Remove them, or record the reason in V2_ONLY_FIELDS:\n  "
        + "\n  ".join(invented)
    )
    assert fields_module.V2_ONLY_FIELDS.get("enable_dai_debug"), (
        "enable_dai_debug has no V1 control; its V2 declaration must say why it exists."
    )

    print("  Every Operations schema field maps back to a V1 field or a recorded reason.")


def test_select_options_match_v1():
    """A select offering different values in each interface stores different data."""
    print("\nTesting Operations select option values against V1...")

    schema_fields = operations_schema_fields()

    checked = 0
    mismatches = []
    for pane_id in OPERATIONS_PANES:
        for match in SELECT_BLOCK_RE.finditer(read_pane(pane_id)):
            name = match.group("name")
            field = schema_fields.get(name)
            if not field or field.get("type") != "select":
                continue
            checked += 1
            v1_values = set(OPTION_RE.findall(match.group("body")))
            v2_values = {option["value"] for option in field.get("options", [])}
            if v1_values != v2_values:
                mismatches.append(
                    f"{name}: V1 offers {sorted(v1_values)}, schema offers {sorted(v2_values)}"
                )

    assert not mismatches, "Select values differ:\n  " + "\n  ".join(mismatches)
    assert checked == 2, f"Expected the two timer unit selects, compared {checked}."

    print(f"  {checked} select(s) offer identical values in both interfaces.")


def test_number_bounds_match_v1():
    """A looser bound in one interface lets a value through the other refuses."""
    print("\nTesting Operations number bounds against V1...")

    schema_fields = operations_schema_fields()

    checked = 0
    mismatches = []
    for pane_id in OPERATIONS_PANES:
        for match in NUMBER_BLOCK_RE.finditer(read_pane(pane_id)):
            attrs = dict(ATTR_RE.findall(match.group("attrs")))
            field = schema_fields.get(attrs.get("name"))
            if not field or field.get("type") != "number":
                continue
            checked += 1
            for bound in ("min", "max"):
                if bound in attrs and int(attrs[bound]) != field.get(bound):
                    mismatches.append(
                        f"{attrs['name']}: V1 {bound}={attrs[bound]}, schema {bound}={field.get(bound)}"
                    )

    assert not mismatches, "Number bounds differ:\n  " + "\n  ".join(mismatches)
    assert checked == 2, f"Expected the two timer durations, compared {checked}."

    print(f"  {checked} number control(s) share identical bounds.")


def test_dependency_chains_are_complete():
    """A flat list has to carry every gate V1 expressed as a nested div."""
    print("\nTesting Operations field dependency chains...")

    schema_fields = operations_schema_fields()

    problems = []
    for key, expected in EXPECTED_DEPENDENCY_CHAINS.items():
        field = schema_fields.get(key)
        if field is None:
            problems.append(f"{key}: not declared in an Operations section")
            continue
        actual = dependency_pairs(field)
        if actual != expected:
            problems.append(f"{key}: expected {sorted(expected)}, found {sorted(actual)}")

    assert not problems, "Incomplete dependency chains:\n  " + "\n  ".join(problems)

    print(f"  All {len(EXPECTED_DEPENDENCY_CHAINS)} dependency chain(s) are complete.")


def test_calculated_values_are_refused():
    """The server works these out; a browser must not be able to set them."""
    print("\nTesting that calculated Operations values cannot be submitted...")

    normalize = fields_module.normalize_admin_settings_updates
    for key in DERIVED_KEYS:
        normalized, errors, _warnings = normalize({key: "2030-01-01T00:00:00+00:00"}, {})
        assert key in errors, f"{key} was accepted from the browser."
        assert key not in normalized, f"{key} reached the normalized update."

    print(f"  All {len(DERIVED_KEYS)} calculated value(s) are refused.")


def test_input_types_have_renderers():
    """A time or timezone field the renderer does not know draws a plain text box."""
    print("\nTesting Operations input types...")

    used = {
        field.get("input_type")
        for _section_id, field in operations_fields()
        if field.get("input_type")
    }
    assert used == {"time", "timezone"}, f"Unexpected input types: {sorted(used)}"
    assert used <= set(fields_module.TEXT_INPUT_TYPES)

    fields_source = FIELDS_TSX.read_text(encoding="utf-8")
    assert "field.input_type === 'timezone'" in fields_source, "No timezone control in fields.tsx."
    assert "field.input_type === 'time'" in fields_source, "No time handling in fields.tsx."

    print("  time and timezone inputs are declared and rendered.")


def test_readout_descriptors_name_real_things():
    """A readout pointed at a missing key or flag would report a state nobody set."""
    print("\nTesting Operations readout descriptors...")

    declared = fields_module.get_declared_setting_keys()
    route_source = ROUTE_V2.read_text(encoding="utf-8")
    route_paths = set()
    for path in APP_ROOT.glob("*.py"):
        route_paths |= set(ROUTE_DECORATOR_RE.findall(path.read_text(encoding="utf-8")))
    nav_sections = {section["id"] for group in ADMIN_NAV for tab in group["tabs"] for section in tab["sections"]}

    problems = []
    components = 0
    for section_id, field in operations_fields():
        component = field.get("component")
        identity = f"{section_id}.{component or field.get('key')}"

        if component == "restart-status":
            components += 1
            if field.get("watches") not in declared:
                problems.append(f"{identity}: watches undeclared key {field.get('watches')!r}")
            for flag_key in ("runtime_flag", "runtime_requires"):
                flag = field.get(flag_key)
                if flag is None and flag_key == "runtime_requires":
                    continue
                if flag not in OPERATIONS_RUNTIME_FLAGS:
                    problems.append(f"{identity}: unknown {flag_key} {flag!r}")

        if component == "logging-timer-status":
            components += 1
            timer_keys = field.get("timer_keys") or {}
            if timer_keys not in fields_module.LOGGING_TIMERS.values():
                problems.append(f"{identity}: timer_keys do not match LOGGING_TIMERS")
            for role, key in timer_keys.items():
                if role != "turnoff_key" and key not in declared:
                    problems.append(f"{identity}: {role} {key!r} is not declared")

        if component == "endpoint-links":
            components += 1
            for endpoint in field.get("endpoints") or []:
                path = endpoint.get("path")
                if path not in route_paths:
                    problems.append(f"{identity}: no route serves {path!r}")
                if endpoint.get("access") not in ENDPOINT_ACCESS_VALUES:
                    problems.append(f"{identity}: {path} has access {endpoint.get('access')!r}")
                gate = endpoint.get("gate_key")
                if gate and gate not in declared:
                    problems.append(f"{identity}: {path} gates on undeclared {gate!r}")
                flag = endpoint.get("runtime_flag")
                if flag and flag not in OPERATIONS_RUNTIME_FLAGS:
                    problems.append(f"{identity}: {path} reads unknown flag {flag!r}")
                if not gate and not flag:
                    problems.append(f"{identity}: {path} says nothing about when it is live")

        related = field.get("related_section")
        if related and related.get("section_id") not in nav_sections:
            problems.append(f"{identity}: related section {related.get('section_id')!r} is not in ADMIN_NAV")

    for flag in OPERATIONS_RUNTIME_FLAGS:
        if f'"{flag}":' not in route_source:
            problems.append(f"route_backend_v2.py does not send the runtime flag {flag!r}")
    if 'readouts["appinsights_connection"]' not in route_source:
        problems.append("route_backend_v2.py does not build the appinsights_connection readout")

    assert not problems, "Readout descriptors are wrong:\n  " + "\n  ".join(problems)
    assert components >= 6, f"Only {components} Operations readout(s) were found."

    print(f"  {components} readout(s) point at declared keys, real routes and sent flags.")


def test_section_guides_are_declared_registered_and_documented():
    """A guide button with nothing behind it, or a dead docs link, is worse than none."""
    print("\nTesting the Operations section guides...")

    guides = fields_module.get_admin_section_guides()
    expected_sections = {
        "control-center-overview-section",
        "health-check-section",
        "swagger-section",
    }
    assert expected_sections <= set(guides), (
        f"Operations guides missing for: {sorted(expected_sections - set(guides))}"
    )

    registry = GUIDE_REGISTRY_TSX.read_text(encoding="utf-8")
    registered = set(re.findall(r"^\s{4}'([a-z]+(?:-[a-z]+)*)':\s*\{", registry, re.MULTILINE))
    docs_source = OPERATIONS_DOCS.read_text(encoding="utf-8")
    nav_sections = {section["id"] for group in ADMIN_NAV for tab in group["tabs"] for section in tab["sections"]}

    problems = []
    for section_id, guide in guides.items():
        if section_id not in nav_sections:
            problems.append(f"{section_id}: not a section in ADMIN_NAV")
        if not guide.get("label"):
            problems.append(f"{section_id}: guide has no button label")
        if guide.get("id") not in registered:
            problems.append(f"{section_id}: guide {guide.get('id')!r} is not in sectionGuides.tsx")
        docs_url = guide.get("docs_url", "")
        if not docs_url.startswith(f"{DOCS_SITE_BASE}/admin/operations/#"):
            problems.append(f"{section_id}: docs_url {docs_url!r} is not an Operations page anchor")
            continue
        anchor = docs_url.rsplit("#", 1)[1]
        if f"{{#{anchor}}}" not in docs_source:
            problems.append(f"{section_id}: docs/admin/operations.md has no {{#{anchor}}} heading")

    assert not problems, "Section guides are wrong:\n  " + "\n  ".join(problems)

    print(f"  {len(guides)} guide(s) are registered and link to real documentation anchors.")


if __name__ == "__main__":
    tests = [
        test_operations_panes_match_navigation,
        test_every_operations_section_is_described,
        test_every_v1_operations_field_is_claimed,
        test_schema_does_not_invent_operations_fields,
        test_select_options_match_v1,
        test_number_bounds_match_v1,
        test_dependency_chains_are_complete,
        test_calculated_values_are_refused,
        test_input_types_have_renderers,
        test_readout_descriptors_name_real_things,
        test_section_guides_are_declared_registered_and_documented,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
