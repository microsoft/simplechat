# test_group_settings_context_seam.py
"""
Functional test for the group settings decision in the selected-group context.
Version: 0.261.154
Implemented in: 0.261.154

The selected-group context (``GET /api/v2/workspaces/group/<group_id>``) publishes
``settings_management`` so the V2 workspace can offer group settings without another
read. It must be the decision the native group settings routes enforce:
``build_group_settings_management`` called with the caller's group role, the stored
group, the current settings and the session's app roles. This test reads the real
context route, in ``test_v2_group_workspace_context``'s environment, across group
roles, statuses, the creation narrowing, the administrator's download capability
and the group retention switch.
"""

import itertools
from copy import deepcopy

import pytest

from test_v2_group_workspace_context import CONTEXT_PATH, environment  # noqa: F401 - the shared fixture


ROLES = {"owner": "Owner", "admin": "Admin", "manager": "DocumentManager", "reader": "User"}
STATUSES = ("active", "upload_disabled", "locked", "inactive", "unknown")
SESSION_ROLES = {"user": ["User"], "creator": ["User", "CreateGroups"], "app_admin": ["Admin"]}
SETTINGS = {
    "plain": {},
    "narrowed": {"require_member_of_create_group": True},
    "downloads": {"allow_group_workspace_file_downloads": True},
    "downloads_elsewhere": {"allow_group_workspace_file_downloads": True,
                            "require_group_assignment_for_file_downloads": True,
                            "file_download_allowed_group_ids": ["group-b"]},
    "retention": {"enable_retention_policy_group": True},
    "everything": {"require_member_of_create_group": True, "allow_group_workspace_file_downloads": True,
                   "enable_retention_policy_group": True},
}


def read_with_roles(environment, user_id, roles):
    with environment.client.session_transaction() as state:
        state["user"] = {"oid": user_id, "roles": list(roles)}
    return environment.client.get(CONTEXT_PATH)


CELLS = list(itertools.product(ROLES, STATUSES, SESSION_ROLES, SETTINGS))


@pytest.mark.parametrize("actor,status,session_roles,settings", CELLS)
def test_the_context_publishes_the_settings_decision(environment, actor, status, session_roles, settings):
    environment.records["group-a"]["status"] = status
    environment.settings.update(SETTINGS[settings])
    response = read_with_roles(environment, actor, SESSION_ROLES[session_roles])
    assert response.status_code == 200, response.get_json()
    expected = environment.helper.build_group_settings_management(
        ROLES[actor], deepcopy(environment.records["group-a"]), deepcopy(environment.settings),
        SESSION_ROLES[session_roles],
    )
    assert response.get_json()["settings_management"] == expected


@pytest.mark.parametrize("session_roles,expected_reason", [
    (["User"], "create_groups_role_required"),
    (["User", "CreateGroups"], None),
    (["Admin"], "create_groups_role_required"),
])
def test_the_session_roles_reach_the_decision(environment, session_roles, expected_reason):
    environment.settings["require_member_of_create_group"] = True
    management = read_with_roles(environment, "owner", session_roles).get_json()["settings_management"]
    assert management["reasons"].get("edit_name") == expected_reason
    assert "edit_logo" in management["operations"]


def test_the_owner_of_an_active_group_may_do_everything_the_settings_allow(environment):
    environment.settings.update(SETTINGS["everything"])
    management = read_with_roles(environment, "owner", ["User", "CreateGroups"]).get_json()["settings_management"]
    assert management == {
        "schema_version": 1,
        "operations": [
            "edit_name", "edit_description", "edit_color", "edit_logo", "edit_downloads", "edit_retention",
            "view_activity", "view_stats", "view_file_count",
        ],
        "reasons": {},
    }


def test_a_member_is_told_why_for_every_operation(environment):
    environment.settings.update(SETTINGS["everything"])
    management = read_with_roles(environment, "reader", ["User"]).get_json()["settings_management"]
    assert management == {
        "schema_version": 1,
        "operations": [],
        "reasons": {
            "edit_name": "group_owner_required",
            "edit_description": "group_owner_required",
            "edit_color": "group_owner_required",
            "edit_logo": "group_owner_required",
            "edit_downloads": "group_manager_required",
            "edit_retention": "group_manager_required",
            "view_activity": "group_manager_required",
            "view_stats": "group_manager_required",
            "view_file_count": "group_owner_required",
        },
    }


def test_an_admin_of_a_locked_group_keeps_downloads_retention_and_the_reads(environment):
    environment.records["group-a"]["status"] = "locked"
    environment.settings.update(SETTINGS["everything"])
    management = read_with_roles(environment, "admin", ["User"]).get_json()["settings_management"]
    assert management["operations"] == ["edit_downloads", "edit_retention", "view_activity", "view_stats"]
    assert management["reasons"]["edit_logo"] == "group_owner_required"
    assert management["reasons"]["view_file_count"] == "group_owner_required"


@pytest.mark.parametrize("status", ["locked", "inactive"])
def test_a_read_only_status_holds_the_owner_profile_and_logo(environment, status):
    environment.records["group-a"]["status"] = status
    management = read_with_roles(environment, "owner", ["User"]).get_json()["settings_management"]
    for operation in ("edit_name", "edit_description", "edit_color", "edit_logo"):
        assert management["reasons"][operation] == "group_status_unavailable"
    assert {"view_activity", "view_stats", "view_file_count"} <= set(management["operations"])


def test_downloads_and_retention_follow_their_switches(environment):
    management = read_with_roles(environment, "owner", ["User"]).get_json()["settings_management"]
    assert management["reasons"]["edit_downloads"] == "group_downloads_not_enabled"
    assert management["reasons"]["edit_retention"] == "group_retention_disabled"

    environment.settings.update(SETTINGS["downloads_elsewhere"])
    management = read_with_roles(environment, "owner", ["User"]).get_json()["settings_management"]
    assert management["reasons"]["edit_downloads"] == "group_downloads_not_enabled"

    environment.settings["file_download_allowed_group_ids"] = ["group-a"]
    environment.settings["enable_retention_policy_group"] = True
    management = read_with_roles(environment, "owner", ["User"]).get_json()["settings_management"]
    assert "edit_downloads" in management["operations"]
    assert "edit_retention" in management["operations"]
