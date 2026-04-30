# test_workspace_autofill_overlay_metadata.py
"""
Functional test for workspace autofill overlay metadata hardening.
Version: 0.240.007
Implemented in: 0.240.007

This test ensures the workspace page and its shared modal includes expose
explicit autofill metadata so browser/password-manager overlays do not treat
non-login fields like prompt, sharing, agent, plugin, and endpoint controls as
login candidates.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "workspace.html"
AGENT_MODAL_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "_agent_modal.html"
MULTIENDPOINT_MODAL_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "_multiendpoint_modal.html"


def read_text(path: Path) -> str:
    """Return UTF-8 text for a repository file."""
    return path.read_text(encoding="utf-8")


def test_workspace_autofill_overlay_metadata() -> bool:
    """Verify workspace template normalization and shared modal markers."""
    print("Testing workspace autofill overlay metadata hardening...")

    workspace_content = read_text(WORKSPACE_TEMPLATE)
    agent_modal_content = read_text(AGENT_MODAL_TEMPLATE)
    multiendpoint_content = read_text(MULTIENDPOINT_MODAL_TEMPLATE)

    workspace_markers = [
        'id="prompt-form" autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true"',
        'id="doc-metadata-form" autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true"',
        'id="shareDocumentForm" autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true"',
        'function applyWorkspaceAutofillMetadata(root) {',
        'function setupWorkspaceAutofillMetadata() {',
        'document.getElementById("promptModal")',
        'document.getElementById("shareDocumentModal")',
        'document.getElementById("modelEndpointModal")',
        'document.getElementById("agentModal")',
        'document.getElementById("plugin-modal")',
        'const autocompleteValue = field.getAttribute("type") === "password" ? "new-password" : "off";',
        'field.setAttribute("autocomplete", autocompleteValue);',
        'field.setAttribute("data-lpignore", "true");',
        'field.setAttribute("data-1p-ignore", "true");',
        'field.setAttribute("data-bwignore", "true");',
        'setupWorkspaceAutofillMetadata();'
    ]

    agent_markers = [
        'id="agentModal"',
        'data-bwignore="true"',
        'data-1p-ignore="true"',
        'data-lpignore="true"',
        'autocomplete="off"'
    ]

    multiendpoint_markers = [
        'id="modelEndpointModal"',
        'id="model-endpoint-client-secret" autocomplete="new-password" data-bwignore="true" data-1p-ignore="true" data-lpignore="true"',
        'id="model-endpoint-api-key" autocomplete="new-password" data-bwignore="true" data-1p-ignore="true" data-lpignore="true"'
    ]

    missing_workspace_markers = [marker for marker in workspace_markers if marker not in workspace_content]
    missing_agent_markers = [marker for marker in agent_markers if marker not in agent_modal_content]
    missing_multiendpoint_markers = [marker for marker in multiendpoint_markers if marker not in multiendpoint_content]

    if missing_workspace_markers or missing_agent_markers or missing_multiendpoint_markers:
        print("Missing workspace autofill hardening markers:")
        for marker in missing_workspace_markers:
            print(f"  - workspace.html: {marker}")
        for marker in missing_agent_markers:
            print(f"  - _agent_modal.html: {marker}")
        for marker in missing_multiendpoint_markers:
            print(f"  - _multiendpoint_modal.html: {marker}")
        return False

    print("Workspace autofill overlay metadata hardening test passed!")
    return True


if __name__ == "__main__":
    success = test_workspace_autofill_overlay_metadata()
    sys.exit(0 if success else 1)