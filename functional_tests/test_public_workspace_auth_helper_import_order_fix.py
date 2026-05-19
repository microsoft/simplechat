# test_public_workspace_auth_helper_import_order_fix.py
"""
Functional test for public workspace auth helper binding during full app startup.
Version: 0.241.039
Implemented in: 0.241.039

This test ensures public workspace creation resolves current user information
after the full Flask app import path and prevents regression of the
get_current_user_info NameError.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import app as simplechat_app_module
from flask import session
import functions_public_workspaces


def test_public_workspace_auth_helpers_survive_full_app_import():
    """Verify public workspace helpers keep auth access after the full app import path."""
    assert callable(
        getattr(functions_public_workspaces.functions_authentication, "get_current_user_info", None)
    ), "Expected functions_public_workspaces to retain access to get_current_user_info after importing app.py."


def test_create_public_workspace_uses_session_user_without_name_errors():
    """Verify create_public_workspace resolves the current user from session state."""
    created_docs = []

    def fake_create_item(workspace_doc):
        created_docs.append(workspace_doc)

    original_create_item = functions_public_workspaces.cosmos_public_workspaces_container.create_item
    functions_public_workspaces.cosmos_public_workspaces_container.create_item = fake_create_item

    try:
        with simplechat_app_module.app.test_request_context("/api/public_workspaces", method="POST"):
            session["user"] = {
                "oid": "user-123",
                "preferred_username": "user@example.com",
                "email": "user@example.com",
                "name": "Test User",
            }

            workspace_doc = functions_public_workspaces.create_public_workspace(
                "Public Test Workspace",
                "Regression coverage for public workspace creation.",
            )
    finally:
        functions_public_workspaces.cosmos_public_workspaces_container.create_item = original_create_item

    assert created_docs, "Expected create_public_workspace to persist a new public workspace document."
    assert workspace_doc["owner"]["userId"] == "user-123", "Expected the session user to become the owner."
    assert workspace_doc["owner"]["email"] == "user@example.com", "Expected the session user's email to be stored."
    assert workspace_doc["owner"]["displayName"] == "Test User", "Expected the session user's name to be stored."


if __name__ == "__main__":
    test_public_workspace_auth_helpers_survive_full_app_import()
    test_create_public_workspace_uses_session_user_without_name_errors()
    print("Public workspace auth helper import-order fix verified.")