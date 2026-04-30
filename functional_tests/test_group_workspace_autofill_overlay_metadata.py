# test_group_workspace_autofill_overlay_metadata.py
"""
Functional test for group workspace autofill overlay metadata hardening.
Version: 0.240.007
Implemented in: 0.240.007

This test ensures the group workspace page exposes explicit autofill metadata so
browser/password-manager overlays do not treat hidden prompt, metadata,
sharing, and tag-management controls as login candidates.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
GROUP_WORKSPACE_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "group_workspaces.html"


def read_text(path: Path) -> str:
    """Return UTF-8 text for a repository file."""
    return path.read_text(encoding="utf-8")


def test_group_workspace_autofill_overlay_metadata() -> bool:
    """Verify group workspace template autofill markers and normalization."""
    print("Testing group workspace autofill overlay metadata hardening...")

    content = read_text(GROUP_WORKSPACE_TEMPLATE)

    required_markers = [
        'id="group-search-input" autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true"',
        'id="group-select" autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true"',
        'id="groupPromptModal" tabindex="-1" aria-hidden="true" autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true"',
        'id="group-prompt-form" autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true"',
        'id="group-prompt-name"',
        'id="group-prompt-content"',
        'id="groupShareDocumentModal" tabindex="-1" aria-hidden="true" autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true"',
        'id="groupShareDocumentForm" autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true"',
        'id="groupSearchTerm"',
        'id="group-bulk-tag-action" autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true"',
        'id="group-new-tag-name"',
        'function applyGroupWorkspaceAutofillMetadata(root) {',
        'function setupGroupWorkspaceAutofillMetadata() {',
        'document.getElementById("group-dropdown")',
        'document.getElementById("groupWorkspaceTabContent")',
        'document.getElementById("groupPromptModal")',
        'document.getElementById("groupShareDocumentModal")',
        'document.getElementById("modelEndpointModal")',
        'document.getElementById("agentModal")',
        'document.getElementById("plugin-modal")',
        'const autocompleteValue = field.getAttribute("type") === "password" ? "new-password" : "off";',
        'setupGroupWorkspaceAutofillMetadata();'
    ]

    missing_markers = [marker for marker in required_markers if marker not in content]
    if missing_markers:
        print("Missing group workspace autofill hardening markers:")
        for marker in missing_markers:
            print(f"  - {marker}")
        return False

    print("Group workspace autofill overlay metadata hardening test passed!")
    return True


if __name__ == "__main__":
    success = test_group_workspace_autofill_overlay_metadata()
    sys.exit(0 if success else 1)