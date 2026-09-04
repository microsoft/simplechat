#!/usr/bin/env python3
# test_v2_admin_inbound_mcp_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings Inbound MCP tab.
Version: 0.261.065
Implemented in: 0.261.065

Two things about this tab are unusual, and both fail silently.

It is gated by ``ENABLE_MCP_UI``, an App Service application setting with no
entry in the settings document. A condition read from settings alone can never
see it, so the fields depend on a runtime flag the settings API sends, and the
section still renders when the flag is off so an administrator can find out how
to turn it on.

Its allowlists are edited as ``{value, description}`` entries but the runtime
reads flat id lists derived from them, and single roles are mirrored into arrays.
The server-rendered form derives all of that on save. Without the same
derivation, an allowlist edited in the new interface would be stored and then
ignored -- the worst possible failure for an access control list, because the
screen would show the restriction while the runtime applied the old one.
"""

import re
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module, stubbed_config
from test_support.nav import ADMIN_NAV
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
PANES_DIR = APP_ROOT / "templates" / "admin" / "_panes"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

SECTION_ID = "inbound-mcp-configuration"

# The tenant this stubbed deployment belongs to. Restricting tenants is expressed
# by admitting only this one, so the derivation is checked against a known value.
HOME_TENANT_ID = "home-tenant-id"

# The five constants functions_mcp_server_config reads from config. Paths are not
# exercised here; only TENANT_ID affects the derivations under test.
CONFIG_CONSTANTS = {
    "INBOUND_MCP_AUTHORIZATION_SERVER_METADATA_PATH": "/.well-known/oauth-authorization-server",
    "INBOUND_MCP_PRM_PATH": "/.well-known/oauth-protected-resource",
    "INBOUND_MCP_PRM_PATHS": ("/.well-known/oauth-protected-resource",),
    "INBOUND_MCP_RESOURCE_PATH": "/external/mcp",
    "TENANT_ID": HOME_TENANT_ID,
}

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")

fields_module = import_app_module("admin_settings_fields")


@contextmanager
def real_mcp_config():
    """Run a normalization with the real inbound MCP helpers available.

    The derivations delegate to ``functions_mcp_server_config``, which is
    imported lazily precisely because it cannot be loaded in a plain test
    process. Loading it against a config stub is what lets these checks exercise
    the real rules rather than assert on source text.
    """
    with stubbed_config(**CONFIG_CONSTANTS):
        yield


def normalize(updates, current=None):
    with real_mcp_config():
        return fields_module.normalize_admin_settings_updates(updates, current or {})


def read(path):
    assert path.is_file(), f"Missing expected file: {path}"
    return path.read_text(encoding="utf-8")


def mcp_fields():
    return fields_module.get_admin_settings_fields()[SECTION_ID]


def test_inbound_mcp_section_is_declared():
    """An undeclared section falls back to rendering two bare switches."""
    print("Testing the Inbound MCP section declaration...")

    assert_app_version_at_least("0.261.065")

    tab = next(
        (
            tab
            for group in ADMIN_NAV
            if group["id"] == "agents-actions"
            for tab in group["tabs"]
            if tab["id"] == "inbound-mcp"
        ),
        None,
    )
    assert tab, "ADMIN_NAV no longer defines an 'inbound-mcp' tab."
    assert [section["id"] for section in tab["sections"]] == [SECTION_ID]

    assert not tab["sections"][0].get("condition"), (
        "The section must stay unconditional. Hiding it when the preview flag is "
        "off would leave an administrator no way to learn the flag exists."
    )

    print(f"  {len(mcp_fields())} field(s) declared for {SECTION_ID}.")
    return True


def test_every_inbound_mcp_pane_field_is_claimed_by_the_schema():
    """A V1 field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that every V1 Inbound MCP field is claimed...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    names = {
        name
        for name in FIELD_NAME_RE.findall(read(PANES_DIR / "inbound-mcp.html"))
        if not JINJA_RE.search(name)
    }
    missing = sorted(names - claimed - documented)

    assert not missing, (
        "These V1 Inbound MCP fields have no V2 equivalent and no recorded "
        "reason:\n  " + "\n  ".join(missing)
    )

    print(f"  All {len(names)} V1 Inbound MCP field name(s) are claimed.")
    return True


