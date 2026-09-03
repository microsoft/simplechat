#!/usr/bin/env python3
# test_v2_admin_appearance_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings Appearance group.
Version: 0.261.039
Implemented in: 0.261.039

The V2 React admin surface renders from ``admin_settings_fields.py`` rather than
from the server-rendered panes, so the two descriptions of the same settings can
drift apart silently: a field added to a V1 pane simply never appears in V2, and
nothing fails.

This test closes that gap for the Appearance group. It reads the three panes that
make up the group, collects the form field names V1 submits, and requires each
one to be claimed by the schema -- either because the schema declares the same
key, or because ``LEGACY_FIELD_NAMES`` records the shape difference, or because
``LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT`` documents why there is no equivalent.

It also checks the parts of a field that a generic renderer must get right and
that a name-only comparison would miss: select option values, numeric bounds,
and the section ids the schema files fields under.
"""

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
PANES_DIR = REPO_ROOT / "application" / "single_app" / "templates" / "admin" / "_panes"

# The three tabs that make up the Appearance group, and the sections each one
# contributes. Sourced from ADMIN_NAV, verified against it below.
APPEARANCE_GROUP_ID = "appearance"
APPEARANCE_PANES = {
    "branding": ("branding-section", "home-page-text-section", "appearance-section"),
    "notices": (
        "classification-banner-section",
        "ai-notice-section",
        "terms-of-use-section",
        "user-agreement-section",
    ),
    "custom-pages": ("custom-pages-section", "external-links-section"),
}

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")

OPTION_RE = re.compile(r'<option value="([^"]*)"')
SELECT_BLOCK_RE = re.compile(
    r'<select[^>]*\sname="(?P<name>[^"]+)"(?P<body>.*?)</select>',
    re.DOTALL,
)
RANGE_BLOCK_RE = re.compile(
    r'<input[^>]*type="range"(?P<attrs>[^>]*)>',
    re.DOTALL,
)
ATTR_RE = re.compile(r'(\w[\w-]*)="([^"]*)"')

fields_module = import_app_module("admin_settings_fields")


def read_pane(pane_id):
    """Return the raw markup for one Admin Settings pane."""
    pane_path = PANES_DIR / f"{pane_id}.html"
    assert pane_path.is_file(), f"Missing Admin Settings pane: {pane_path}"
    return pane_path.read_text(encoding="utf-8")


def collect_pane_field_names(markup):
    """Return literal form field names submitted by a pane."""
    return {
        name
        for name in FIELD_NAME_RE.findall(markup)
        if not JINJA_RE.search(name)
    }


def test_appearance_panes_match_navigation():
    """The panes this test reads must be the ones ADMIN_NAV puts in the group."""
    print("Testing Appearance pane list against ADMIN_NAV...")

    assert_app_version_at_least("0.261.039")

    group = next((g for g in ADMIN_NAV if g["id"] == APPEARANCE_GROUP_ID), None)
    assert group, "ADMIN_NAV no longer defines an 'appearance' group."

    nav_tabs = {tab["id"]: tuple(s["id"] for s in tab["sections"]) for tab in group["tabs"]}

    assert set(nav_tabs) == set(APPEARANCE_PANES), (
        "The Appearance group's tabs changed. Update APPEARANCE_PANES and the "
        f"schema together.\n  ADMIN_NAV: {sorted(nav_tabs)}\n  test: "
        f"{sorted(APPEARANCE_PANES)}"
    )

    for tab_id, section_ids in nav_tabs.items():
        assert section_ids == APPEARANCE_PANES[tab_id], (
            f"Sections for the '{tab_id}' tab changed.\n"
            f"  ADMIN_NAV: {section_ids}\n  test: {APPEARANCE_PANES[tab_id]}"
        )

    print(f"  {len(nav_tabs)} tab(s) and their sections match ADMIN_NAV.")
    return True


def test_every_v1_field_is_claimed_by_the_schema():
    """A V1 Appearance field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that every V1 Appearance field is claimed by the schema...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    unclaimed = {}
    total = 0
    for pane_id in APPEARANCE_PANES:
        names = collect_pane_field_names(read_pane(pane_id))
        total += len(names)
        missing = sorted(names - claimed - documented)
        if missing:
            unclaimed[pane_id] = missing

    assert not unclaimed, (
        "These fields exist in the server-rendered Appearance panes but are not "
        "described in admin_settings_fields.py, so they cannot appear in the V2 "
        "admin UI. Add a field definition, record the name in LEGACY_FIELD_NAMES "
        "if the shapes differ, or document the omission in "
        "LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT:\n"
        + "\n".join(f"  {pane}: {', '.join(names)}" for pane, names in unclaimed.items())
    )

    print(f"  All {total} V1 Appearance field(s) are claimed by the schema.")
    return True


