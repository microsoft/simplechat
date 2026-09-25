# test_group_screening_hint_seam.py
"""
Functional test for the seam between the group screening hint and the screening routes.
Version: 0.261.173
Implemented in: 0.261.173

The group Documents section offers the content screening controls only when the group context's
`screening_management` hint grants `manage`. The hint must be exactly the authorization every
group-scoped `/api/content-screening` route enforces: `content_screening.permissions.
assert_scope_access`, which accepts the group's Owner, Admin or DocumentManager (`REVIEW_ROLES`)
and checks no group status. Otherwise the section either offers a member controls the server
refuses or hides controls the server allows.

The real context route and builder run in the harness `test_v2_group_workspace_context.py` uses.
Its `functions_group` executes the real role functions against the harness's group record, and the
real permissions module resolves `assert_group_role` through that same module, so both sides decide
on the same record. For every role and status, the hint is compared with the real authorization;
the builder is shown to read the screening module's own roles, not a copy of them.
"""

import importlib

import pytest

from test_v2_group_workspace_context import environment as environment, read_as  # noqa: F401 - the real builder's harness

_PYTEST_FIXTURES = (environment,)

ROLE_USERS = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "reader"}
# Every status the server stores, and one it does not recognize, which the context reports as unknown.
STATUSES = ("active", "locked", "upload_disabled", "inactive", "archived")


def screening_permissions():
    # Imported once the harness has put the application on sys.path.
    return importlib.import_module("content_screening.permissions")


def screening_allows(user_id, group_id="group-a"):
    """What the screening routes decide: `assert_scope_access`, the check each group-scoped route
    (policy read and write, scan start, job read and actions) makes before anything else."""
    permissions = screening_permissions()
    try:
        permissions.assert_scope_access(user_id, "group", group_id)
    except permissions.ScreeningPermissionError:
        return False
    return True


def screening_hint(env, user_id, status):
    env.records["group-a"]["status"] = status
    response = read_as(env, user_id)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["screening_management"]


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("role", list(ROLE_USERS))
def test_the_hint_is_the_screening_routes_authorization(environment, role, status):  # noqa: F811
    user_id = ROLE_USERS[role]
    hint = screening_hint(environment, user_id, status)
    allowed = screening_allows(user_id)
    assert hint == {"schema_version": 1, "operations": ["manage"] if allowed else []}


def test_the_comparison_is_not_vacuous(environment):  # noqa: F811
    """The grid above holds only if the real authorization really splits the roles: the managers are
    allowed, an ordinary member and a non-member are refused, in a status that bars viewing too."""
    environment.records["group-a"]["status"] = "inactive"
    decisions = {user_id: screening_allows(user_id) for user_id in (*ROLE_USERS.values(), "stranger")}
    assert decisions == {
        "owner": True, "admin": True, "manager": True, "reader": False, "stranger": False,
    }


def test_the_builder_reads_the_screening_modules_roles(environment, monkeypatch):  # noqa: F811
    """The hint is computed from `REVIEW_ROLES` itself, at call time: the builder holds the screening
    module's own tuple, and replacing it moves the hint, so no copy of the roles can stand in."""
    assert environment.helper.SCREENING_REVIEW_ROLES is screening_permissions().REVIEW_ROLES
    monkeypatch.setattr(environment.helper, "SCREENING_REVIEW_ROLES", ("User",))
    assert screening_hint(environment, "reader", "active")["operations"] == ["manage"]
    assert screening_hint(environment, "owner", "active")["operations"] == []
