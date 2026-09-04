#!/usr/bin/env python3
# test_v2_admin_workspaces_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings Workspaces group.
Version: 0.261.060
Implemented in: 0.261.060

The V2 React admin surface renders from ``admin_settings_fields.py``. Sections with
no entry there fall back to scanning the settings document for ``enable_*``
booleans, which means a setting that is not a boolean capability toggle -- a text
box, a number, a list of assigned ids, or any ``require_member_of_*`` role gate --
is simply invisible in V2 and nothing fails.

Before the Workspaces group was described, thirteen of its settings were in exactly
that position. This test keeps them described, the same way
``test_v2_admin_appearance_parity.py`` does for Appearance: every form field the
server-rendered panes submit must be claimed by the schema, and the schema must not
claim a field V1 does not have.

It also pins the two structural moves made at the same time, because both split a
setting away from the pane it used to live in and a half-applied move leaves either
V1 or V2 with a section that renders nothing:

  - Maximum File Size moved to Knowledge > Document Extraction. It caps chat
    attachments as well as workspace documents, so Workspaces only ever owned half
    of what it does.
  - Global Identities moved to Security. They are credentials that File Sync sources
    and Actions reuse, and Workspaces owns neither of those.

Finally it covers the app role roster, which mirrors every declared
``require_member_of_*`` switch into one place in Security. That roster is built from
the schema, so an undeclared role requirement is missing from it for the same reason
it is missing from the rest of V2.
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
SETTINGS_MODULE = APP_ROOT / "functions_settings.py"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

WORKSPACES_GROUP_ID = "workspaces"

# The tabs that make up the Workspaces group after the moves, and the sections each
# one contributes. Verified against ADMIN_NAV below rather than trusted.
WORKSPACES_PANES = {
    "workspace-types": (
        "personal-workspaces-section",
        "group-workspaces-section",
        "public-workspaces-section",
    ),
    "files-sharing": (
        "file-download-settings-section",
        "file-sharing-section",
        "shared-conversation-file-approvals-section",
    ),
}

# Where each relocated section now lives, and the pane whose markup must have moved
# with it. Nav and markup are separate files, so only checking one would let the
# other drift.
RELOCATED_SECTIONS = {
    "file-size-limit-section": {
        "group": "knowledge",
        "tab": "extraction",
        "pane": "extraction",
        "vacated_pane": "files-sharing",
        "field": "max_file_size_mb",
    },
}

# The tab that moved wholesale, rather than one section of a tab.
RELOCATED_TABS = {
    "workspace-identities": "security",
}

# Every app role requirement the application seeds, and the section that must own
# its primary control. The roster in Security mirrors these; a key missing from the
# schema is missing from V2 entirely, because the fallback scan only sees enable_*.
APP_ROLE_SECTIONS = {
    "require_member_of_create_group": ("group-workspaces-section", "workspace-types"),
    "require_member_of_create_public_workspace": (
        "public-workspaces-section",
        "workspace-types",
    ),
    "require_member_of_safety_violation_admin": ("permissions-section", "access-roles"),
    "require_member_of_feedback_admin": ("permissions-section", "access-roles"),
    "require_member_of_chat_file_upload_user": (
        "chat-file-uploads-section",
        "chat-experience",
    ),
    "require_member_of_control_center_admin": (
        "control-center-overview-section",
        "control-center-config",
    ),
    "require_member_of_control_center_dashboard_reader": (
        "control-center-overview-section",
        "control-center-config",
    ),
    "require_member_of_url_access_user": ("url-access-section", "web-research"),
    "require_member_of_deep_research_user": ("source-review-section", "web-research"),
    "require_member_of_workflow_user": ("workflow-settings-section", "workflow"),
}

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")
CARD_ID_RE = re.compile(r'class="card[^"]*"\s+id="([a-z0-9-]+)"')
APP_ROLE_DEFAULT_RE = re.compile(
    r"^\s*'(require_member_of_[a-z0-9_]+)'\s*:\s*(?:True|False)\s*,", re.MULTILINE
)
PUBLIC_NAME_LIMIT_RE = re.compile(
    r"^PUBLIC_WORKSPACE_DISPLAY_NAME_MAX_LENGTH\s*=\s*(\d+)\s*$", re.MULTILINE
)

fields_module = import_app_module("admin_settings_fields")


def read_pane(pane_id):
    """Return the raw markup for one Admin Settings pane."""
    pane_path = PANES_DIR / f"{pane_id}.html"
    assert pane_path.is_file(), f"Missing Admin Settings pane: {pane_path}"
    return pane_path.read_text(encoding="utf-8")


