#!/usr/bin/env python3
# test_v2_admin_security_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings Security group.
Version: 0.261.063
Implemented in: 0.261.063

The V2 React admin surface renders from ``admin_settings_fields.py`` rather than
from the server-rendered panes, so the two descriptions of the same settings can
drift apart silently: a field added to a V1 pane simply never appears in V2, and
nothing fails.

Security is the group where that mattered most. Before it was described, the
fallback ``enable_*`` scan could draw its switches and nothing else, which meant
the Key Vault name, the Content Safety endpoint and key, the idle timeout values,
the Front Door URL and the access denied message were all unreachable in V2 -- and
the Permissions, Access Denied Message and Key Vault sections rendered as nothing
at all, because a section with no switches and no declared fields is skipped.

This test does for Security what ``test_v2_admin_appearance_parity.py`` does for
Appearance. It reads the six panes that make up the group, collects the form field
names V1 submits, and requires each one to be claimed by the schema. It also
checks the parts a generic renderer must get right and a name-only comparison
would miss: select option values, numeric bounds, secret declarations, and the
dependency chains that decide which controls are visible.
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

SECURITY_GROUP_ID = "security"

# The seven tabs that make up the Security group, and the sections each contributes.
# Sourced from ADMIN_NAV, verified against it below. Workspace Identities arrived
# with the Workspaces work and is declared by that schema entry, so it is listed
# here to keep this test's view of the group complete.
SECURITY_PANES = {
    "access-roles": (
        "permissions-section",
        "app-role-requirements-section",
        "access-denied-message-section",
    ),
    "secrets": ("keyvault-section",),
    "workspace-identities": ("workspace-identities-section",),
    "content-safety": ("content-safety-section",),
    "session": ("idle-timeout-section",),
    "network": ("front-door-section",),
    "rate-limiting": ("rate-limit-message-section",),
}

# Panes this test reads for V1 parity. Workspace Identities is excluded: its
# parity is held by test_v2_admin_workspaces_parity.py, which owns that work.
SECURITY_PARITY_PANES = tuple(
    tab for tab in SECURITY_PANES if tab != "workspace-identities"
)

# Settings that must be declared as secrets, so the browser is handed a placeholder
# instead of the stored credential. Declaring one of these as plain text would put
# a live key into the settings payload.
EXPECTED_SECRET_KEYS = {
    "content_safety_key",
    "azure_apim_content_safety_subscription_key",
}

# Dependency chains a V2 control has to reproduce, because the server-rendered page
# expresses them as nested divs that have no equivalent in a flat list. Each entry
# is the full set of conditions the field carries.
EXPECTED_DEPENDENCY_CHAINS = {
    "content_safety_key": {
        ("enable_content_safety", True),
        ("enable_content_safety_apim", False),
        ("content_safety_authentication_type", "key"),
    },
    "azure_apim_content_safety_subscription_key": {
        ("enable_content_safety", True),
        ("enable_content_safety_apim", True),
    },
    "content_safety_endpoint": {
        ("enable_content_safety", True),
        ("enable_content_safety_apim", False),
    },
    "key_vault_name": {("enable_key_vault_secret_storage", True)},
    "key_vault_secret_expiration_default_lead_days": {
        ("enable_key_vault_secret_storage", True),
        ("enable_key_vault_secret_expiration_reminders", True),
    },
}

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")

OPTION_RE = re.compile(r'<option value="([^"]*)"')
SELECT_BLOCK_RE = re.compile(
    r'<select[^>]*\sname="(?P<name>[^"]+)"(?P<body>.*?)</select>',
    re.DOTALL,
)
NUMBER_BLOCK_RE = re.compile(r'<input[^>]*type="number"(?P<attrs>[^>]*)>', re.DOTALL)
ATTR_RE = re.compile(r'(\w[\w-]*)="([^"]*)"')

fields_module = import_app_module("admin_settings_fields")


def read_pane(pane_id):
    """Return the raw markup for one Admin Settings pane."""
    pane_path = PANES_DIR / f"{pane_id}.html"
    assert pane_path.is_file(), f"Missing Admin Settings pane: {pane_path}"
    return pane_path.read_text(encoding="utf-8")


def collect_pane_field_names(markup):
    """Return literal form field names submitted by a pane."""
    return {name for name in FIELD_NAME_RE.findall(markup) if not JINJA_RE.search(name)}


