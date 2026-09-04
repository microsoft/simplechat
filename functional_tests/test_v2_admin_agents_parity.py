#!/usr/bin/env python3
# test_v2_admin_agents_parity.py
"""
Functional test pinning V1/V2 parity for the Admin Settings Agents & Actions group.
Version: 0.261.059
Implemented in: 0.261.059

The V2 React admin surface renders from ``admin_settings_fields.py``. A setting
present in a V1 pane but absent from that schema does not fail anything: it
simply never appears in V2, and an administrator has no way of knowing a control
they used to have is gone.

Before this group was declared, the V2 surface fell back to scanning the settings
document for ``enable_*`` booleans, which meant the Agents tab rendered nothing
at all -- not one of ``per_user_semantic_kernel``, the ``allow_*`` toggles, or
the eleven ``agents_page_*`` keys is an ``enable_*`` boolean.

This test requires each V1 field name in the panes that have been declared to be
claimed by the schema, either because the schema declares the same key, because
``LEGACY_FIELD_NAMES`` records a shape difference, or because
``LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT`` documents why there is none. It also
tracks which panes in the group are still undeclared, so finishing one without
extending this test fails rather than passing quietly.
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

GROUP_ID = "agents-actions"

# Tabs of the group whose fields the schema describes, and the sections each one
# contributes. Verified against ADMIN_NAV below so a navigation change cannot
# leave this list quietly stale.
DECLARED_PANES = {
    "agents": (
        "agents-config",
        "agent-toggles-card",
        "agents-page-customization-card",
        "agent-template-approvals-section",
    ),
    "actions": (
        "document-action-capabilities-card",
        "plugin-feature-toggles",
        "core-plugin-toggles",
        "actions-config",
    ),
    "inbound-mcp": ("inbound-mcp-configuration",),
}

# Tabs still served by the fallback scan, with the phase that declares them. The
# test asserts this is exactly the remainder, so declaring one of them fails here
# until it is moved into DECLARED_PANES with its sections.
PANES_PENDING_DECLARATION = {}

# Declared sections that hold no settings, because what belongs in them is a
# table rather than a field. The V2 surface skips a section with nothing in it,
# so this is not a broken heading; the entry records why and is checked for
# staleness once the section is filled.
SECTIONS_AWAITING_A_COMPONENT = {
    "actions-config": "Phase 5 -- the global actions table",
}

FIELD_NAME_RE = re.compile(r'\sname="([^"]+)"')
JINJA_RE = re.compile(r"\{\{|\{%")

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


def group_tabs():
    """Return the group's tabs keyed by id, straight from ADMIN_NAV."""
    group = next((g for g in ADMIN_NAV if g["id"] == GROUP_ID), None)
    assert group, f"ADMIN_NAV no longer defines an '{GROUP_ID}' group."
    return {tab["id"]: tab for tab in group["tabs"]}


def test_declared_panes_match_navigation():
    """The panes this test reads must be the ones ADMIN_NAV puts in the group."""
    print("Testing Agents & Actions pane list against ADMIN_NAV...")

    assert_app_version_at_least("0.261.059")

    tabs = group_tabs()

    covered = set(DECLARED_PANES) | set(PANES_PENDING_DECLARATION)
    assert covered == set(tabs), (
        "The Agents & Actions tabs changed. Update DECLARED_PANES and "
        "PANES_PENDING_DECLARATION together.\n"
        f"  ADMIN_NAV: {sorted(tabs)}\n  test: {sorted(covered)}"
    )

    for tab_id, section_ids in DECLARED_PANES.items():
        actual = tuple(section["id"] for section in tabs[tab_id]["sections"])
        assert actual == section_ids, (
            f"Sections for the '{tab_id}' tab changed.\n"
            f"  ADMIN_NAV: {actual}\n  test: {section_ids}"
        )

    print(f"  {len(tabs)} tab(s) accounted for, {len(DECLARED_PANES)} declared.")
    return True


def test_every_declared_pane_field_is_claimed_by_the_schema():
    """A V1 field with no V2 equivalent is invisible in the new UI."""
    print("\nTesting that every declared V1 field is claimed by the schema...")

    claimed = fields_module.get_legacy_field_names()
    documented = set(fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT)

    unclaimed = {}
    total = 0
    for pane_id in DECLARED_PANES:
        names = collect_pane_field_names(read_pane(pane_id))
        total += len(names)
        missing = sorted(names - claimed - documented)
        if missing:
            unclaimed[pane_id] = missing

    assert not unclaimed, (
        "These V1 fields have no V2 equivalent and no recorded reason. Declare "
        "them in admin_settings_fields.py, map them through LEGACY_FIELD_NAMES, "
        "or record why in LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT:\n  "
        + "\n  ".join(f"{pane}: {', '.join(names)}" for pane, names in unclaimed.items())
    )

    print(f"  All {total} V1 field name(s) across {len(DECLARED_PANES)} pane(s) are claimed.")
    return True