def collect_pane_field_names(markup):
    """Return literal form field names submitted by a pane."""
    return {name for name in FIELD_NAME_RE.findall(markup) if not JINJA_RE.search(name)}


def declared_sections():
    """Return ``key -> (section_id, field)`` for every declared field."""
    return {
        field["key"]: (section_id, field)
        for section_id, field in fields_module.iter_fields()
        if field.get("key")
    }


def nav_index():
    """Return group id, tab id and section id lookups from ADMIN_NAV."""
    section_home = {}
    tab_home = {}
    for group in ADMIN_NAV:
        for tab in group["tabs"]:
            tab_home[tab["id"]] = group["id"]
            for section in tab["sections"]:
                section_home[section["id"]] = (group["id"], tab["id"])
    return section_home, tab_home


def test_workspaces_panes_match_navigation():
    """The panes this test reads must be the ones ADMIN_NAV puts in the group."""
    print("Testing Workspaces pane list against ADMIN_NAV...")

    assert_app_version_at_least("0.261.060")

    group = next((g for g in ADMIN_NAV if g["id"] == WORKSPACES_GROUP_ID), None)
    assert group, "ADMIN_NAV no longer defines a 'workspaces' group."

    nav_tabs = {tab["id"]: tuple(s["id"] for s in tab["sections"]) for tab in group["tabs"]}

    assert set(nav_tabs) == set(WORKSPACES_PANES), (
        "The Workspaces group's tabs changed. Update WORKSPACES_PANES and the schema "
        f"together.\n  ADMIN_NAV: {sorted(nav_tabs)}\n  test: {sorted(WORKSPACES_PANES)}"
    )

    for tab_id, section_ids in nav_tabs.items():
        assert section_ids == WORKSPACES_PANES[tab_id], (
            f"Sections for the '{tab_id}' tab changed.\n"
            f"  ADMIN_NAV: {section_ids}\n  test: {WORKSPACES_PANES[tab_id]}"
        )

    print(f"  {len(nav_tabs)} tab(s) and their sections match ADMIN_NAV.")
    return True


