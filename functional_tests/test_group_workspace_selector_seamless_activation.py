# test_group_workspace_selector_seamless_activation.py
"""
Functional test for group workspace selector seamless activation.
Version: 0.241.152
Implemented in: 0.241.147

This test ensures the group workspace selector combines group selection, role,
and manage controls in one row, activates groups directly from the dropdown,
shows a useful empty state when the user has no groups, and keeps the role
summary from repeating the active group name.
"""

import os
import sys
import traceback


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUP_WORKSPACES_TEMPLATE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "templates",
    "group_workspaces.html",
)
CONFIG_FILE = os.path.join(ROOT_DIR, "application", "single_app", "config.py")


def read_file(path):
    """Read a repository file as UTF-8 text."""
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def assert_ordered_snippets(content, ordered_snippets, label):
    """Verify snippets appear in the expected order."""
    previous_index = -1
    for snippet in ordered_snippets:
        current_index = content.find(snippet)
        assert current_index != -1, f"Missing ordered {label} snippet: {snippet}"
        assert current_index > previous_index, f"Snippet out of order for {label}: {snippet}"
        previous_index = current_index


def test_group_selector_row_combines_related_controls():
    """Verify group selector, role summary, and manage button share one row."""
    print("Testing group selector row layout...")

    try:
        template = read_file(GROUP_WORKSPACES_TEMPLATE)
        assert_ordered_snippets(
            template,
            [
                'id="group-selector-row"',
                'id="group-dropdown"',
                'id="user-role-display"',
                'id="manage-active-group-btn"',
                'id="btn-my-groups"',
                'id="group-status-alert"',
            ],
            "group selector row",
        )
        assert 'id="btn-change-group"' not in template
        assert "Change Active Group" not in template
        assert '<span class="group-role-label">Role</span>' in template
        assert "group-role-pill" in template
        assert "group-selector-actions" in template
        assert "Your role in" not in template
        assert 'alert alert-info mb-0 py-2 px-3 h-100' not in template
        assert 'id="active-group-name-role"' not in template
        assert "activeGroupNameRoleEl" not in template

        print("Group selector row layout passed")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        traceback.print_exc()
        return False


def test_group_dropdown_click_activates_selected_group():
    """Verify clicking a group dropdown item triggers active-group persistence."""
    print("Testing group dropdown activation wiring...")

    try:
        template = read_file(GROUP_WORKSPACES_TEMPLATE)
        required_snippets = [
            'item.addEventListener("click", function() {',
            'activateSelectedGroup(groupId);',
            'function activateSelectedGroup(groupId) {',
            'return setActiveGroup(newGroupId)',
            'fetch("/api/groups/setActive"',
        ]
        missing = [snippet for snippet in required_snippets if snippet not in template]
        assert not missing, f"Missing seamless activation snippets: {missing}"

        print("Group dropdown activation wiring passed")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        traceback.print_exc()
        return False


def test_group_selector_empty_state_copy():
    """Verify no-group users see actionable empty-state text."""
    print("Testing group selector empty-state copy...")

    try:
        template = read_file(GROUP_WORKSPACES_TEMPLATE)
        required_snippets = [
            'selectedGroupText.textContent = "No groups yet";',
            'You are not a member of any group. Select My Groups to find or create a group.',
            'emptyOption.textContent = "No groups available";',
        ]
        missing = [snippet for snippet in required_snippets if snippet not in template]
        assert not missing, f"Missing empty-state snippets: {missing}"
        assert 'dropdownItems.innerHTML = \'<div class="dropdown-item disabled">No groups found</div>\';' not in template

        print("Group selector empty-state copy passed")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        traceback.print_exc()
        return False


def test_config_version_matches_selector_change():
    """Verify config.py reflects the group selector UX update version."""
    print("Testing config version...")

    try:
        config_content = read_file(CONFIG_FILE)
        assert 'VERSION = "0.241.152"' in config_content, "Expected config.py version 0.241.152"

        print("Config version passed")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_group_selector_row_combines_related_controls,
        test_group_dropdown_click_activates_selected_group,
        test_group_selector_empty_state_copy,
        test_config_version_matches_selector_change,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
