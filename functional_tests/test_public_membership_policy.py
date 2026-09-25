# test_public_membership_policy.py
"""
Functional test for the public workspace membership policy and its disclosure.
Version: 0.261.177
Implemented in: 0.261.177

``public_membership_operations`` and ``public_member_actions`` are the one public
membership decision the native routes and their hints will read, so the Members
view can never offer a control the routes refuse. ``project_member_rows`` is the
server-side disclosure projector: only the Owner and Admins see members' emails.

This test pins the pure policy tables and the projector. Both modules import
nothing from the application, so they run here as themselves, with no harness. The
seam with the classic and native routes is pinned in the route tests that land with
the routes.

The public policy deliberately differs from the group policy:

- there is no ``leave`` and no self-action (decision 17): a public manager can't
  remove or demote themselves;
- the assignable roles are Admin and DocumentManager only; ``User`` is never stored,
  so removal stands in for demoting to ``User``;
- a public workspace has no ``users[]`` roster, so ``User`` never appears as a
  member row.
"""

import itertools
import sys

import pytest

from test_support.agent_delegation import APP_ROOT

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import functions_public_membership_disclosure as disclosure  # noqa: E402
import functions_public_membership_policy as policy  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


assert_app_version_at_least("0.261.132")

STATUSES = ["active", "upload_disabled", "locked", "inactive", None, "", "archived"]
ADD_STATUSES = {"active", "upload_disabled", None, ""}


# ---------------------------------------------------------------------------
# The policy: operations
# ---------------------------------------------------------------------------

EXPECTED_OPERATIONS = {
    "Owner": ["add_member", "review_requests", "change_role", "remove_member", "transfer_ownership"],
    "Admin": ["add_member", "review_requests", "change_role", "remove_member"],
    "DocumentManager": [],
    "User": [],
    None: [],
    "Superuser": [],
}


@pytest.mark.parametrize("role,status", list(itertools.product(EXPECTED_OPERATIONS, STATUSES)))
def test_operations_for_every_role_and_status(role, status):
    workspace = {} if status is None else {"status": status}
    expected = list(EXPECTED_OPERATIONS[role])
    if status not in ADD_STATUSES:
        # Adding a member and changing a role need an active or upload_disabled
        # workspace; removing, reviewing requests and transferring do not.
        expected = [operation for operation in expected if operation not in ("add_member", "change_role")]
    assert policy.public_membership_operations(role, workspace, {"enable_public_workspaces": True}) == expected


def test_operations_need_public_workspaces_enabled():
    for settings in ({}, {"enable_public_workspaces": False}, None, []):
        assert policy.public_membership_operations("Owner", {"status": "active"}, settings) == []


def test_no_operation_is_ever_leave():
    for role in EXPECTED_OPERATIONS:
        for status in STATUSES:
            workspace = {} if status is None else {"status": status}
            operations = policy.public_membership_operations(role, workspace, {"enable_public_workspaces": True})
            assert "leave" not in operations


# ---------------------------------------------------------------------------
# The policy: per-member actions
# ---------------------------------------------------------------------------

EXPECTED_ACTIONS = {
    ("Owner", "Owner", True): [],
    ("Owner", "Admin", False): ["change_role", "remove", "transfer_ownership"],
    ("Owner", "DocumentManager", False): ["change_role", "remove", "transfer_ownership"],
    ("Owner", "User", False): ["change_role", "remove", "transfer_ownership"],
    ("Admin", "Owner", False): [],
    ("Admin", "Admin", True): [],
    ("Admin", "Admin", False): ["change_role", "remove"],
    ("Admin", "DocumentManager", False): ["change_role", "remove"],
    ("Admin", "User", False): ["change_role", "remove"],
    ("DocumentManager", "Owner", False): [],
    ("DocumentManager", "Admin", False): [],
    ("DocumentManager", "DocumentManager", True): [],
    ("DocumentManager", "DocumentManager", False): [],
    ("DocumentManager", "User", False): [],
    ("User", "Owner", False): [],
    ("User", "Admin", False): [],
    ("User", "DocumentManager", False): [],
    ("User", "User", True): [],
    ("User", "User", False): [],
}


@pytest.mark.parametrize("caller,target,is_self", list(EXPECTED_ACTIONS))
def test_member_actions_for_every_caller_target_and_self(caller, target, is_self):
    assert policy.public_member_actions(caller, target, is_self=is_self) == EXPECTED_ACTIONS[(caller, target, is_self)]


def test_member_actions_for_unknown_roles_are_empty():
    assert policy.public_member_actions(None, "User", is_self=False) == []
    assert policy.public_member_actions("Owner", None, is_self=False) == []
    assert policy.public_member_actions("Superuser", "User", is_self=False) == []


def test_no_action_is_ever_leave_and_self_yields_nothing():
    roles = policy.PUBLIC_MEMBER_ROLES
    for caller, target in itertools.product(roles, roles):
        assert "leave" not in policy.public_member_actions(caller, target, is_self=False)
        assert policy.public_member_actions(caller, target, is_self=True) == []


def test_assignable_roles_are_admin_and_document_manager_only():
    assert policy.PUBLIC_ASSIGNABLE_ROLES == ("Admin", "DocumentManager")
    assert "User" not in policy.PUBLIC_ASSIGNABLE_ROLES
    assert "Owner" not in policy.PUBLIC_ASSIGNABLE_ROLES


def test_add_allowed_only_in_active_and_upload_disabled():
    assert policy.public_member_add_allowed({}) is True
    assert policy.public_member_add_allowed({"status": "active"}) is True
    assert policy.public_member_add_allowed({"status": "upload_disabled"}) is True
    for status in ("locked", "inactive", "archived", "mystery"):
        assert policy.public_member_add_allowed({"status": status}) is False


# ---------------------------------------------------------------------------
# The disclosure projector
# ---------------------------------------------------------------------------

def _rows():
    return [
        {"userId": "o", "displayName": "Olive Owner", "email": "olive@example.test", "role": "Owner",
         "member_actions": []},
        {"userId": "a", "displayName": "Amir Admin", "email": "amir@example.test", "role": "Admin",
         "member_actions": ["change_role", "remove"]},
        {"userId": "d", "displayName": "Dana Docs", "email": "dana@example.test", "role": "DocumentManager",
         "member_actions": []},
    ]


@pytest.mark.parametrize("viewer_role", ["Owner", "Admin"])
def test_managers_see_every_members_email(viewer_role):
    projected = disclosure.project_member_rows(_rows(), viewer_role)
    assert [row["email"] for row in projected] == ["olive@example.test", "amir@example.test", "dana@example.test"]
    assert disclosure.viewer_may_see_member_emails(viewer_role) is True


@pytest.mark.parametrize("viewer_role", ["DocumentManager", "User", None, "Superuser"])
def test_a_non_manager_viewer_sees_no_emails_but_keeps_names_and_roles(viewer_role):
    rows = _rows()
    projected = disclosure.project_member_rows(rows, viewer_role)
    assert all(row["email"] == "" for row in projected)
    # Names, ids, roles and actions are the values the decision keeps visible.
    assert [row["displayName"] for row in projected] == ["Olive Owner", "Amir Admin", "Dana Docs"]
    assert [row["role"] for row in projected] == ["Owner", "Admin", "DocumentManager"]
    assert [row["userId"] for row in projected] == ["o", "a", "d"]
    assert disclosure.viewer_may_see_member_emails(viewer_role) is False
    # The input rows are never mutated.
    assert [row["email"] for row in rows] == ["olive@example.test", "amir@example.test", "dana@example.test"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