def test_configuration_is_gated_on_the_runtime_flag():
    """A settings-only condition can never see an App Service setting."""
    print("\nTesting the preview flag gate...")

    ungated = []
    notice = None
    for field in mcp_fields():
        flags = {
            (dependency.get("flag"), dependency.get("equals"))
            for dependency in fields_module.iter_dependencies(field)
            if dependency.get("flag")
        }
        if ("mcp_ui_enabled", False) in flags:
            notice = field
            continue
        if ("mcp_ui_enabled", True) not in flags:
            ungated.append(field.get("key") or field.get("component"))

    assert not ungated, (
        "These Inbound MCP fields would render even where the preview UI is "
        "switched off for the deployment:\n  " + "\n  ".join(map(str, ungated))
    )

    assert notice is not None, (
        "Nothing explains how to enable the tab, so an administrator would see "
        "an empty section and no reason for it."
    )
    assert notice["type"] == "component", "The notice must be a component field."

    print("  Every setting is gated, and a notice covers the disabled state.")
    return True


def test_the_settings_api_sends_the_runtime_flag():
    """The gate is unusable if the flag never reaches the browser."""
    print("\nTesting that mcp_ui_enabled is sent to the SPA...")

    route = read(APP_ROOT / "route_backend_v2.py")
    assert "runtime_flags" in route and "is_mcp_ui_enabled()" in route, (
        "route_backend_v2.py no longer sends the runtime flags the schema "
        "depends on, so every Inbound MCP field would stay hidden."
    )

    page = read(V2_SRC / "pages" / "AdminSettingsPage.tsx")
    assert "runtime_flags" in page, "The SPA no longer reads runtime_flags."

    print("  The flag is sent by the API and read by the page.")
    return True


def test_allowlist_edits_derive_the_lists_the_runtime_reads():
    """Storing entries without their id list would apply the old allowlist."""
    print("\nTesting inbound MCP derivations...")

    normalized, errors, _warnings = normalize(
        {
            "inbound_mcp_allowed_client_app_entries": [
                {"value": "  ABC-123  ", "description": "VS Code"},
                {"value": "abc-123", "description": "duplicate"},
                {"value": "", "description": "blank"},
            ]
        },
        {},
    )

    assert not errors, f"Unexpected errors: {errors}"
    assert normalized["inbound_mcp_allowed_client_app_ids"] == ["abc-123"], (
        "The runtime reads the id list, so it must be derived, trimmed, "
        "lowercased and de-duplicated alongside the entries."
    )
    assert [entry["value"] for entry in normalized["inbound_mcp_allowed_client_app_entries"]] == [
        "abc-123"
    ]

    print("  Client app entries derive their id list.")
    return True


def test_a_single_role_is_mirrored_into_the_array_the_runtime_reads():
    """Both shapes are stored, and V1 keeps them in step."""
    print("\nTesting role mirroring...")

    normalized, errors, _warnings = normalize(
        {"inbound_mcp_required_user_role": "  CustomRole  "}, {}
    )

    assert not errors, f"Unexpected errors: {errors}"
    assert normalized["inbound_mcp_required_user_role"] == "CustomRole"
    assert normalized["inbound_mcp_required_user_roles"] == ["CustomRole"], (
        "The array form was not updated, so the runtime would keep checking the "
        "previous role."
    )

    print("  A role edit updates both stored shapes.")
    return True