def test_documented_omissions_are_still_real():
    """A recorded omission for a field that no longer exists is stale."""
    print("\nTesting that documented omissions still appear in a pane...")

    pane_names = set()
    for pane_id in list(DECLARED_PANES) + list(PANES_PENDING_DECLARATION):
        pane_names |= collect_pane_field_names(read_pane(pane_id))

    # Only omissions this group is responsible for are checked here, so the
    # Appearance group can record its own without this test failing.
    group_omissions = {"orchestration_type", "max_rounds_per_agent"}
    stale = sorted(
        name
        for name in fields_module.LEGACY_FIELDS_WITHOUT_V2_EQUIVALENT
        if name in group_omissions and name not in pane_names
    )

    assert not stale, (
        "These fields are recorded as having no V2 equivalent but no longer "
        "appear in any Agents & Actions pane. Remove the entry:\n  "
        + "\n  ".join(stale)
    )

    print(f"  {len(group_omissions)} documented omission(s) still exist in V1.")
    return True


def test_declared_agent_sections_are_not_empty():
    """A named section with no fields renders as a heading over nothing."""
    print("\nTesting that every declared section owns at least one field...")

    schema = fields_module.get_admin_settings_fields()
    empty = [
        section_id
        for section_ids in DECLARED_PANES.values()
        for section_id in section_ids
        if not schema.get(section_id) and section_id not in SECTIONS_AWAITING_A_COMPONENT
    ]

    assert not empty, (
        "These sections are listed as declared but the schema has no fields for "
        "them:\n  " + "\n  ".join(empty)
    )

    stale = sorted(
        section_id
        for section_id in SECTIONS_AWAITING_A_COMPONENT
        if schema.get(section_id)
    )
    assert not stale, (
        "These sections now have fields, so their entry in "
        "SECTIONS_AWAITING_A_COMPONENT is stale and should be removed:\n  "
        + "\n  ".join(stale)
    )

    declared = sum(
        len(schema.get(section_id, ()))
        for section_ids in DECLARED_PANES.values()
        for section_id in section_ids
    )
    print(f"  {declared} field(s) across {sum(map(len, DECLARED_PANES.values()))} section(s).")
    return True


def test_the_agents_gate_chain_is_declared():
    """The dependency chain is the point of the rework, so it is pinned.

    ``/agents`` carries ``@enabled_required('enable_semantic_kernel')``, and the
    Agents page copy customises that page, so every one of those fields has to
    depend on the gate. Losing a link in the chain puts a control back on screen
    that cannot affect anything.
    """
    print("\nTesting the Agents dependency chain...")

    schema = fields_module.get_admin_settings_fields()

    def dependency_keys(field):
        return {
            dependency["key"]
            for dependency in fields_module.iter_dependencies(field)
        }

    runtime = {field["key"]: field for field in schema["agents-config"] if field.get("key")}

    assert "enable_semantic_kernel" in runtime, "The master gate is not declared."
    assert not runtime["enable_semantic_kernel"].get("depends_on"), (
        "The master gate must not itself be gated, or it could become unreachable."
    )
    assert dependency_keys(runtime["per_user_semantic_kernel"]) == {
        "enable_semantic_kernel"
    }, "Workspace Mode must depend on Enable Agents."
    assert dependency_keys(runtime["merge_global_semantic_kernel_with_workspace"]) == {
        "enable_semantic_kernel",
        "per_user_semantic_kernel",
    }, (
        "The merge toggle only means anything in Workspace Mode, so it must "
        "depend on both links of the chain rather than the outer one alone."
    )

    ungated = [
        field.get("key") or field.get("component")
        for field in schema["agents-page-customization-card"]
        if "enable_semantic_kernel" not in dependency_keys(field)
    ]
    assert not ungated, (
        "The Agents page is served behind enable_semantic_kernel, so its "
        "settings must be too. These are not:\n  " + "\n  ".join(map(str, ungated))
    )

    derived = next(
        (
            field
            for field in schema["agents-config"]
            if field.get("key") == "enable_multi_agent_orchestration"
        ),
        None,
    )
    assert derived is not None and derived.get("readonly"), (
        "enable_multi_agent_orchestration is written by the orchestration API "
        "from the chosen mode. Left undeclared it is guessed into AI Models and "
        "rendered as a switch that does nothing."
    )

    print("  Gate chain, Agents page dependencies and the derived key are declared.")
    return True


def test_workspace_permission_sections_are_conditional():
    """V1 only renders these cards in Workspace Mode; V2 must agree.

    Without the condition the section would render a set of permissions that the
    runtime ignores, because nothing reads them outside Workspace Mode.
    """
    print("\nTesting workspace permission section conditions...")

    conditions = {
        section["id"]: section.get("condition")
        for group in ADMIN_NAV
        if group["id"] == GROUP_ID
        for tab in group["tabs"]
        for section in tab["sections"]
    }

    assert conditions.get("agent-toggles-card") == "per_user_semantic_kernel", (
        "Workspace Agent Permissions must be conditional on Workspace Mode."
    )
    assert conditions.get("agent-template-approvals-section") == (
        "enable_agent_template_gallery"
    ), "Agent Template Approvals must stay conditional on the gallery toggle."

    print("  Conditional sections declare the gate they belong to.")
    return True


if __name__ == "__main__":
    tests = [
        test_declared_panes_match_navigation,
        test_every_declared_pane_field_is_claimed_by_the_schema,
        test_documented_omissions_are_still_real,
        test_declared_agent_sections_are_not_empty,
        test_the_agents_gate_chain_is_declared,
        test_workspace_permission_sections_are_conditional,
    ]
    results = [test() for test in tests]
    print(f"\nResults: {sum(bool(r) for r in results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
