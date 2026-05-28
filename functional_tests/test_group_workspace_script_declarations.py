# test_group_workspace_script_declarations.py
"""
Functional test for group workspace document access script declarations.
Version: 0.241.113
Implemented in: 0.241.113

This test ensures that group workspace document renderers keep access-related
constants declared once and in the right order so the page script can parse.
"""

import os
import re
import sys


IMPLEMENTED_VERSION = "0.241.113"
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUP_WORKSPACE_TEMPLATE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "templates",
    "group_workspaces.html",
)
CONFIG_FILE = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "config.py",
)


def read_file(path):
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def version_tuple(version):
    return tuple(int(part) for part in version.split("."))


def extract_between(content, start_marker, end_marker):
    start_index = content.find(start_marker)
    assert start_index != -1, f"Could not locate start marker: {start_marker}"

    end_index = content.find(end_marker, start_index)
    assert end_index != -1, f"Could not locate end marker: {end_marker}"

    return content[start_index:end_index]


def declared_constants(block):
    return re.findall(r"^\s*const\s+([A-Za-z_$][\w$]*)\b", block, re.MULTILINE)


def duplicate_names(names):
    return sorted({name for name in names if names.count(name) > 1})


def assert_ordered(block, snippets):
    positions = []
    for snippet in snippets:
        position = block.find(snippet)
        assert position != -1, f"Missing expected snippet: {snippet}"
        positions.append(position)

    assert positions == sorted(positions), f"Expected snippets in order: {snippets}"


def test_render_group_document_row_access_declarations_are_unique():
    """Verify the row renderer does not redeclare access-related constants."""
    print("Testing renderGroupDocumentRow access declarations...")

    content = read_file(GROUP_WORKSPACE_TEMPLATE)
    row_block = extract_between(
        content,
        "  function renderGroupDocumentRow(doc, userRole) {",
        "\n  function toggleGroupDetails",
    )
    declaration_block = extract_between(
        row_block,
        "    const canManage =",
        "\n    // First column with checkbox",
    )

    duplicates = duplicate_names(declared_constants(declaration_block))
    assert not duplicates, f"Duplicate const declarations in row renderer: {duplicates}"
    assert_ordered(
        declaration_block,
        [
            "const access = getGroupDocumentAccess(doc);",
            "const groupStatus = window.currentGroupStatus || 'active';",
            "const canModify = access.isOwnerGroup && groupStatus === 'active';",
            "const canChat = access.hasApprovedAccess && groupStatus !== 'inactive';",
            "const canRemove = canManage && !access.isOwnerGroup",
        ],
    )

    print("renderGroupDocumentRow declaration check passed")


def test_group_folder_documents_table_declares_per_document_access_flags():
    """Verify folder table rendering declares access flags before using them."""
    print("Testing buildGroupFolderDocumentsTable access declarations...")

    content = read_file(GROUP_WORKSPACE_TEMPLATE)
    folder_block = extract_between(
        content,
        "  function buildGroupFolderDocumentsTable(docs) {",
        "\n  function buildGroupFolderDocumentsCardsHtml",
    )
    setup_block = extract_between(
        folder_block,
        "    const groupStatus = window.currentGroupStatus || 'active';",
        "\n      // First column: expand/collapse or status indicator",
    )

    duplicates = duplicate_names(declared_constants(setup_block))
    assert not duplicates, f"Duplicate const declarations in folder table setup: {duplicates}"
    assert_ordered(
        setup_block,
        [
            "const groupCanModify = groupStatus === 'active';",
            "const groupCanChat = groupStatus !== 'inactive';",
            "const access = getGroupDocumentAccess(doc);",
            "const canModify = access.isOwnerGroup && groupCanModify;",
            "const canChat = access.hasApprovedAccess && groupCanChat;",
            "const canRemove = canManage && !access.isOwnerGroup",
        ],
    )

    print("buildGroupFolderDocumentsTable declaration check passed")


def test_config_version_includes_group_workspace_script_fix():
    """Verify config.py version is at least the implemented fix version."""
    print("Testing config version for group workspace script fix...")

    config_content = read_file(CONFIG_FILE)
    match = re.search(r'VERSION\s*=\s*"(?P<version>\d+\.\d+\.\d+)"', config_content)
    assert match, "Could not locate VERSION in config.py"
    current_version = match.group("version")
    assert version_tuple(current_version) >= version_tuple(IMPLEMENTED_VERSION), (
        f"Expected config.py VERSION to be at least {IMPLEMENTED_VERSION}, "
        f"found {current_version}"
    )

    print("config version check passed")


if __name__ == "__main__":
    tests = [
        test_render_group_document_row_access_declarations_are_unique,
        test_group_folder_documents_table_declares_per_document_access_flags,
        test_config_version_includes_group_workspace_script_fix,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as ex:
            print(f"Test failed: {ex}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)