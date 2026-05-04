# test_group_auth_helper_import_order_fix.py
"""
Functional test for group auth helper binding during full app startup.
Version: 0.241.100
Implemented in: 0.241.100

This test ensures group workspace helper functions continue resolving the
current user after the full Flask app import path, preventing group creation,
active-group changes, and dependent group uploads from failing with NameError.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import app as simplechat_app_module
from flask import session
import functions_group


def test_group_auth_helpers_survive_full_app_import():
    """Verify group helpers resolve auth accessors after the full app import path."""
    assert callable(getattr(functions_group.functions_authentication, "get_current_user_id", None)), (
        "Expected functions_group to retain access to get_current_user_id after importing app.py."
    )
    assert callable(getattr(functions_group.functions_authentication, "get_current_user_info", None)), (
        "Expected functions_group to retain access to get_current_user_info after importing app.py."
    )


def test_group_helpers_use_session_user_without_name_errors():
    """Verify create/set-active group helpers resolve the current user from session state."""
    created_docs = []
    updated_settings_call = {}

    def fake_create_item(group_doc):
        created_docs.append(group_doc)

    def fake_update_user_settings(user_id, new_settings):
        updated_settings_call["user_id"] = user_id
        updated_settings_call["settings"] = new_settings

    original_create_item = functions_group.cosmos_groups_container.create_item
    original_update_user_settings = functions_group.functions_settings.update_user_settings

    functions_group.cosmos_groups_container.create_item = fake_create_item
    functions_group.functions_settings.update_user_settings = fake_update_user_settings

    try:
        with simplechat_app_module.app.test_request_context("/api/groups"):
            session["user"] = {
                "oid": "user-123",
                "preferred_username": "user@example.com",
                "email": "user@example.com",
                "name": "Test User",
            }

            group_doc = functions_group.create_group("Alpha Team", "Release docs")
            functions_group.update_active_group_for_user("group-123")
    finally:
        functions_group.cosmos_groups_container.create_item = original_create_item
        functions_group.functions_settings.update_user_settings = original_update_user_settings

    assert created_docs, "Expected create_group to persist a new group document."
    assert group_doc["owner"]["id"] == "user-123", "Expected the session user to become the group owner."
    assert group_doc["users"][0]["userId"] == "user-123", "Expected the session user to be added as a group member."
    assert updated_settings_call == {
        "user_id": "user-123",
        "settings": {"activeGroupOid": "group-123"},
    }, "Expected update_active_group_for_user to persist the selected group for the session user."


if __name__ == "__main__":
    test_group_auth_helpers_survive_full_app_import()
    test_group_helpers_use_session_user_without_name_errors()
    print("✅ Group auth helper import-order fix verified.")