#!/usr/bin/env python3
# test_v2_admin_workflow_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings Workflow group.
Version: 0.261.059
Implemented in: 0.261.059

The Workflow group rendered completely empty in the V2 React admin surface. The
navigation defined the group, the tab and the section, but nothing described what
the section contains, and the fallback that keeps undescribed groups usable only
scans for ``enable_*`` booleans. Every workflow setting is named ``allow_*``,
``require_*``, ``workflow_max_*`` or ``group_workflow_*``, so the scan had nothing
to find and the section was skipped for having no fields at all.

That is a worse failure than a misfiled toggle, because there is no partial
rendering to notice. These checks make it a test failure:

  - the panes and sections this test reads are the ones ADMIN_NAV defines;
  - every form field the V1 pane submits is claimed by the schema;
  - the schema invents no workflow field that V1 does not have;
  - the section is not empty, which is the specific regression;
  - the two numeric limits share identical bounds with the V1 inputs, since a V2
    control offering a wider range would save a value V1 refuses to show; and
  - the gating chain matches the capability each sub-setting belongs to.
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

WORKFLOW_GROUP_ID = "workflow"
WORKFLOW_PANES = {
    "workflow": ("workflow-settings-section",),
}
WORKFLOW_SECTION_ID = "workflow-settings-section"

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")
NUMBER_BLOCK_RE = re.compile(r'<input[^>]*type="number"(?P<attrs>[^>]*)>', re.DOTALL)
ATTR_RE = re.compile(r'(\w[\w-]*)="([^"]*)"')

# Which capability each sub-setting belongs to. The two run limits are absent on
# purpose: they bound personal *and* group runs, and `depends_on` names a single
# key, so gating either one on a single capability would hide a live limit from
# an administrator who only uses the other.
EXPECTED_DEPENDENCIES = {
    "require_member_of_workflow_user": "allow_user_workflows",
    "require_group_assignment_for_group_workflows": "allow_group_workflows",
    "group_workflow_allowed_group_ids": "require_group_assignment_for_group_workflows",
}

UNGATED_KEYS = ("workflow_max_auto_invoke_attempts", "workflow_max_tasks")

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


def workflow_fields():
    """Return the schema entries filed under the workflow section."""
    return fields_module.get_admin_settings_fields().get(WORKFLOW_SECTION_ID, [])


def test_workflow_panes_match_navigation():
    """The pane this test reads must be the one ADMIN_NAV puts in the group."""
    print("Testing Workflow pane list against ADMIN_NAV...")

    assert_app_version_at_least("0.261.059")

    group = next((g for g in ADMIN_NAV if g["id"] == WORKFLOW_GROUP_ID), None)
    assert group, "ADMIN_NAV no longer defines a 'workflow' group."

    nav_tabs = {tab["id"]: tuple(s["id"] for s in tab["sections"]) for tab in group["tabs"]}

    assert set(nav_tabs) == set(WORKFLOW_PANES), (
        "The Workflow group's tabs changed. Update WORKFLOW_PANES and the schema "
        f"together.\n  ADMIN_NAV: {sorted(nav_tabs)}\n  test: {sorted(WORKFLOW_PANES)}"
    )

    for tab_id, section_ids in nav_tabs.items():
        assert section_ids == WORKFLOW_PANES[tab_id], (
            f"Sections for the '{tab_id}' tab changed.\n"
            f"  ADMIN_NAV: {section_ids}\n  test: {WORKFLOW_PANES[tab_id]}"
        )

    print(f"  {len(nav_tabs)} tab(s) and their sections match ADMIN_NAV.")
    return True


def test_workflow_section_is_described():
    """An undescribed section renders as nothing, which is the original bug."""
    print("\nTesting that the workflow section has declared fields...")

    declared = workflow_fields()

    assert declared, (
        "admin_settings_fields.py declares no fields for "
        f"{WORKFLOW_SECTION_ID!r}. None of the workflow settings are named enable_*, "
        "so the V2 surface's fallback scan cannot find them either, and the whole "
        "Workflow group renders empty."
    )

    print(f"  {len(declared)} workflow field(s) declared.")
    return True