def security_schema_fields():
    """Return ``{key: field}`` for every field the Security sections declare."""
    section_ids = {
        section_id
        for sections in (SECURITY_PANES[tab] for tab in SECURITY_PARITY_PANES)
        for section_id in sections
    }
    return {
        field["key"]: field
        for section_id, field in fields_module.iter_fields()
        if section_id in section_ids and field.get("key")
    }


def dependency_pairs(field):
    """Return the ``(key, equals)`` pairs a field's ``depends_on`` carries."""
    return {
        (condition["key"], condition.get("equals", True))
        for condition in fields_module.iter_field_dependencies(field)
    }


def test_security_panes_match_navigation():
    """The panes this test reads must be the ones ADMIN_NAV puts in the group."""
    print("Testing Security pane list against ADMIN_NAV...")

    assert_app_version_at_least("0.261.063")

    group = next((g for g in ADMIN_NAV if g["id"] == SECURITY_GROUP_ID), None)
    assert group, "ADMIN_NAV no longer defines a 'security' group."

    nav_tabs = {tab["id"]: tuple(s["id"] for s in tab["sections"]) for tab in group["tabs"]}

    assert set(nav_tabs) == set(SECURITY_PANES), (
        "The Security group's tabs changed. Update SECURITY_PANES and the schema "
        f"together.\n  ADMIN_NAV: {sorted(nav_tabs)}\n  test: {sorted(SECURITY_PANES)}"
    )

    for tab_id, section_ids in nav_tabs.items():
        assert section_ids == SECURITY_PANES[tab_id], (
            f"Sections for the '{tab_id}' tab changed.\n"
            f"  ADMIN_NAV: {section_ids}\n  test: {SECURITY_PANES[tab_id]}"
        )

    print(f"  {len(nav_tabs)} tab(s) and their sections match ADMIN_NAV.")
    return True


def test_every_v1_security_field_is_claimed():
    """A field only V1 has is a setting the V2 surface cannot reach."""
    print("\nTesting that every V1 Security field is claimed by the schema...")

    claimed = fields_module.get_legacy_field_names()
    excused = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    unclaimed = []
    total = 0
    for pane_id in SECURITY_PARITY_PANES:
        for name in sorted(collect_pane_field_names(read_pane(pane_id))):
            total += 1
            if name not in claimed and name not in excused:
                unclaimed.append(f"{pane_id}.html: {name}")

    assert not unclaimed, (
        "These fields exist in the server-rendered Security panes but nothing in "
        "admin_settings_fields.py claims them, so they are missing from the V2 "
        "admin surface. Declare each one, or record why it has no V2 equivalent in "
        "LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT:\n  " + "\n  ".join(unclaimed)
    )

    print(f"  All {total} V1 Security field(s) are claimed by the schema.")
    return True


def test_schema_does_not_invent_security_fields():
    """A V2 field with no V1 counterpart writes a setting nothing else reads."""
    print("\nTesting that the schema does not invent Security fields...")

    pane_fields = set()
    for pane_id in SECURITY_PARITY_PANES:
        pane_fields |= collect_pane_field_names(read_pane(pane_id))

    invented = []
    for key, field in sorted(security_schema_fields().items()):
        legacy_names = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
        if any(name in pane_fields for name in legacy_names):
            continue
        if key in fields_module.V2_ONLY_FIELDS:
            continue
        invented.append(f"{key} (type {field.get('type')})")

    assert not invented, (
        "These schema fields have no counterpart in the server-rendered Security "
        "panes, so saving them would write settings the rest of the application "
        "never reads. Remove them, or record the reason in V2_ONLY_FIELDS:\n  "
        + "\n  ".join(invented)
    )

    print("  Every Security schema field maps back to a V1 field.")
    return True


def test_secrets_are_declared_as_secrets():
    """A credential declared as text is a credential sent to the browser."""
    print("\nTesting that Security credentials are declared as secrets...")

    declared_secrets = fields_module.get_secret_field_keys()
    missing = sorted(EXPECTED_SECRET_KEYS - declared_secrets)

    assert not missing, (
        "These settings hold credentials but are not declared with the 'secret' "
        "type, so the V2 settings payload would carry their stored value to the "
        "browser:\n  " + "\n  ".join(missing)
    )

    print(f"  All {len(EXPECTED_SECRET_KEYS)} credential(s) are declared as secrets.")
    return True


