#!/usr/bin/env python3
# test_v2_admin_app_role_registry.py
"""
Functional test that the app role registry describes every role requirement.
Version: 0.261.059
Implemented in: 0.261.059

Admin Settings gathers every "require an Entra app role" switch into one place so
the access policy can be read as a whole. The server-rendered page builds that
roster by scanning the DOM for ``input[name^="require_member_of_"]``, which has two
failure modes nobody can see from the page itself: it misses any requirement whose
settings key does not start with that prefix, and it cannot work at all in the V2
surface, where the controls are not all in one document.

``admin_app_roles.py`` replaces the scan with a declaration. That trades one silent
failure for another unless something checks it, because a new role requirement
added to a feature tab would simply not appear in the catalog. These checks are
that something:

  - every role-shaped settings key is registered,
  - every registered key is a real setting,
  - each entry names a section that exists and a capability that exists,
  - the Entra role value each entry names is the one the V1 pane documents.

The last check is the important one. The role value is what an administrator types
into Entra, and a wrong value here produces a requirement that can never be
satisfied by anyone.
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
SETTINGS_MODULE = APP_ROOT / "functions_settings.py"
PANES_DIR = APP_ROOT / "templates" / "admin" / "_panes"
CATALOG_TSX = (
    REPO_ROOT
    / "application"
    / "v2_ui"
    / "src"
    / "components"
    / "admin"
    / "AppRoleRoster.tsx"
)

SETTING_KEY_RE = re.compile(r"^\s*'(?P<key>[a-z0-9_]+)'\s*:", re.MULTILINE)

roles_module = import_app_module("admin_app_roles")
fields_module = import_app_module("admin_settings_fields")


def read_setting_keys():
    """Return the keys the settings document defaults to."""
    source = SETTINGS_MODULE.read_text(encoding="utf-8")
    keys = {match.group("key") for match in SETTING_KEY_RE.finditer(source)}
    assert keys, "No settings defaults were found; the extraction likely broke."
    return keys


def read_all_panes():
    """Return the concatenated markup of every Admin Settings pane."""
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(PANES_DIR.glob("*.html"))
    )


def test_every_role_setting_is_registered():
    """An unregistered requirement is invisible in the access policy view."""
    print("Testing that every role-shaped setting is registered...")

    assert_app_version_at_least("0.261.059")

    candidates = {
        key for key in read_setting_keys() if roles_module.is_app_role_setting_key(key)
    }
    assert candidates, "No role-shaped settings found; the extraction likely broke."

    missing = sorted(candidates - roles_module.get_app_role_setting_keys())

    assert not missing, (
        "These settings require an Entra app role but are not described in "
        "admin_app_roles.py, so they are missing from the App Role Requirements "
        "catalog and the access policy cannot be read in one place. Add an entry "
        "for each:\n  " + "\n  ".join(missing)
    )

    print(f"  All {len(candidates)} role-shaped setting(s) are registered.")
    return True


def test_registry_describes_only_real_settings():
    """An entry for a setting that no longer exists renders a switch over nothing."""
    print("\nTesting that every registered key is a real setting...")

    setting_keys = read_setting_keys()
    unknown = sorted(roles_module.get_app_role_setting_keys() - setting_keys)

    assert not unknown, (
        "These registry entries name settings that do not exist in the settings "
        "defaults. Either the key is misspelled or the requirement was removed:\n  "
        + "\n  ".join(unknown)
    )

    print(f"  All {len(roles_module.APP_ROLE_REQUIREMENTS)} registered key(s) are real.")
    return True


def test_entries_reference_real_sections_and_capabilities():
    """A broken link or a phantom gate misleads rather than helping."""
    print("\nTesting registry section and capability references...")

    setting_keys = read_setting_keys()
    nav_sections = {
        section["id"]
        for group in ADMIN_NAV
        for tab in group["tabs"]
        for section in tab["sections"]
    }

    problems = []
    for requirement in roles_module.APP_ROLE_REQUIREMENTS:
        if requirement["section_id"] not in nav_sections:
            problems.append(
                f"{requirement['key']}: section {requirement['section_id']!r} is not "
                "in ADMIN_NAV, so 'Go to setting' would lead nowhere"
            )
        gate = requirement["depends_on"]
        if gate and gate not in setting_keys:
            problems.append(
                f"{requirement['key']}: depends_on {gate!r} is not a setting, so the "
                "'has no effect right now' hint can never be right"
            )

    assert not problems, (
        "These registry entries reference something that does not exist:\n  "
        + "\n  ".join(problems)
    )

    print(f"  All {len(roles_module.APP_ROLE_REQUIREMENTS)} entry/entries resolve.")
    return True


def test_role_values_match_the_server_rendered_panes():
    """A wrong role value produces a requirement nobody can satisfy."""
    print("\nTesting registry role values against the V1 panes...")

    panes = read_all_panes()

    missing = [
        f"{requirement['key']}: no <code>{requirement['role']}</code> in any pane"
        for requirement in roles_module.APP_ROLE_REQUIREMENTS
        if f"<code>{requirement['role']}</code>" not in panes
    ]

    assert not missing, (
        "These Entra role values do not appear in any server-rendered pane, so the "
        "two interfaces are telling administrators to assign different roles:\n  "
        + "\n  ".join(missing)
    )

    print(f"  All {len(roles_module.APP_ROLE_REQUIREMENTS)} role value(s) match V1.")
    return True


def test_entries_carry_both_states():
    """The catalog states what changes when a requirement is on and when it is off."""
    print("\nTesting that every entry explains both states...")

    incomplete = []
    for requirement in roles_module.APP_ROLE_REQUIREMENTS:
        for attribute in ("label", "role", "grants", "when_off"):
            if not str(requirement.get(attribute) or "").strip():
                incomplete.append(f"{requirement['key']}: {attribute} is empty")

    assert not incomplete, (
        "The catalog shows 'grants' while a requirement is enforced and 'when_off' "
        "while it is not, so an empty one leaves a row saying nothing:\n  "
        + "\n  ".join(incomplete)
    )

    print(f"  All {len(roles_module.APP_ROLE_REQUIREMENTS)} entry/entries are complete.")
    return True


def test_catalog_is_declared_and_rendered():
    """A registry nothing renders is a description with no reader."""
    print("\nTesting that the catalog component is wired up...")

    declared_components = {
        field.get("component")
        for _section_id, field in fields_module.iter_fields()
        if field.get("type") == "component"
    }

    assert "app-role-requirements-roster" in declared_components, (
        "No schema field declares the 'app-role-requirements-roster' component, so the "
        "catalog never renders. Declare it in app-role-requirements-section."
    )

    assert CATALOG_TSX.is_file(), f"Missing the catalog component: {CATALOG_TSX}"

    source = CATALOG_TSX.read_text(encoding="utf-8")
    missing = [
        name
        for name, fragment in (
            ("the Entra role value", "entry.role"),
            ("what enforcing it restricts", "entry.grants"),
            ("who keeps access when it is off", "entry.whenOff"),
            ("the marker for a requirement guarding a disabled feature", "entry.dependsOn"),
        )
        if fragment not in source
    ]

    assert not missing, (
        "The roster no longer renders the registry detail it exists to surface, so the "
        "registry is being maintained for nothing:\n  " + "\n  ".join(missing)
    )

    print("  The catalog is declared by the schema and renders the registry detail.")
    return True


if __name__ == "__main__":
    tests = [
        test_every_role_setting_is_registered,
        test_registry_describes_only_real_settings,
        test_entries_reference_real_sections_and_capabilities,
        test_role_values_match_the_server_rendered_panes,
        test_entries_carry_both_states,
        test_catalog_is_declared_and_rendered,
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
