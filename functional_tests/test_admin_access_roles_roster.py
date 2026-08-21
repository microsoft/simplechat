#!/usr/bin/env python3
"""
Functional test for the Access & Roles app role roster.
Version: 0.260.017
Implemented in: 0.260.017

Settings that can require an Entra app role are spread across seven tabs, which
makes the overall access policy impossible to read in one go. Access & Roles now
gathers them into one roster.

The switches themselves stay on their own tabs, so the roster shows mirrors. A
mirror must never carry a name attribute: the Admin Settings form posts once and
the backend reads by field name, so a named duplicate would submit the setting
twice.

This test ensures the roster stays a mirror rather than becoming a second copy.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.templates import read_admin_settings_template  # noqa: E402
from test_support.nav import iter_tabs  # noqa: E402

APP_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "application",
    "single_app",
)
ROSTER_JS = os.path.join(APP_ROOT, "static", "js", "admin", "admin_access_roles_roster.js")

ROLE_FIELD_PATTERN = re.compile(r'name="(require_member_of_[a-z_]+)"')


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_role_fields_are_declared_exactly_once():
    """A duplicated role field would post the setting twice."""
    print("Testing app role fields are not duplicated by the roster...")

    markup = read_admin_settings_template()
    names = ROLE_FIELD_PATTERN.findall(markup)
    assert names, "Expected app role requirement fields in Admin Settings"

    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, (
        "App role fields declared more than once, which would submit them "
        f"twice: {duplicates}"
    )

    print(f"All {len(names)} app role fields are declared exactly once.")
    return True


def test_roster_is_rendered_from_the_page():
    """A hand-written roster would drift as settings move between tabs."""
    print("Testing the roster builds itself from the page...")

    markup = read_admin_settings_template()
    assert 'id="app-role-requirements-list"' in markup, (
        "Expected the roster container in Access & Roles"
    )
    assert 'id="app-role-requirements-section"' in markup, (
        "Expected the roster card in Access & Roles"
    )

    source = _read(ROSTER_JS)
    assert 'input[type="checkbox"][name^="require_member_of_"]' in source, (
        "The roster should discover role switches from the page rather than "
        "from a hard-coded list, so it cannot fall out of step"
    )

    print("The roster is built from the page.")
    return True


def test_roster_mirrors_carry_no_name():
    """The whole point of a mirror is that it is not submitted."""
    print("Testing roster mirrors are not submitted with the form...")

    source = _read(ROSTER_JS)
    mirror_block = source[source.index("function buildRow("):source.index("export function")]

    assert "mirror.name" not in mirror_block, (
        "A roster mirror must not be given a name attribute, or its setting "
        "would be posted twice"
    )
    assert "data-ignore-settings-change" in mirror_block, (
        "A roster mirror should be excluded from unsaved-change tracking"
    )
    assert "data-role-mirror-for" in mirror_block, (
        "A roster mirror should record which control it drives"
    )

    print("Roster mirrors carry no name and are excluded from change tracking.")
    return True


def test_roster_lives_in_access_and_roles():
    """The roster is only useful where access policy is being read."""
    print("Testing the roster is listed under Access & Roles...")

    section_ids = {
        section["id"]
        for _, tab in iter_tabs()
        if tab["id"] == "access-roles"
        for section in tab["sections"]
    }
    assert "app-role-requirements-section" in section_ids, (
        "The app role roster should be a section of the Access & Roles tab"
    )

    print("The roster is listed under Access & Roles.")
    return True


if __name__ == "__main__":
    tests = [
        test_role_fields_are_declared_exactly_once,
        test_roster_is_rendered_from_the_page,
        test_roster_mirrors_carry_no_name,
        test_roster_lives_in_access_and_roles,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"Test failed: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