def test_select_options_match_v1():
    """A select offering different values in each interface stores different data."""
    print("\nTesting Security select option values against V1...")

    schema_fields = security_schema_fields()

    checked = 0
    mismatches = []
    for pane_id in SECURITY_PARITY_PANES:
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
                    f"{name}: V1 offers {sorted(v1_values)}, schema offers "
                    f"{sorted(v2_values)}"
                )

    assert not mismatches, (
        "These selects do not offer the same values in both interfaces:\n  "
        + "\n  ".join(mismatches)
    )

    print(f"  {checked} select(s) offer identical values in both interfaces.")
    return True


def test_number_bounds_match_v1():
    """A looser bound in one interface lets a value through the other refuses."""
    print("\nTesting Security number bounds against V1...")

    schema_fields = security_schema_fields()

    checked = 0
    mismatches = []
    for pane_id in SECURITY_PARITY_PANES:
        for match in NUMBER_BLOCK_RE.finditer(read_pane(pane_id)):
            attrs = dict(ATTR_RE.findall(match.group("attrs")))
            name = attrs.get("name")
            field = schema_fields.get(name)
            if not field or field.get("type") != "number":
                continue

            checked += 1
            for bound in ("min", "max"):
                if bound not in attrs:
                    continue
                if int(attrs[bound]) != field.get(bound):
                    mismatches.append(
                        f"{name}: V1 {bound}={attrs[bound]}, schema "
                        f"{bound}={field.get(bound)}"
                    )

    assert not mismatches, (
        "These number controls do not share bounds across the two interfaces:\n  "
        + "\n  ".join(mismatches)
    )

    print(f"  {checked} number control(s) share identical bounds.")
    return True


def test_dependency_chains_are_complete():
    """A flat list has to carry every gate V1 expressed as a nested div."""
    print("\nTesting Security field dependency chains...")

    schema_fields = security_schema_fields()

    problems = []
    for key, expected in EXPECTED_DEPENDENCY_CHAINS.items():
        field = schema_fields.get(key)
        if field is None:
            problems.append(f"{key}: not declared in a Security section")
            continue
        actual = dependency_pairs(field)
        if actual != expected:
            problems.append(
                f"{key}: expected {sorted(expected)}, found {sorted(actual)}"
            )

    assert not problems, (
        "The server-rendered page nests these controls inside enclosing blocks, so "
        "each gate has to be declared on the field itself for V2 to hide it in the "
        "same situations:\n  " + "\n  ".join(problems)
    )

    print(f"  All {len(EXPECTED_DEPENDENCY_CHAINS)} dependency chain(s) are complete.")
    return True


def test_section_status_targets_real_settings():
    """A status rule naming a key that does not exist reports a state nobody set."""
    print("\nTesting section status descriptors...")

    settings_source = (
        REPO_ROOT / "application" / "single_app" / "functions_settings.py"
    ).read_text(encoding="utf-8")
    setting_keys = set(re.findall(r"^\s*'([a-z0-9_]+)'\s*:", settings_source, re.MULTILINE))

    nav_sections = {
        section["id"]
        for group in ADMIN_NAV
        for tab in group["tabs"]
        for section in tab["sections"]
    }

    problems = []
    for section_id, rule in fields_module.get_admin_section_status().items():
        if section_id not in nav_sections:
            problems.append(f"{section_id}: not a section in ADMIN_NAV")
        if rule["enabled_key"] not in setting_keys:
            problems.append(f"{section_id}: enabled_key {rule['enabled_key']!r} is not a setting")
        for candidate in rule.get("configured", []):
            for key in list(candidate.get("when", {})) + list(candidate["requires"]):
                if key not in setting_keys:
                    problems.append(f"{section_id}: {key!r} is not a setting")

    assert not problems, (
        "These section status descriptors reference something that does not "
        "exist:\n  " + "\n  ".join(problems)
    )

    print(
        f"  All {len(fields_module.get_admin_section_status())} status descriptor(s) "
        "reference real sections and settings."
    )
    return True


if __name__ == "__main__":
    tests = [
        test_security_panes_match_navigation,
        test_every_v1_security_field_is_claimed,
        test_schema_does_not_invent_security_fields,
        test_secrets_are_declared_as_secrets,
        test_select_options_match_v1,
        test_number_bounds_match_v1,
        test_dependency_chains_are_complete,
        test_section_status_targets_real_settings,
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
