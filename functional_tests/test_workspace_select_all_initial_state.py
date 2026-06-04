# test_workspace_select_all_initial_state.py
"""
Functional test for workspace select-all initial multi-select state.
Version: 0.241.125
Implemented in: 0.241.125

This test ensures personal and group workspace selection sync calculates
header select-all availability after row checkboxes are made visible.
"""

from pathlib import Path
import sys
import traceback


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
PERSONAL_DOCUMENTS_JS = APP_ROOT / "static" / "js" / "workspace" / "workspace-documents.js"
GROUP_WORKSPACES_TEMPLATE = APP_ROOT / "templates" / "group_workspaces.html"
CONFIG_FILE = APP_ROOT / "config.py"
CURRENT_VERSION = "0.241.125"


def read_text(path):
    """Read a repository text file."""
    return path.read_text(encoding="utf-8")


def extract_block(source, start_marker, end_marker):
    """Extract source text between two stable markers."""
    start_index = source.index(start_marker)
    end_index = source.index(end_marker, start_index)
    return source[start_index:end_index]


def assert_ordered(block, markers):
    """Assert that markers appear in the expected order."""
    previous_index = -1
    for marker in markers:
        current_index = block.index(marker)
        if current_index <= previous_index:
            raise AssertionError(f"Expected marker after previous marker: {marker}")
        previous_index = current_index


def test_personal_workspace_selection_sync_order():
    """Validate personal workspace enables select-all after entering multi-select."""
    source = read_text(PERSONAL_DOCUMENTS_JS)
    block = extract_block(
        source,
        "function syncDocumentSelectionModeUI()",
        "// Delete selected documents",
    )

    assert_ordered(
        block,
        [
            "getDocumentSelectionTables().forEach",
            "checkbox.classList.toggle('d-none', !selectionModeActive);",
            "syncDocumentCheckboxesWithSelection();",
        ],
    )


def test_group_workspace_selection_sync_order():
    """Validate group workspace enables select-all after entering multi-select."""
    source = read_text(GROUP_WORKSPACES_TEMPLATE)
    block = extract_block(
        source,
        "function syncGroupSelectionModeUI()",
        "function renderCurrentGroupDocuments()",
    )

    assert_ordered(
        block,
        [
            "getGroupSelectionTables().forEach",
            "checkbox.classList.toggle('d-none', !groupSelectionMode);",
            "syncGroupSelectionUI();",
        ],
    )


def test_version_was_incremented():
    """Validate the app version was incremented with this bug fix."""
    config_source = read_text(CONFIG_FILE)
    expected = f'VERSION = "{CURRENT_VERSION}"'
    assert expected in config_source


def main():
    """Run all regression checks."""
    tests = [
        test_personal_workspace_selection_sync_order,
        test_group_workspace_selection_sync_order,
        test_version_was_incremented,
    ]
    results = []

    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"PASS: {test.__name__}")
            results.append(True)
        except Exception as ex:
            print(f"FAIL: {test.__name__}: {ex}")
            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    print(f"Results: {passed}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)