#!/usr/bin/env python3
# test_workspace_section_order.py
"""
Functional test for the canonical workspace section order.
Version: 0.250.211
Implemented in: 0.250.211

This test ensures every surface that lists workspace sections renders them in the
canonical order of operations (Documents, Prompts, Identities, Sync, Endpoints,
Actions, Agents, Workflows), and that each surface shows exactly the same sections
for a given set of feature flags so a navigation link can never point at a tab that
was never rendered.
"""

import itertools
import re
import traceback
from pathlib import Path

from jinja2 import Environment

from test_support.versioning import assert_app_version_at_least

IMPLEMENTED_VERSION = "0.250.211"

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "application" / "single_app" / "templates"
WORKSPACE_TEMPLATE = TEMPLATE_DIR / "workspace.html"
GROUP_TEMPLATE = TEMPLATE_DIR / "group_workspaces.html"
SIDEBAR_TEMPLATE = TEMPLATE_DIR / "_sidebar_nav.html"
PUBLIC_TEMPLATE = TEMPLATE_DIR / "public_workspaces.html"
MANAGE_PUBLIC_TEMPLATE = TEMPLATE_DIR / "manage_public_workspace.html"

CANONICAL_ORDER = [
    "documents",
    "prompts",
    "identities",
    "sync",
    "endpoints",
    "actions",
    "agents",
    "workflows",
]

NAV_BUTTON_RE = re.compile(r'\bid="([a-z-]+-tab-btn)"')
SELECT_OPTION_RE = re.compile(r'<option value="([a-z-]+-tab-btn)"')
SIDEBAR_LINK_RE = re.compile(r'\bdata-tab="([a-z-]+-tab)"')

PERSONAL_FLAG_NAMES = (
    "file_sync_enabled",
    "enable_semantic_kernel",
    "per_user_semantic_kernel",
    "allow_user_agents",
    "allow_user_plugins",
    "allow_user_workflows",
    "allow_user_custom_endpoints",
    "enable_multi_model_endpoints",
)

GROUP_FLAG_NAMES = (
    "file_sync_enabled",
    "enable_semantic_kernel",
    "per_user_semantic_kernel",
    "allow_group_agents",
    "allow_group_plugins",
    "allow_group_workflows",
    "allow_group_custom_endpoints",
    "enable_multi_model_endpoints",
)


def read_template(template_path):
    return template_path.read_text(encoding="utf-8")


def extract_block(source, start_pattern, end_token, label):
    """Return the template source for a single markup block, including its wrapper tags."""
    start_match = re.search(start_pattern, source)
    assert start_match, f"Could not locate the opening tag for {label}."

    end_index = source.find(end_token, start_match.end())
    assert end_index != -1, f"Could not locate the closing {end_token} for {label}."

    return source[start_match.start():end_index + len(end_token)]


def extract_set_statement(source, variable_name):
    """Return the template's own {% set %} statement so gating is exercised as written."""
    set_match = re.search(r"\{%-?\s*set\s+" + re.escape(variable_name) + r"\s*=.*?%\}", source)
    assert set_match, f"Could not locate the {variable_name} set statement."
    return set_match.group(0)