def test_every_v1_field_is_claimed_by_the_schema():
    """A V1 workflow field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that every V1 Workflow field is claimed by the schema...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    unclaimed = {}
    total = 0
    for pane_id in WORKFLOW_PANES:
        names = collect_pane_field_names(read_pane(pane_id))
        total += len(names)
        missing = sorted(names - claimed - documented)
        if missing:
            unclaimed[pane_id] = missing

    assert not unclaimed, (
        "These fields exist in the server-rendered Workflow pane but are not "
        "described in admin_settings_fields.py, so they cannot appear in the V2 "
        "admin UI. Add a field definition, record the name in LEGACY_FIELD_NAMES "
        "if the shapes differ, or document the omission in "
        "LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT:\n"
        + "\n".join(f"  {pane}: {', '.join(names)}" for pane, names in unclaimed.items())
    )

    print(f"  All {total} V1 Workflow field(s) are claimed by the schema.")
    return True


def test_schema_does_not_invent_workflow_fields():
    """A schema key with no V1 counterpart would save a setting nothing reads."""
    print("\nTesting that the schema does not invent Workflow fields...")

    v1_names = set()
    for pane_id in WORKFLOW_PANES:
        v1_names |= collect_pane_field_names(read_pane(pane_id))

    invented = []
    for field in workflow_fields():
        key = field.get("key")
        if not key:
            continue
        legacy = fields_module.LEGACY_FIELD_NAMES.get(key, [key])
        if not any(name in v1_names for name in legacy):
            invented.append(f"{WORKFLOW_SECTION_ID}.{key}")

    assert not invented, (
        "These schema fields have no matching field in the V1 Workflow pane, so V2 "
        "would write settings the rest of the application never reads:\n  "
        + "\n  ".join(invented)
    )

    print("  Every Workflow schema field maps back to a V1 field.")
    return True


def test_number_bounds_match_v1():
    """A wider range in V2 would save a value the V1 input refuses to show."""
    print("\nTesting number bounds against V1...")

    v1_numbers = {}
    for pane_id in WORKFLOW_PANES:
        for match in NUMBER_BLOCK_RE.finditer(read_pane(pane_id)):
            attrs = dict(ATTR_RE.findall(match.group("attrs")))
            name = attrs.get("name")
            if not name or JINJA_RE.search(name):
                continue
            v1_numbers[name] = attrs

    assert v1_numbers, "No number inputs were found in the Workflow pane."

    mismatches = []
    checked = 0
    for field in workflow_fields():
        if field.get("type") != "number":
            continue
        attrs = v1_numbers.get(field.get("key"))
        if not attrs:
            mismatches.append(f"{field.get('key')}: no number input in the V1 pane")
            continue
        for schema_prop, html_attr in (("min", "min"), ("max", "max"), ("step", "step")):
            if str(field.get(schema_prop)) != attrs.get(html_attr):
                mismatches.append(
                    f"{field['key']}.{schema_prop}: schema {field.get(schema_prop)} "
                    f"!= template {attrs.get(html_attr)}"
                )
        checked += 1

    assert not mismatches, (
        "These number controls differ between interfaces:\n  " + "\n  ".join(mismatches)
    )
    assert checked == len(v1_numbers), (
        f"The V1 pane has {len(v1_numbers)} number input(s) but the schema declares "
        f"{checked}. Every one must be described or it is unreachable in V2."
    )

    print(f"  {checked} number control(s) share identical bounds.")
    return True


def test_sub_settings_are_gated_by_their_capability():
    """A sub-setting gated on the wrong capability hides while its feature is live."""
    print("\nTesting the workflow gating chain...")

    declared = {field["key"]: field for field in workflow_fields() if field.get("key")}

    problems = []
    for key, expected_gate in EXPECTED_DEPENDENCIES.items():
        field = declared.get(key)
        if field is None:
            problems.append(f"{key}: not declared")
            continue
        # Read through the module's own iterator: a field may declare one
        # condition or a list of them, and a list means every condition holds.
        # Treating the list shape as a dict crashes rather than reporting.
        conditions = list(fields_module.iter_field_dependencies(field))
        gates = [c.get("key") for c in conditions]
        if expected_gate not in gates:
            problems.append(f"{key}: gated on {gates!r}, expected {expected_gate!r}")
            continue
        gate = next(c for c in conditions if c.get("key") == expected_gate)
        if gate.get("equals") is not True:
            problems.append(f"{key}: gate expects {gate.get('equals')!r}, not True")

    for key in UNGATED_KEYS:
        field = declared.get(key)
        if field is None:
            problems.append(f"{key}: not declared")
            continue
        if field.get("depends_on"):
            gates = [c.get("key") for c in fields_module.iter_field_dependencies(field)]
            problems.append(
                f"{key}: gated on {gates!r}. It bounds both "
                "personal and group runs, so gating it on one capability hides a live "
                "limit from administrators who use the other."
            )

    assert not problems, (
        "The workflow gating chain does not match the capabilities it belongs to:\n  "
        + "\n  ".join(problems)
    )

    print(
        f"  {len(EXPECTED_DEPENDENCIES)} gated and {len(UNGATED_KEYS)} ungated "
        "field(s) are correct."
    )
    return True


def test_group_assignment_uses_the_group_picker():
    """Stored as a list of ids, so a text control would save unreadable state."""
    print("\nTesting the group assignment control...")

    declared = {field["key"]: field for field in workflow_fields() if field.get("key")}
    field = declared.get("group_workflow_allowed_group_ids")

    assert field, "group_workflow_allowed_group_ids is not declared."
    assert field.get("type") == "group_picker", (
        f"group_workflow_allowed_group_ids is declared as {field.get('type')!r}. It "
        "stores a list of group ids, so it needs the group_picker control."
    )
    assert field.get("search_endpoint"), (
        "The group picker has no search_endpoint, so it cannot resolve an assigned id "
        "to a group name or search for another."
    )
    assert "group_picker" not in fields_module.NON_PATCHABLE_TYPES, (
        "group_picker is marked non-patchable, so the assignment could not save with "
        "the toggle that gates it. Requiring assignment and choosing the assigned "
        "groups is one decision; saving them apart locks every group out in between."
    )

    print("  The assignment is a patchable group picker with a search endpoint.")
    return True


def test_group_picker_endpoint_exists_and_is_admin_only():
    """A picker pointing at no route renders but can never resolve a group."""
    print("\nTesting the group picker's search endpoint...")

    source = (
        REPO_ROOT / "application" / "single_app" / "route_backend_v2.py"
    ).read_text(encoding="utf-8")

    endpoints = {
        field["search_endpoint"]
        for field in workflow_fields()
        if field.get("type") == "group_picker" and field.get("search_endpoint")
    }
    assert endpoints, "No group picker declares a search endpoint."

    problems = []
    for endpoint in sorted(endpoints):
        # Capture everything between the route decorator and the handler, rather
        # than modelling decorator syntax: the chain mixes bare decorators with
        # ones taking nested calls, and a regex precise enough to parse that is
        # easier to get wrong than the thing it checks.
        route = re.search(
            r'@bp\.route\(\s*"' + re.escape(endpoint) + r'".*?\n'
            r'(?P<decorators>(?:[ \t]*@.*\n)*)'
            r'[ \t]*def ',
            source,
        )
        if not route:
            problems.append(
                f"{endpoint}: no matching @bp.route in route_backend_v2.py"
            )
            continue

        decorators = route.group("decorators")
        # An unauthenticated or merely signed-in group directory would let any user
        # enumerate every group in the tenant, which the member-facing directory
        # deliberately does not do.
        for required in ("@login_required", "@admin_required", "@swagger_route"):
            if required not in decorators:
                problems.append(f"{endpoint}: missing {required}")

    assert not problems, (
        "The group picker's endpoint is missing or insufficiently guarded:\n  "
        + "\n  ".join(problems)
    )

    print(f"  {len(endpoints)} picker endpoint(s) exist and are admin-only.")
    return True


def test_group_picker_normalizes_like_v1():
    """V2 must store the shape V1 stores, including the ids it drops."""
    print("\nTesting group picker normalization...")

    group_id = "11111111-1111-1111-1111-111111111111"
    other_id = "22222222-2222-2222-2222-222222222222"

    cases = (
        ([group_id, group_id], [group_id], "duplicates are collapsed"),
        ([group_id, "not-a-uuid"], [group_id], "non-uuid ids are dropped"),
        (f'["{group_id}", "{other_id}"]', [group_id, other_id], "a JSON string parses"),
        ([], [], "an empty assignment stays empty"),
    )

    problems = []
    for value, expected, description in cases:
        normalized, errors, _warnings = fields_module.normalize_admin_settings_updates(
            {"group_workflow_allowed_group_ids": value}, {}
        )
        if errors:
            problems.append(f"{description}: rejected with {errors}")
            continue
        actual = normalized.get("group_workflow_allowed_group_ids")
        if actual != expected:
            problems.append(f"{description}: got {actual!r}, expected {expected!r}")

    assert not problems, (
        "The group picker does not normalize the way the server-rendered form does:\n  "
        + "\n  ".join(problems)
    )

    print(f"  {len(cases)} normalization case(s) match V1.")
    return True


if __name__ == "__main__":
    tests = [
        test_workflow_panes_match_navigation,
        test_workflow_section_is_described,
        test_every_v1_field_is_claimed_by_the_schema,
        test_schema_does_not_invent_workflow_fields,
        test_number_bounds_match_v1,
        test_sub_settings_are_gated_by_their_capability,
        test_group_assignment_uses_the_group_picker,
        test_group_picker_endpoint_exists_and_is_admin_only,
        test_group_picker_normalizes_like_v1,
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