def test_schema_does_not_invent_appearance_fields():
    """A schema key with no V1 counterpart would save a setting nothing reads."""
    print("\nTesting that the schema does not invent Appearance fields...")

    v1_names = set()
    for pane_id in APPEARANCE_PANES:
        v1_names |= collect_pane_field_names(read_pane(pane_id))

    appearance_sections = {
        section for sections in APPEARANCE_PANES.values() for section in sections
    }

    invented = []
    for section_id, field in fields_module.iter_fields():
        if section_id not in appearance_sections:
            continue
        key = field.get("key")
        if not key:
            continue
        legacy = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
        if not any(name in v1_names for name in legacy):
            invented.append(f"{section_id}.{key}")

    assert not invented, (
        "These schema fields have no matching field in the V1 Appearance panes, "
        "so V2 would write settings the rest of the application never reads:\n  "
        + "\n  ".join(invented)
    )

    print("  Every Appearance schema field maps back to a V1 field.")
    return True


def test_select_options_match_v1():
    """A select offering different values than V1 would save unreadable state."""
    print("\nTesting select option values against V1...")

    v1_options = {}
    for pane_id in APPEARANCE_PANES:
        for match in SELECT_BLOCK_RE.finditer(read_pane(pane_id)):
            name = match.group("name")
            if JINJA_RE.search(name):
                continue
            v1_options[name] = OPTION_RE.findall(match.group("body"))

    mismatches = []
    checked = 0
    for _section_id, field in fields_module.iter_fields():
        if field.get("type") != "select":
            continue
        key = field.get("key")
        if key not in v1_options:
            continue
        schema_values = [option["value"] for option in field["options"]]
        if schema_values != v1_options[key]:
            mismatches.append(
                f"{key}: schema {schema_values} != template {v1_options[key]}"
            )
        checked += 1

    assert not mismatches, (
        "These selects offer different values in each interface:\n  "
        + "\n  ".join(mismatches)
    )

    assert checked, "No select fields were compared; the extraction likely broke."
    print(f"  {checked} select(s) offer identical values in both interfaces.")
    return True


def test_range_bounds_match_v1():
    """The logo scale must span the same range in both interfaces."""
    print("\nTesting range bounds against V1...")

    v1_ranges = {}
    for pane_id in APPEARANCE_PANES:
        for match in RANGE_BLOCK_RE.finditer(read_pane(pane_id)):
            attrs = dict(ATTR_RE.findall(match.group("attrs")))
            name = attrs.get("name")
            if not name or JINJA_RE.search(name):
                continue
            v1_ranges[name] = attrs

    mismatches = []
    checked = 0
    for _section_id, field in fields_module.iter_fields():
        if field.get("type") != "range":
            continue
        attrs = v1_ranges.get(field.get("key"))
        if not attrs:
            continue
        for schema_prop, html_attr in (("min", "min"), ("max", "max"), ("step", "step")):
            if str(field.get(schema_prop)) != attrs.get(html_attr):
                mismatches.append(
                    f"{field['key']}.{schema_prop}: schema {field.get(schema_prop)} "
                    f"!= template {attrs.get(html_attr)}"
                )
        checked += 1

    assert not mismatches, (
        "These range controls differ between interfaces:\n  " + "\n  ".join(mismatches)
    )
    assert checked, "No range fields were compared; the extraction likely broke."
    print(f"  {checked} range control(s) share identical bounds.")
    return True


def test_schema_sections_exist_in_navigation():
    """A field filed under an unknown section id would never render."""
    print("\nTesting schema section ids against ADMIN_NAV...")

    nav_sections = {
        section["id"]
        for group in ADMIN_NAV
        for tab in group["tabs"]
        for section in tab["sections"]
    }

    unknown = sorted(set(fields_module.ADMIN_SETTINGS_FIELDS) - nav_sections)
    assert not unknown, (
        "These schema sections are not defined in admin_settings_nav.py, so the "
        "V2 UI has nowhere to render them:\n  " + "\n  ".join(unknown)
    )

    print(f"  All {len(fields_module.ADMIN_SETTINGS_FIELDS)} schema section(s) exist in ADMIN_NAV.")
    return True


if __name__ == "__main__":
    tests = [
        test_appearance_panes_match_navigation,
        test_every_v1_field_is_claimed_by_the_schema,
        test_schema_does_not_invent_appearance_fields,
        test_select_options_match_v1,
        test_range_bounds_match_v1,
        test_schema_sections_exist_in_navigation,
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