def section_key(token):
    """Normalize a tab identifier into its canonical section key."""
    name = token
    for suffix in ("-tab-btn", "-tab"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break

    if name.startswith("group-"):
        name = name[len("group-"):]

    # The Actions section is still wired up under its historical "plugins" identifier.
    if name == "plugins":
        name = "actions"

    return name


def render_sections(block_source, pattern, context, prelude=""):
    """Render a section list under the given flags and return its section keys in DOM order."""
    template = Environment(autoescape=True).from_string(prelude + block_source)
    rendered = template.render(**context)
    return [section_key(token) for token in pattern.findall(rendered)]


def build_flags(flag_names, values):
    return dict(zip(flag_names, values))


def build_context(flags, settings_keys):
    settings = {key: flags[key] for key in settings_keys}
    return {
        "settings": settings,
        "sidebar_settings": settings,
        "file_sync_enabled": flags["file_sync_enabled"],
        "nav_layout": "",
    }


def personal_context(flags):
    return build_context(flags, [name for name in PERSONAL_FLAG_NAMES if name != "file_sync_enabled"])


def group_context(flags):
    return build_context(flags, [name for name in GROUP_FLAG_NAMES if name != "file_sync_enabled"])


def assert_canonical_subsequence(sections, label, flags):
    """Assert the rendered sections follow the canonical order and contain no duplicates."""
    unknown = [section for section in sections if section not in CANONICAL_ORDER]
    assert not unknown, f"{label} rendered unknown sections {unknown} with flags {flags}."

    assert len(set(sections)) == len(sections), (
        f"{label} rendered duplicate sections {sections} with flags {flags}."
    )

    positions = [CANONICAL_ORDER.index(section) for section in sections]
    assert positions == sorted(positions), (
        f"{label} order {sections} does not follow the canonical order "
        f"{CANONICAL_ORDER} with flags {flags}."
    )


def build_personal_surfaces():
    workspace_source = read_template(WORKSPACE_TEMPLATE)
    sidebar_source = read_template(SIDEBAR_TEMPLATE)
    identities_set = extract_set_statement(workspace_source, "workspace_identities_enabled")

    return {
        "personal nav tabs": {
            "block": extract_block(
                workspace_source,
                r'<ul class="nav nav-tabs[^>]*id="workspaceTab"[^>]*>',
                "</ul>",
                "the personal workspace nav tabs",
            ),
            "pattern": NAV_BUTTON_RE,
            "prelude": identities_set,
        },
        "personal section select": {
            "block": extract_block(
                workspace_source,
                r'<select[^>]*id="workspace-section-select"[^>]*>',
                "</select>",
                "the personal workspace section select",
            ),
            "pattern": SELECT_OPTION_RE,
            "prelude": identities_set,
        },
        "personal sidebar submenu": {
            "block": extract_block(
                sidebar_source,
                r'<ul[^>]*id="personal-workspace-submenu"[^>]*>',
                "</ul>",
                "the personal sidebar submenu",
            ),
            "pattern": SIDEBAR_LINK_RE,
            "prelude": "",
        },
    }


def build_group_surfaces():
    group_source = read_template(GROUP_TEMPLATE)
    sidebar_source = read_template(SIDEBAR_TEMPLATE)
    identities_set = extract_set_statement(group_source, "group_workspace_identities_enabled")

    return {
        "group nav tabs": {
            "block": extract_block(
                group_source,
                r'<ul class="nav nav-tabs[^>]*id="groupWorkspaceTab"[^>]*>',
                "</ul>",
                "the group workspace nav tabs",
            ),
            "pattern": NAV_BUTTON_RE,
            "prelude": identities_set,
        },
        "group section select": {
            "block": extract_block(
                group_source,
                r'<select[^>]*id="group-workspace-section-select"[^>]*>',
                "</select>",
                "the group workspace section select",
            ),
            "pattern": SELECT_OPTION_RE,
            "prelude": identities_set,
        },
        "group sidebar submenu": {
            "block": extract_block(
                sidebar_source,
                r'<ul[^>]*id="group-workspace-submenu"[^>]*>',
                "</ul>",
                "the group sidebar submenu",
            ),
            "pattern": SIDEBAR_LINK_RE,
            "prelude": "",
        },
    }


def render_surfaces(surfaces, context):
    return {
        label: render_sections(surface["block"], surface["pattern"], context, surface["prelude"])
        for label, surface in surfaces.items()
    }


def test_version_reflects_workspace_section_order():
    """Verify the application version is at least the implementation version."""
    print("Testing workspace section order version marker...")

    assert_app_version_at_least(
        IMPLEMENTED_VERSION,
        reason="Workspace section reordering shipped in this version.",
    )

    print("Version marker verified.")


def test_every_section_surface_uses_the_canonical_order():
    """Verify all six workspace section lists render the canonical order when fully enabled."""
    print("Testing canonical workspace section order...")

    personal_flags = build_flags(PERSONAL_FLAG_NAMES, [True] * len(PERSONAL_FLAG_NAMES))
    group_flags = build_flags(GROUP_FLAG_NAMES, [True] * len(GROUP_FLAG_NAMES))

    rendered = render_surfaces(build_personal_surfaces(), personal_context(personal_flags))
    rendered.update(render_surfaces(build_group_surfaces(), group_context(group_flags)))

    for label, sections in rendered.items():
        assert sections == CANONICAL_ORDER, (
            f"{label} should render {CANONICAL_ORDER} when every feature is enabled, got {sections}."
        )

    print("Canonical workspace section order verified across all six surfaces.")


def test_disabled_features_only_remove_sections():
    """Verify every flag combination keeps the canonical order and only hides sections."""
    print("Testing workspace section order across feature flag combinations...")

    personal_surfaces = build_personal_surfaces()
    group_surfaces = build_group_surfaces()
    always_present = ["documents", "prompts"]

    for values in itertools.product([True, False], repeat=len(PERSONAL_FLAG_NAMES)):
        flags = build_flags(PERSONAL_FLAG_NAMES, values)
        for label, sections in render_surfaces(personal_surfaces, personal_context(flags)).items():
            assert_canonical_subsequence(sections, label, flags)
            assert sections[:2] == always_present, (
                f"{label} should always start with {always_present}, got {sections} with flags {flags}."
            )

    for values in itertools.product([True, False], repeat=len(GROUP_FLAG_NAMES)):
        flags = build_flags(GROUP_FLAG_NAMES, values)
        for label, sections in render_surfaces(group_surfaces, group_context(flags)).items():
            assert_canonical_subsequence(sections, label, flags)
            assert sections[:2] == always_present, (
                f"{label} should always start with {always_present}, got {sections} with flags {flags}."
            )

    print("Workspace section order verified across all feature flag combinations.")


def test_section_surfaces_stay_in_gating_lockstep():
    """Verify tabs, the section select, and the sidebar expose identical sections."""
    print("Testing workspace section gating parity...")

    personal_surfaces = build_personal_surfaces()
    group_surfaces = build_group_surfaces()

    for values in itertools.product([True, False], repeat=len(PERSONAL_FLAG_NAMES)):
        flags = build_flags(PERSONAL_FLAG_NAMES, values)
        rendered = render_surfaces(personal_surfaces, personal_context(flags))
        expected = rendered["personal nav tabs"]
        for label, sections in rendered.items():
            assert sections == expected, (
                f"{label} exposes {sections} but the personal nav tabs expose {expected} "
                f"with flags {flags}."
            )

    for values in itertools.product([True, False], repeat=len(GROUP_FLAG_NAMES)):
        flags = build_flags(GROUP_FLAG_NAMES, values)
        rendered = render_surfaces(group_surfaces, group_context(flags))
        expected = rendered["group nav tabs"]
        for label, sections in rendered.items():
            assert sections == expected, (
                f"{label} exposes {sections} but the group nav tabs expose {expected} "
                f"with flags {flags}."
            )

    print("Workspace section gating parity verified for personal and group surfaces.")


def test_group_identities_navigation_markers_survive_reordering():
    """Verify the permission-aware group Identities markers are preserved after the move."""
    print("Testing group identities navigation markers...")

    group_source = read_template(GROUP_TEMPLATE)
    sidebar_source = read_template(SIDEBAR_TEMPLATE)

    assert 'data-group-identities-section-option hidden disabled' in group_source, (
        "Group identities section option marker missing after reordering."
    )
    assert 'class="nav-item d-none" role="presentation" data-group-identities-tab-nav' in group_source, (
        "Group identities tab nav marker missing after reordering."
    )
    assert '<li class="nav-item d-none" data-group-identities-sidebar-nav>' in sidebar_source, (
        "Group identities sidebar nav marker missing after reordering."
    )

    print("Group identities navigation markers verified.")


def test_public_workspace_surfaces_follow_the_canonical_order():
    """Verify the public workspace pages already satisfy the canonical relative order."""
    print("Testing public workspace section order...")

    public_source = read_template(PUBLIC_TEMPLATE)
    documents_index = public_source.find('id="public-docs-tab-btn"')
    prompts_index = public_source.find('id="public-prompts-tab-btn"')

    assert documents_index != -1, "Public workspace documents tab button missing."
    assert prompts_index != -1, "Public workspace prompts tab button missing."
    assert documents_index < prompts_index, (
        "Public workspace order should be Documents -> Prompts."
    )

    manage_source = read_template(MANAGE_PUBLIC_TEMPLATE)
    identities_index = manage_source.find('id="identities-tab"')
    sync_index = manage_source.find('id="sync-tab"')

    assert identities_index != -1, "Public workspace management identities tab missing."
    assert sync_index != -1, "Public workspace management sync tab missing."
    assert identities_index < sync_index, (
        "Public workspace management order should place Identities before Sync."
    )

    print("Public workspace section order verified.")


def run_tests():
    tests = [
        test_version_reflects_workspace_section_order,
        test_every_section_surface_uses_the_canonical_order,
        test_disabled_features_only_remove_sections,
        test_section_surfaces_stay_in_gating_lockstep,
        test_group_identities_navigation_markers_survive_reordering,
        test_public_workspace_surfaces_follow_the_canonical_order,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("Test passed")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)
