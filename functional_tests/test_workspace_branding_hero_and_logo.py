# test_workspace_branding_hero_and_logo.py
"""
Functional test for workspace branding hero and logo support.
Version: 0.241.177
Implemented in: 0.241.125

This test ensures that group and public workspace branding metadata, logo
endpoints, and hero UI hooks remain wired across the backend routes, manage
pages, and active workspace pages. Updated in 0.241.146 to validate that active
workspace hero cards render before page selectors without redundant headings.
Updated in 0.241.150 to validate compact public workspace selector controls.
Updated in 0.241.151 to validate public workspace dropdown search wiring.
Updated in 0.241.152 to keep public workspace search visible for any list size.
Updated in 0.241.176 to validate custom hero color swatches for group and
public workspace manage pages.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT_DIR, "application", "single_app", "config.py")
FUNCTIONS_GROUP_FILE = os.path.join(ROOT_DIR, "application", "single_app", "functions_group.py")
FUNCTIONS_PUBLIC_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "functions_public_workspaces.py",
)
GROUP_ROUTES_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "route_backend_groups.py",
)
PUBLIC_ROUTES_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "route_backend_public_workspaces.py",
)
MANAGE_GROUP_TEMPLATE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "templates",
    "manage_group.html",
)
MANAGE_PUBLIC_TEMPLATE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "templates",
    "manage_public_workspace.html",
)
GROUP_WORKSPACES_TEMPLATE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "templates",
    "group_workspaces.html",
)
PUBLIC_WORKSPACES_TEMPLATE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "templates",
    "public_workspaces.html",
)
PUBLIC_WORKSPACE_SCRIPT = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "public",
    "public_workspace.js",
)
MANAGE_GROUP_SCRIPT = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "group",
    "manage_group.js",
)
MANAGE_PUBLIC_SCRIPT = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "public",
    "manage_public_workspace.js",
)


def read_file(path):
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def assert_required_snippets(content, required_snippets, label):
    missing = [snippet for snippet in required_snippets if snippet not in content]
    assert not missing, f"Missing required {label} snippets: {missing}"


def assert_ordered_snippets(content, ordered_snippets, label):
    """Verify snippets appear in the expected order."""
    previous_index = -1
    for snippet in ordered_snippets:
        current_index = content.find(snippet)
        assert current_index != -1, f"Missing ordered {label} snippet: {snippet}"
        assert current_index > previous_index, f"Snippet out of order for {label}: {snippet}"
        previous_index = current_index


def test_workspace_models_and_routes_include_branding_fields():
    """Verify branding fields and logo endpoints remain present in the backend."""
    print("[check] Testing workspace branding backend wiring...")

    group_content = read_file(FUNCTIONS_GROUP_FILE)
    public_content = read_file(FUNCTIONS_PUBLIC_FILE)
    group_routes = read_file(GROUP_ROUTES_FILE)
    public_routes = read_file(PUBLIC_ROUTES_FILE)

    assert_required_snippets(
        group_content,
        [
            '"heroColor": DEFAULT_WORKSPACE_HERO_COLOR',
            '"logoBase64": ""',
            '"logoVersion": 1',
        ],
        "group model",
    )
    assert_required_snippets(
        public_content,
        [
            '"heroColor": DEFAULT_WORKSPACE_HERO_COLOR',
            '"logoBase64": ""',
            '"logoVersion": 1',
            '"heroColor": normalize_workspace_hero_color(ws_doc.get("heroColor"))',
        ],
        "public workspace model",
    )
    assert_required_snippets(
        group_routes,
        [
            '"heroColor": normalize_workspace_hero_color',
            'logo_metadata = get_workspace_logo_metadata(g)',
            '**logo_metadata,',
            '@app.route("/api/groups/<group_id>/logo", methods=["GET"])',
            '@app.route("/api/groups/<group_id>/logo", methods=["POST"])',
        ],
        "group route",
    )
    assert_required_snippets(
        public_routes,
        [
            '"heroColor": normalize_workspace_hero_color',
            'logo_metadata = get_workspace_logo_metadata(ws)',
            '**logo_metadata,',
            '@app.route("/api/public_workspaces/<ws_id>/logo", methods=["GET"])',
            '@app.route("/api/public_workspaces/<ws_id>/logo", methods=["POST"])',
        ],
        "public workspace route",
    )

    print("[pass] Workspace branding backend wiring passed")


def test_workspace_manage_and_active_pages_include_branding_hooks():
    """Verify the updated pages retain hero, logo, and manage-button hooks."""
    print("[check] Testing workspace branding UI hooks...")

    manage_group_template = read_file(MANAGE_GROUP_TEMPLATE)
    manage_public_template = read_file(MANAGE_PUBLIC_TEMPLATE)
    group_workspaces_template = read_file(GROUP_WORKSPACES_TEMPLATE)
    public_workspaces_template = read_file(PUBLIC_WORKSPACES_TEMPLATE)
    public_workspace_script = read_file(PUBLIC_WORKSPACE_SCRIPT)
    manage_group_script = read_file(MANAGE_GROUP_SCRIPT)
    manage_public_script = read_file(MANAGE_PUBLIC_SCRIPT)

    assert_required_snippets(
        manage_group_template,
        [
            'id="groupHero"',
            'id="groupLogoImage"',
            'id="groupLogoFile"',
            'id="selectedColor"',
            'id="customHeroColor"',
            'aria-label="Custom hero color"',
        ],
        "manage group template",
    )
    assert_required_snippets(
        manage_public_template,
        [
            'id="workspaceHero"',
            'id="workspaceLogoImage"',
            'id="workspaceLogoFile"',
            'id="selectedColor"',
            'id="customHeroColor"',
            'aria-label="Custom hero color"',
        ],
        "manage public template",
    )
    assert_required_snippets(
        manage_group_script,
        [
            'initializeColorPicker();',
            'updateGroupHeroMedia(group);',
            'const response = await fetch(`/api/groups/${groupId}/logo`',
            "const logoInput = document.getElementById('groupLogoFile');",
            'await uploadGroupLogo(logoFile);',
            "$('#customHeroColor').on('input change'",
            "customColorInput.addClass('selected');",
            'function normalizeWorkspaceHeroColor(color)',
        ],
        "manage group script",
    )
    assert_required_snippets(
        manage_public_script,
        [
            'updateWorkspaceHeroMedia(workspace);',
            'const response = await fetch(`/api/public_workspaces/${workspaceId}/logo`',
            "const logoInput = document.getElementById('workspaceLogoFile');",
            'await uploadWorkspaceLogo(logoFile);',
            'updateProfileHero(ws, owner);',
            "$('#customHeroColor').on('input change'",
            "customColorInput.addClass('selected');",
            'function normalizeWorkspaceHeroColor(color)',
        ],
        "manage public script",
    )
    assert_required_snippets(
        group_workspaces_template,
        [
            'id="active-group-hero"',
            'id="manage-active-group-btn"',
            'function updateActiveGroupHero(activeGroup)',
            'function updateManageGroupButton(activeGroup)',
        ],
        "group workspace template",
    )
    assert '<h2>Group Workspace</h2>' not in group_workspaces_template
    assert_ordered_snippets(
        group_workspaces_template,
        [
            '<div class="container workspace-page">',
            '<div class="workspace-page-header">',
            '<div class="workspace-hero-card d-none" id="active-group-hero">',
            '<!-- Group Selector and Role Display -->',
        ],
        "group workspace hero placement",
    )
    assert_required_snippets(
        public_workspaces_template,
        [
            'id="active-public-hero"',
            'id="manage-active-public-btn"',
        ],
        "public workspace template",
    )
    assert '<h2>Public Workspace</h2>' not in public_workspaces_template
    assert_ordered_snippets(
        public_workspaces_template,
        [
            '<div class="container">',
            '<div class="workspace-hero-card d-none" id="active-public-hero">',
            'id="public-selector-row"',
        ],
        "public workspace hero placement",
    )
    assert_required_snippets(
        public_workspaces_template,
        [
            'id="public-selector-row"',
            'class="public-role-pill"',
            'id="public-selector-actions"',
            'id="manage-active-public-btn"',
            'id="btn-my-publics"',
        ],
        "public workspace compact selector",
    )
    assert 'id="btn-change-public"' not in public_workspaces_template
    assert "Change Active Workspace" not in public_workspaces_template
    assert "Your role in" not in public_workspaces_template
    assert 'id="active-public-name-role"' not in public_workspaces_template
    assert_required_snippets(
        public_workspace_script,
        [
            'function updateActivePublicHero(activeWorkspace)',
            'function updateManagePublicWorkspaceLink(activeWorkspace)',
            'heroLogo.src = `/api/public_workspaces/${activeWorkspace.id}/logo',
            'function activateSelectedPublic(publicId)',
            'activateSelectedPublic(w.id);',
            "fetch('/api/public_workspaces?page_size=1000')",
            "fetch('/api/public_workspaces/setActive'",
            'function filterPublicDropdownItems()',
            'const shouldShowSearch = userPublics.length > 0;',
            "publicSearchInput.addEventListener('input', filterPublicDropdownItems);",
            'No public workspaces are available. Select My Workspaces to create one.',
        ],
        "public workspace script",
    )
    assert "btnChangePublic" not in public_workspace_script
    assert "active-public-name-role" not in public_workspace_script

    print("[pass] Workspace branding UI hooks passed")


def test_config_version_is_bumped_for_workspace_hero_layout_changes():
    """Verify config.py reflects the workspace hero layout change version."""
    print("[check] Testing config version bump...")

    config_content = read_file(CONFIG_FILE)
    assert 'VERSION = "0.241.177"' in config_content, "Expected config.py version 0.241.177"

    print("[pass] Config version bump passed")


if __name__ == "__main__":
    tests = [
        test_workspace_models_and_routes_include_branding_fields,
        test_workspace_manage_and_active_pages_include_branding_hooks,
        test_config_version_is_bumped_for_workspace_hero_layout_changes,
    ]

    results = []
    for test in tests:
        print(f"\n[test] Running {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception:
            results.append(False)
            raise

    success = all(results)
    print(f"\n[results] {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)