#!/usr/bin/env python3
"""
Functional test for personal workspace tutorial selector coverage.
Version: 0.239.191
Implemented in: 0.239.191

This test ensures that the personal workspace tutorial points at the current
visible workspace controls and keeps its launcher and overlay wiring intact.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
TUTORIAL_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace-tutorial.js"
WORKSPACE_TEMPLATE_FILE = REPO_ROOT / "application" / "single_app" / "templates" / "workspace.html"


def test_personal_workspace_tutorial_selectors() -> bool:
    """Validate that the personal workspace tutorial references current UI controls."""
    print("Testing personal workspace tutorial selector coverage...")

    tutorial_content = TUTORIAL_FILE.read_text(encoding="utf-8")
    template_content = WORKSPACE_TEMPLATE_FILE.read_text(encoding="utf-8")

    required_tutorial_selectors = [
        "#upload-area",
        "#docs-filters-toggle-btn",
        "#docs-search-input",
        "label[for='docs-view-grid']",
        "#documents-table tbody tr[id^='doc-row-'] .expand-collapse-container button",
        "#documents-table tbody tr[id^='details-row-'] .bg-light",
        "#documents-table tbody tr[id^='details-row-'] .btn-info",
        ".workspace-tutorial-metadata-modal .modal-content",
        ".workspace-tutorial-metadata-tag-selection-modal .modal-content",
        "#documents-table tbody tr[id^='doc-row-'] button[onclick*='redirectToChat']",
        "#documents-table tbody tr[id^='doc-row-'] .action-dropdown .dropdown-toggle",
        ".workspace-tutorial-bulk-tag-modal .modal-content",
        ".workspace-tutorial-bulk-tag-selection-modal .modal-content",
        ".workspace-tutorial-doc-actions-menu .dropdown-menu",
        ".workspace-tutorial-share-modal .modal-content",
        "#documents-table.selection-mode tbody tr[id^='doc-row-'] .document-checkbox",
        "#bulkActionsBar",
        ".workspace-tutorial-tag-management-modal .modal-content",
        "#workspace-manage-tags-btn",
        "#create-prompt-btn",
        "#prompts-filters-toggle-btn",
        "#prompts-search-input",
        ".agent-examples-trigger",
        "#create-agent-btn",
        "#agents-search",
        "#create-plugin-btn",
        "#plugins-search",
    ]

    required_template_markers = [
        'id="workspace-tutorial-launch"',
        'is-ready',
        'id="workspace-tutorial-btn"',
        'Workspace Tutorial',
        'tutorial-btn-label',
        'bi bi-question-circle',
        'data-bs-trigger="hover"',
        'data-bs-custom-class="chat-tutorial-tooltip"',
        'data-bs-offset="0,132"',
        "js/workspace/workspace-tutorial.js",
        'id="upload-area"',
        'id="docs-filters-toggle-btn"',
        'id="docs-search-input"',
        'id="bulkActionsBar"',
        'id="manage-tags-btn"',
        'id="docMetadataModal"',
        'id="bulkTagModal"',
        'id="tagSelectionModal"',
        'id="shareDocumentModal"',
        'id="workspace-manage-tags-btn"',
        'id="create-prompt-btn"',
        'id="prompts-search-input"',
        'id="create-agent-btn"',
        'id="agents-search"',
        'id="plugins-tab-btn"',
        'id="workspaceTab"',
        ".workspace-tutorial-layer",
        ".workspace-tutorial-highlight",
        ".workspace-tutorial-card",
        '.chat-tutorial-tooltip',
        '#workspace-tutorial-launch.is-ready',
    ]

    required_behavior_guards = [
        "function activateTab(tabButtonId)",
        "function ensureCollapseVisible(toggleId, collapseId)",
        "function ensureDocumentsListView()",
        "function ensureFirstDocumentDetailsVisible()",
        "function ensureFirstDocumentSelected()",
        "function createTutorialModalClone(sourceModalId, cloneClassName, customizeClone)",
        "function createTutorialAnchoredMenu(anchorEl, className, innerHtml)",
        "function ensureTutorialMetadataModal()",
        "function ensureTutorialMetadataTagSelectionModal()",
        "function ensureTutorialShareModal()",
        "function ensureTutorialBulkTagModal()",
        "function ensureTutorialBulkTagSelectionModal()",
        "function ensureTutorialWorkspaceTagManagementModal()",
        "function ensureTutorialActionsMenu()",
        'typeof step.prepare === "function"',
        'function applyTargetHighlight(step, target)',
        'workspace-tutorial-target-highlight',
        'suppressOverlayHighlight: true',
        "async function ensurePluginsReady()",
        'ensureCollapseVisible("docs-filters-toggle-btn", "docs-filters-collapse")',
        'ensureCollapseVisible("prompts-filters-toggle-btn", "prompts-filters-collapse")',
        'activateTab("documents-tab-btn")',
        'activateTab("prompts-tab-btn")',
        'activateTab("agents-tab-btn")',
        'activateTab("plugins-tab-btn")',
        'window.fetchPlugins',
        'bootstrap.Tab.getOrCreateInstance(tabButton).show();',
        'function buildSteps()',
        'workspace-tutorial: no steps available',
        'id: "documents-upload"',
        'id: "documents-edit-metadata-tag-selection"',
        'id: "documents-bulk-tag-selection"',
        'id: "documents-manage-tags-modal"',
        'id: "documents-actions-select"',
        'id: "plugins-search"',
    ]

    for selector in required_tutorial_selectors:
        if selector not in tutorial_content:
            print(f"Missing workspace tutorial selector: {selector}")
            return False

    for marker in required_template_markers:
        if marker not in template_content:
            print(f"Missing workspace template marker: {marker}")
            return False

    for guard in required_behavior_guards:
        if guard not in tutorial_content:
            print(f"Missing workspace tutorial behavior guard: {guard}")
            return False

    print("Personal workspace tutorial selector coverage test passed!")
    return True


if __name__ == "__main__":
    success = test_personal_workspace_tutorial_selectors()
    sys.exit(0 if success else 1)