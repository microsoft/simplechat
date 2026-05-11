#!/usr/bin/env python3
"""
Functional test for personal workspace tutorial document flow.
Version: 0.239.191
Implemented in: 0.239.191

This test ensures that the personal workspace tutorial covers the document row,
metadata, actions, selection bar, and example tag walkthrough steps requested
for the workspace document experience.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
TUTORIAL_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace-tutorial.js"


def test_personal_workspace_tutorial_document_flow() -> bool:
    """Validate that the tutorial includes the expanded document flow steps."""
    print("Testing personal workspace tutorial document flow...")

    tutorial_content = TUTORIAL_FILE.read_text(encoding="utf-8")
    required_markers = [
        'id: "documents-open-details"',
        'id: "documents-details-panel"',
        'id: "documents-edit-metadata-modal"',
        'id: "documents-edit-metadata-tag-selection"',
        'id: "documents-chat-button"',
        'id: "documents-actions-button"',
        'id: "documents-bulk-tag-modal"',
        'id: "documents-bulk-tag-selection"',
        'id: "documents-actions-menu"',
        'id: "documents-actions-share"',
        'id: "documents-actions-chat"',
        'id: "documents-actions-select"',
        'id: "documents-selection-bar"',
        'id: "documents-manage-tags-modal"',
        'EXAMPLE_TAGS',
        'EXAMPLE_SHARED_USERS'
    ]

    missing = [marker for marker in required_markers if marker not in tutorial_content]
    if missing:
        print("Missing workspace tutorial document flow markers:")
        for marker in missing:
            print(f"  - {marker}")
        return False

    metadata_modal_index = tutorial_content.index('id: "documents-edit-metadata-modal"')
    metadata_tag_index = tutorial_content.index('id: "documents-edit-metadata-tag-selection"')
    selection_bar_index = tutorial_content.index('id: "documents-selection-bar"')
    bulk_modal_index = tutorial_content.index('id: "documents-bulk-tag-modal"')

    if metadata_tag_index <= metadata_modal_index:
        print("Single-file tag picker no longer follows the metadata popup in tutorial order.")
        return False

    if bulk_modal_index <= selection_bar_index:
        print("Bulk tag assignment popup no longer appears after the selection bar step in tutorial order.")
        return False

    print("Personal workspace tutorial document flow test passed!")
    return True


if __name__ == "__main__":
    success = test_personal_workspace_tutorial_document_flow()
    sys.exit(0 if success else 1)