def test_every_v1_field_is_claimed_by_the_schema():
    """A V1 Workspaces field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that every V1 Workspaces field is claimed by the schema...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    unclaimed = {}
    total = 0
    for pane_id in WORKSPACES_PANES:
        names = collect_pane_field_names(read_pane(pane_id))
        total += len(names)
        missing = sorted(names - claimed - documented)
        if missing:
            unclaimed[pane_id] = missing

    assert not unclaimed, (
        "These fields exist in the server-rendered Workspaces panes but are not "
        "described in admin_settings_fields.py, so they cannot appear in the V2 admin "
        "UI. Add a field definition, record the name in LEGACY_FIELD_NAMES if the "
        "shapes differ, or document the omission in "
        "LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT:\n"
        + "\n".join(f"  {pane}: {', '.join(names)}" for pane, names in unclaimed.items())
    )

    print(f"  All {total} V1 Workspaces field(s) are claimed by the schema.")
    return True


def test_schema_does_not_invent_workspace_fields():
    """A schema key with no V1 counterpart would save a setting nothing reads."""
    print("\nTesting that the schema does not invent Workspaces fields...")

    v1_names = set()
    for pane_id in WORKSPACES_PANES:
        v1_names |= collect_pane_field_names(read_pane(pane_id))

    workspace_sections = {
        section for sections in WORKSPACES_PANES.values() for section in sections
    }

    invented = []
    for section_id, field in fields_module.iter_fields():
        if section_id not in workspace_sections:
            continue
        key = field.get("key")
        if not key:
            continue
        legacy = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
        if not any(name in v1_names for name in legacy):
            invented.append(f"{section_id}.{key}")

    assert not invented, (
        "These schema fields have no matching field in the V1 Workspaces panes, so V2 "
        "would write settings the rest of the application never reads:\n  "
        + "\n  ".join(invented)
    )

    print("  Every Workspaces schema field maps back to a V1 field.")
    return True


def test_group_creation_polarity_is_recorded():
    """V1 submits the inverse of the stored key, which only a mapping can reconcile."""
    print("\nTesting the group creation polarity mapping...")

    legacy = fields_module.LEGACY_FIELD_NAMES.get("enable_group_creation")
    assert legacy == ["disable_group_creation"], (
        "V1 renders group creation as an inverted 'Disable Group Creation' checkbox "
        "and flips it server-side, while V2 edits enable_group_creation directly. "
        "LEGACY_FIELD_NAMES is what records that difference; without it the parity "
        f"check above cannot resolve either name. Found: {legacy!r}"
    )

    section_id, field = declared_sections()["enable_group_creation"]
    assert section_id == "group-workspaces-section", (
        f"enable_group_creation is declared under {section_id!r}, not the group "
        "workspaces section it belongs to."
    )
    assert field.get("default") is True, (
        "enable_group_creation must default to True. Declaring it positively while "
        "defaulting it off would silently forbid group creation on a fresh deployment."
    )

    print("  Group creation is declared positively and its V1 inverse is recorded.")
    return True


def test_public_display_name_limit_matches_the_application():
    """A longer value than the application allows would be truncated after saving."""
    print("\nTesting the public workspace display name limit...")

    match = PUBLIC_NAME_LIMIT_RE.search(SETTINGS_MODULE.read_text(encoding="utf-8"))
    assert match, (
        "PUBLIC_WORKSPACE_DISPLAY_NAME_MAX_LENGTH was not found in "
        "functions_settings.py; the extraction likely broke."
    )
    application_limit = int(match.group(1))

    assert fields_module.PUBLIC_WORKSPACE_DISPLAY_NAME_MAX_LENGTH == application_limit, (
        "admin_settings_fields.py mirrors this constant because functions_settings "
        "cannot be imported there. The two have drifted:\n"
        f"  schema: {fields_module.PUBLIC_WORKSPACE_DISPLAY_NAME_MAX_LENGTH}\n"
        f"  application: {application_limit}"
    )

    _section_id, field = declared_sections()["public_workspace_display_name"]
    assert field.get("max_length") == application_limit, (
        f"public_workspace_display_name declares max_length {field.get('max_length')}, "
        f"but the application truncates at {application_limit}."
    )

    print(f"  Both interfaces limit the display name to {application_limit} characters.")
    return True


def test_relocated_sections_moved_in_both_places():
    """A nav entry without its markup leaves one interface rendering nothing."""
    print("\nTesting the relocated sections...")

    section_home, _tab_home = nav_index()
    declared = declared_sections()
    problems = []

    for section_id, expected in RELOCATED_SECTIONS.items():
        home = section_home.get(section_id)
        if home is None:
            problems.append(f"{section_id}: no longer defined in ADMIN_NAV")
            continue
        if home != (expected["group"], expected["tab"]):
            problems.append(
                f"{section_id}: ADMIN_NAV places it in {home}, expected "
                f"{(expected['group'], expected['tab'])}"
            )

        if section_id not in CARD_ID_RE.findall(read_pane(expected["pane"])):
            problems.append(
                f"{section_id}: no card with that id in {expected['pane']}.html"
            )
        if section_id in CARD_ID_RE.findall(read_pane(expected["vacated_pane"])):
            problems.append(
                f"{section_id}: card is still in {expected['vacated_pane']}.html, so "
                "the same id would render twice"
            )

        field_key = expected["field"]
        entry = declared.get(field_key)
        if entry is None:
            problems.append(f"{field_key}: not declared at all")
        elif entry[0] != section_id:
            problems.append(
                f"{field_key}: declared under {entry[0]!r}, expected {section_id!r}"
            )

    assert not problems, (
        "These sections were moved to a new tab. A move has to happen in "
        "admin_settings_nav.py and in the pane markup together:\n  "
        + "\n  ".join(problems)
    )

    print(f"  All {len(RELOCATED_SECTIONS)} relocated section(s) moved in both places.")
    return True


def test_relocated_tabs_have_a_renderable_section():
    """A tab with no sections renders nothing at all in V2."""
    print("\nTesting the relocated tabs...")

    _section_home, tab_home = nav_index()
    problems = []

    for tab_id, expected_group in RELOCATED_TABS.items():
        group_id = tab_home.get(tab_id)
        if group_id is None:
            problems.append(f"{tab_id}: no longer defined in ADMIN_NAV")
            continue
        if group_id != expected_group:
            problems.append(
                f"{tab_id}: in group {group_id!r}, expected {expected_group!r}"
            )

        tab = next(
            (
                tab
                for group in ADMIN_NAV
                for tab in group["tabs"]
                if tab["id"] == tab_id
            ),
            None,
        )
        if tab is not None and not tab["sections"]:
            problems.append(
                f"{tab_id}: declares no sections, so the V2 surface -- which builds "
                "its page from group > tab > section -- has nowhere to render it"
            )

    assert not problems, (
        "These tabs were moved between groups:\n  " + "\n  ".join(problems)
    )

    print(f"  All {len(RELOCATED_TABS)} relocated tab(s) are where they belong.")
    return True


def test_every_app_role_requirement_is_declared():
    """An undeclared role gate renders nowhere in V2 and is absent from the roster."""
    print("\nTesting app role requirement declarations...")

    application_keys = sorted(
        {
            match.group(1)
            for match in APP_ROLE_DEFAULT_RE.finditer(
                SETTINGS_MODULE.read_text(encoding="utf-8")
            )
        }
    )
    assert application_keys, "No require_member_of_* defaults found; extraction broke."

    assert set(application_keys) == set(APP_ROLE_SECTIONS), (
        "The set of app role requirements changed. Declare the new one in the section "
        "that owns the feature it gates, and list it here so the roster stays "
        "complete:\n"
        f"  application: {application_keys}\n  test: {sorted(APP_ROLE_SECTIONS)}"
    )

    declared = declared_sections()
    problems = []
    for key, (expected_section, pane_id) in APP_ROLE_SECTIONS.items():
        entry = declared.get(key)
        if entry is None:
            problems.append(f"{key}: not declared at all")
            continue
        section_id, field = entry
        if section_id != expected_section:
            problems.append(
                f"{key}: declared under {section_id!r}, expected {expected_section!r}"
            )
        if field.get("type") != "switch":
            problems.append(f"{key}: declared as {field.get('type')!r}, expected 'switch'")
        if f'name="{key}"' not in read_pane(pane_id):
            problems.append(f"{key}: no name=\"{key}\" field in {pane_id}.html")

    assert not problems, (
        "The Security roster is built from declared fields, so these gaps make a role "
        "requirement unreachable in V2:\n  " + "\n  ".join(problems)
    )

    print(f"  All {len(APP_ROLE_SECTIONS)} app role requirement(s) are declared.")
    return True


def test_assignment_pickers_target_real_endpoints():
    """An id_list pointing at a route that does not exist renders an empty picker."""
    print("\nTesting id_list search endpoints against registered routes...")

    routes = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(APP_ROOT.glob("route_*.py"))
    )

    problems = []
    checked = 0
    for section_id, field in fields_module.iter_fields():
        if field.get("type") != "id_list":
            continue
        checked += 1
        endpoint = field.get("search_endpoint", "")
        if f"'{endpoint}'" not in routes and f'"{endpoint}"' not in routes:
            problems.append(f"{section_id}.{field['key']}: no route registers {endpoint!r}")

    assert not problems, (
        "These assignment pickers search an endpoint the application does not "
        "register:\n  " + "\n  ".join(problems)
    )
    assert checked, "No id_list fields were checked; the schema extraction likely broke."

    print(f"  All {checked} assignment picker(s) target a registered route.")
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
        "These schema sections are not defined in admin_settings_nav.py, so the V2 UI "
        "has nowhere to render them:\n  " + "\n  ".join(unknown)
    )

    print(
        f"  All {len(fields_module.ADMIN_SETTINGS_FIELDS)} schema section(s) exist in "
        "ADMIN_NAV."
    )
    return True


def test_v2_renderer_handles_the_new_widgets():
    """The schema can name a widget the renderer has no branch for, and nothing fails."""
    print("\nTesting the V2 renderer branches for this group...")

    page = (V2_SRC / "pages" / "AdminSettingsPage.tsx").read_text(encoding="utf-8")
    helpers = (V2_SRC / "lib" / "adminFields.ts").read_text(encoding="utf-8")

    required = (
        ("the id_list assignment picker", "field.type === 'id_list'", page),
        ("the global identities list", "case 'global-identities-list':", page),
        ("the app role roster", "case 'app-role-requirements-roster':", page),
        ("the roster's entry collector", "export function collectAppRoleEntries", helpers),
        ("the role key prefix", "require_member_of_", helpers),
    )

    missing = [description for description, fragment, source in required if fragment not in source]

    assert not missing, (
        "The V2 admin surface has no branch for these, so the section would render an "
        "empty space:\n  " + "\n  ".join(missing)
    )

    for component_dir_file in ("AssignmentPicker.tsx", "GlobalIdentitiesList.tsx", "AppRoleRoster.tsx"):
        path = V2_SRC / "components" / "admin" / component_dir_file
        assert path.is_file(), f"Missing V2 admin component: {path}"

    print(f"  All {len(required)} renderer branch(es) and 3 component file(s) are present.")
    return True


if __name__ == "__main__":
    tests = [
        test_workspaces_panes_match_navigation,
        test_every_v1_field_is_claimed_by_the_schema,
        test_schema_does_not_invent_workspace_fields,
        test_group_creation_polarity_is_recorded,
        test_public_display_name_limit_matches_the_application,
        test_relocated_sections_moved_in_both_places,
        test_relocated_tabs_have_a_renderable_section,
        test_every_app_role_requirement_is_declared,
        test_assignment_pickers_target_real_endpoints,
        test_schema_sections_exist_in_navigation,
        test_v2_renderer_handles_the_new_widgets,
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