def test_allowing_all_sources_collapses_the_source_list():
    """The two modes are expressed differently, and mixing them is dangerous."""
    print("\nTesting source allowlist modes...")

    allow_all, errors, _warnings = normalize(
        {"inbound_mcp_allow_all_source_ids": True}, {}
    )
    assert not errors, f"Unexpected errors: {errors}"
    assert allow_all["inbound_mcp_allowed_source_ids"] == ["*"], (
        "Allowing every source is expressed as the wildcard id list."
    )

    controlled, errors, _warnings = normalize(
        {"inbound_mcp_allow_all_source_ids": False},
        {
            "inbound_mcp_allowed_source_entries": [
                {"value": "*", "description": "Allow all inbound MCP source IDs"},
                {"value": "vscode", "description": "Editor"},
            ]
        },
    )
    assert not errors, f"Unexpected errors: {errors}"
    assert controlled["inbound_mcp_allowed_source_ids"] == ["vscode"], (
        "Turning off allow-all must drop the wildcard row, or every source would "
        "still be accepted while the screen showed a restricted list."
    )
    assert all(
        entry["value"] != "*"
        for entry in controlled["inbound_mcp_allowed_source_entries"]
    )

    print("  Each mode produces the id list the runtime expects.")
    return True


def test_restricting_tenants_keeps_the_entries_an_admin_typed():
    """Switching the tenant gate off must not silently delete configuration."""
    print("\nTesting tenant allowlist behaviour...")

    current = {
        "inbound_mcp_allowed_tenant_entries": [
            {"value": "partner-tenant", "description": "Partner"}
        ]
    }

    restricted, errors, _warnings = normalize(
        {"inbound_mcp_allow_external_tenants": False}, current
    )
    assert not errors, f"Unexpected errors: {errors}"
    assert [
        entry["value"] for entry in restricted["inbound_mcp_allowed_tenant_entries"]
    ] == ["partner-tenant"], "The partner tenant an admin configured was discarded."
    assert restricted["inbound_mcp_allowed_tenant_ids"] == [HOME_TENANT_ID], (
        "A restricted deployment must admit its own tenant and nothing else."
    )

    reopened, errors, _warnings = normalize(
        {"inbound_mcp_allow_external_tenants": True}, current
    )
    assert not errors, f"Unexpected errors: {errors}"
    assert "partner-tenant" in reopened["inbound_mcp_allowed_tenant_ids"]
    assert HOME_TENANT_ID in reopened["inbound_mcp_allowed_tenant_ids"], (
        "Admitting other tenants must not lock out the deployment's own."
    )

    print("  Entries survive the gate; only the effective id list changes.")
    return True


def test_derivations_reuse_the_functions_that_already_own_them():
    """Reimplementing these rules would let the two admin surfaces disagree."""
    print("\nTesting that derivations are delegated...")

    source = read(APP_ROOT / "admin_settings_fields.py")
    for helper in (
        "normalize_inbound_mcp_value_entries",
        "inbound_mcp_entry_values",
        "ensure_inbound_mcp_default_tenant_entry",
        "normalize_inbound_mcp_single_value",
    ):
        assert helper in source, (
            f"{helper} is no longer used, so the V2 surface has its own idea of "
            "what a valid inbound MCP allowlist is."
        )

    print("  All four allowlist helpers are reused.")
    return True


if __name__ == "__main__":
    tests = [
        test_inbound_mcp_section_is_declared,
        test_every_inbound_mcp_pane_field_is_claimed_by_the_schema,
        test_configuration_is_gated_on_the_runtime_flag,
        test_the_settings_api_sends_the_runtime_flag,
        test_allowlist_edits_derive_the_lists_the_runtime_reads,
        test_a_single_role_is_mirrored_into_the_array_the_runtime_reads,
        test_allowing_all_sources_collapses_the_source_list,
        test_restricting_tenants_keeps_the_entries_an_admin_typed,
        test_derivations_reuse_the_functions_that_already_own_them,
    ]
    results = [test() for test in tests]
    print(f"\nResults: {sum(bool(r) for r in results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)

