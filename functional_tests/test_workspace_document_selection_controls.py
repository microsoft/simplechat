#!/usr/bin/env python3
# test_workspace_document_selection_controls.py
"""
Functional test for workspace document selection controls.
Version: 0.241.095
Implemented in: 0.241.087

This test ensures personal and group workspaces expose select-all controls in
list and folder-grid document tables, and that the larger 100/250 page sizes
are available anywhere document pagination is configured.
"""

from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_workspace_document_selection_controls_wiring() -> None:
    print("🔍 Testing workspace document selection controls wiring...")

    config_content = read_text("application/single_app/config.py")
    workspace_template = read_text("application/single_app/templates/workspace.html")
    workspace_documents_js = read_text("application/single_app/static/js/workspace/workspace-documents.js")
    workspace_tags_js = read_text("application/single_app/static/js/workspace/workspace-tags.js")
    group_template = read_text("application/single_app/templates/group_workspaces.html")

    assert 'VERSION = "0.241.095"' in config_content, (
        "Expected config.py version 0.241.095 for the workspace document selection controls update."
    )

    assert 'id="docs-select-all-checkbox"' in workspace_template, (
        "Expected the personal workspace list table to render a select-all checkbox."
    )
    assert '<option value="100">100</option>' in workspace_template, (
        "Expected the personal workspace list or grid page size selector to include 100 items per page."
    )
    assert '<option value="250">250</option>' in workspace_template, (
        "Expected the personal workspace list or grid page size selector to include 250 items per page."
    )
    assert 'window.toggleSelectAllDocuments = function(isSelected) {' in workspace_documents_js, (
        "Expected the personal workspace selection owner to expose a select-all handler."
    )
    assert 'function getDocumentSelectAllCheckboxes() {' in workspace_documents_js, (
        "Expected the personal workspace selection owner to track select-all controls across tables."
    )
    assert 'class="form-check-input document-select-all-checkbox"' in workspace_tags_js, (
        "Expected the personal workspace folder drill-down table to render a select-all checkbox."
    )
    assert 'window.toggleSelectionMode(); return false;' in workspace_tags_js, (
        "Expected the personal workspace folder drill-down actions to expose selection mode."
    )
    assert 'window.syncDocumentSelectionUI?.();' in workspace_tags_js, (
        "Expected the personal workspace folder drill-down to resync selection UI after rerendering."
    )
    assert '<option value="100"${folderPageSize === 100 ? \' selected\' : \'\'}>100</option>' in workspace_tags_js, (
        "Expected the personal workspace folder drill-down page size selector to include 100."
    )
    assert '<option value="250"${folderPageSize === 250 ? \' selected\' : \'\'}>250</option>' in workspace_tags_js, (
        "Expected the personal workspace folder drill-down page size selector to include 250."
    )

    assert 'id="group-docs-select-all-checkbox"' in group_template, (
        "Expected the group workspace list table to render a select-all checkbox."
    )
    assert 'function toggleGroupSelectAllDocuments(isSelected) {' in group_template, (
        "Expected the group workspace selection owner to expose a select-all handler."
    )
    assert 'id="group-folder-docs-table"' in group_template, (
        "Expected the group workspace folder drill-down table to be addressable for selection sync."
    )
    assert 'class="form-check-input document-select-all-checkbox"' in group_template, (
        "Expected the group workspace folder drill-down table to render a select-all checkbox."
    )
    assert '<option value="100">100</option>' in group_template, (
        "Expected the group workspace static page size selectors to include 100 items per page."
    )
    assert '<option value="250">250</option>' in group_template, (
        "Expected the group workspace static page size selectors to include 250 items per page."
    )
    assert '<option value="100"${groupFolderPageSize === 100 ? \' selected\' : \'\'}>100</option>' in group_template, (
        "Expected the group workspace folder drill-down page size selector to include 100."
    )
    assert '<option value="250"${groupFolderPageSize === 250 ? \' selected\' : \'\'}>250</option>' in group_template, (
        "Expected the group workspace folder drill-down page size selector to include 250."
    )

    print("✅ Workspace document selection controls wiring verified")


def run_tests() -> bool:
    tests = [test_workspace_document_selection_controls_wiring]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print("✅ Test passed")
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)