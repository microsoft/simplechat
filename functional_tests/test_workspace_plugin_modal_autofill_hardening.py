#!/usr/bin/env python3
"""
Functional test for workspace plugin modal autofill hardening.
Version: 0.239.195
Implemented in: 0.239.195

This test ensures the hidden plugin modal fields on workspace.html are marked so
browser/password-manager autofill extensions ignore secret inputs that are not
part of a login form and still belong to an explicit non-submitting form.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MODAL_FILE = REPO_ROOT / "application" / "single_app" / "templates" / "_plugin_modal.html"


def test_workspace_plugin_modal_autofill_hardening() -> bool:
    """Verify secret inputs are ignored by autofill overlays and form-associated."""
    print("Testing workspace plugin modal autofill hardening...")

    content = PLUGIN_MODAL_FILE.read_text(encoding="utf-8")

    required_markers = [
        'id="plugin-modal"',
        'id="plugin-modal-form"',
        'action=""',
        'method="post"',
        'data-bwignore="true"',
        'data-1p-ignore="true"',
        'data-lpignore="true"',
        'id="plugin-auth-api-key-value"',
        'id="plugin-auth-bearer-token"',
        'id="plugin-auth-basic-password"',
        'id="plugin-auth-oauth2-token"',
        'id="sql-password"',
        'id="sql-client-secret"',
        'autocomplete="new-password"'
    ]

    missing = [marker for marker in required_markers if marker not in content]
    if missing:
        print("Missing plugin modal autofill hardening markers:")
        for marker in missing:
            print(f"  - {marker}")
        return False

    print("Workspace plugin modal autofill hardening test passed!")
    return True


if __name__ == "__main__":
    success = test_workspace_plugin_modal_autofill_hardening()
    sys.exit(0 if success else 1)