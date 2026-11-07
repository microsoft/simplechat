# test_group_membership_policy.py
"""
Functional test for the group membership policy and its hints.
Version: 0.261.151
Implemented in: 0.261.151

``group_membership_operations`` and ``group_member_actions`` are the one membership
decision. This test pins:

- the operations for every role and status, and the per-member actions for every
  caller role, target role and self combination;
- the seam with the classic routes: the real classic PATCH, DELETE and transfer
  routes allow exactly the per-member actions the policy advertises, and the real
  classic add, request list and leave routes agree with the group-level operations,
  apart from decision 2's recorded divergence (the classic add stays open in a
  locked or inactive group);
- the seam with the native routes: every action the member list advertises is one
  the native routes accept, and every action it withholds is one they refuse.
"""

import itertools

import pytest

from test_support.group_directory_harness import group_directory_environment


ROLE_USERS = {"Owner": "owner-1", "Admin": "admin-1", "DocumentManager": "manager-1", "User": "member-1"}
USER_ROLES = {user_id: role for role, user_id in ROLE_USERS.items()}
STATUSES = ["active", "upload_disabled", "locked", "inactive", None, "", "archived"]
# A different role for each target, so a role change always changes something.
OTHER_ROLE = {"Owner": "User", "Admin": "User", "DocumentManager": "User", "User": "DocumentManager"}


@pytest.fixture(scope="module")
def module_env():
    with group_directory_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def seed(env, **extra):
    return env.seed_group("g-1", "Team", **extra)


# ---------------------------------------------------------------------------
# The policy itself
# ---------------------------------------------------------------------------

EXPECTED_OPERATIONS = {
    "Owner": ["add_member", "review_requests", "change_role", "remove_member", "transfer_ownership"],
    "Admin": ["add_member", "review_requests", "change_role", "remove_member", "leave"],
    "DocumentManager": ["leave"],
    "User": ["leave"],
    None: [],
}


@pytest.mark.parametrize("role,status", list(itertools.product(EXPECTED_OPERATIONS, STATUSES)))
def test_operations_for_every_role_and_status(env, role, status):
    policy = env.modules.membership_policy
    group = {} if status is None else {"status": status}
    expected = list(EXPECTED_OPERATIONS[role])
    if status not in ("active", "upload_disabled", None, ""):
        expected = [operation for operation in expected if operation != "add_member"]
    assert policy.group_membership_operations(role, group, {"enable_group_workspaces": True}) == expected


def test_operations_need_group_workspaces(env):
    policy = env.modules.membership_policy
    for settings in ({}, {"enable_group_workspaces": False}, None, []):
        assert policy.group_membership_operations("Owner", {}, settings) == []


EXPECTED_ACTIONS = {
    # (caller, target, self): actions
    ("Owner", "Owner", True): [],
    ("Owner", "Admin", False): ["change_role", "remove", "transfer_ownership"],
    ("Owner", "DocumentManager", False): ["change_role", "remove", "transfer_ownership"],
    ("Owner", "User", False): ["change_role", "remove", "transfer_ownership"],
    ("Admin", "Owner", False): [],
    ("Admin", "Admin", True): ["change_role", "leave"],
    ("Admin", "Admin", False): ["change_role", "remove"],
    ("Admin", "DocumentManager", False): ["change_role", "remove"],
    ("Admin", "User", False): ["change_role", "remove"],
    ("DocumentManager", "Owner", False): [],
    ("DocumentManager", "Admin", False): [],
    ("DocumentManager", "DocumentManager", True): ["leave"],
    ("DocumentManager", "DocumentManager", False): [],
    ("DocumentManager", "User", False): [],
    ("User", "Owner", False): [],
    ("User", "Admin", False): [],
    ("User", "DocumentManager", False): [],
    ("User", "User", True): ["leave"],
    ("User", "User", False): [],
}


@pytest.mark.parametrize("caller,target,is_self", list(EXPECTED_ACTIONS))
def test_member_actions_for_every_caller_target_and_self(env, caller, target, is_self):
    policy = env.modules.membership_policy
    assert policy.group_member_actions(caller, target, is_self=is_self) == EXPECTED_ACTIONS[(caller, target, is_self)]


def test_member_actions_for_unknown_roles_are_empty(env):
    policy = env.modules.membership_policy
    assert policy.group_member_actions(None, "User", is_self=False) == []
    assert policy.group_member_actions("Owner", None, is_self=False) == []
    assert policy.group_member_actions("Superuser", "User", is_self=False) == []


# ---------------------------------------------------------------------------
# The seam with the classic routes
# ---------------------------------------------------------------------------

# The per-member actions have no deliberate differences left: decision 4's classic
# fix made the classic role change refuse the owner as its target, as the hint
# withholds it.


def classic_allows(env, caller_id, target_id, action):
    env.reset()
    seed(env)
    env.as_user(caller_id)
    if action == "change_role":
        response = env.call(
            "PATCH", f"/api/groups/g-1/members/{target_id}", {"role": OTHER_ROLE[USER_ROLES[target_id]]},
        )
    elif action in ("remove", "leave"):
        response = env.call("DELETE", f"/api/groups/g-1/members/{target_id}")
    else:
        response = env.call("PATCH", "/api/groups/g-1/transferOwnership", {"newOwnerId": target_id})
    return response.status_code == 200


@pytest.mark.parametrize("caller_id,target_id", list(itertools.product(ROLE_USERS.values(), ROLE_USERS.values())))
def test_member_actions_agree_with_the_classic_routes(env, caller_id, target_id):
    policy = env.modules.membership_policy
    caller_role, target_role, is_self = USER_ROLES[caller_id], USER_ROLES[target_id], caller_id == target_id
    advertised = set(policy.group_member_actions(caller_role, target_role, is_self=is_self))
    removal = "leave" if is_self else "remove"
    for action in ("change_role", removal, "transfer_ownership"):
        if action == "transfer_ownership" and is_self:
            continue  # a transfer to yourself is a classic no-op, not an action
        allowed = classic_allows(env, caller_id, target_id, action)
        assert allowed == (action in advertised), (caller_role, target_role, action)


def test_group_operations_agree_with_the_classic_routes(env):
    policy = env.modules.membership_policy
    for role, caller_id in ROLE_USERS.items():
        operations = set(policy.group_membership_operations(role, {"status": "active"}, env.settings))

        env.reset()
        seed(env)
        env.as_user(caller_id)
        added = env.call("POST", "/api/groups/g-1/members", {
            "userId": "newcomer-1", "email": "nia.newcomer@example.test", "displayName": "Nia Newcomer",
        })
        assert (added.status_code == 200) == ("add_member" in operations), role

        env.reset()
        seed(env)
        env.as_user(caller_id)
        listed = env.call("GET", "/api/groups/g-1/requests")
        assert (listed.status_code == 200) == ("review_requests" in operations), role

        env.reset()
        seed(env)
        env.as_user(caller_id)
        left = env.call("DELETE", f"/api/groups/g-1/members/{caller_id}")
        assert (left.status_code == 200) == ("leave" in operations), role


@pytest.mark.parametrize("status", ["locked", "inactive"])
def test_adding_in_a_locked_or_inactive_group_is_a_recorded_divergence(env, status):
    """Decision 2: native add follows the classic page, which hides Add there; the
    classic API still accepts it, and stays unchanged."""
    seed(env, status=status)
    env.as_user("owner-1")
    assert "add_member" not in env.modules.membership_policy.group_membership_operations(
        "Owner", env.stored_group("g-1"), env.settings,
    )
    classic = env.call("POST", "/api/groups/g-1/members", {
        "userId": "newcomer-1", "email": "nia.newcomer@example.test", "displayName": "Nia Newcomer",
    })
    assert classic.status_code == 200


# ---------------------------------------------------------------------------
# The seam with the native routes
# ---------------------------------------------------------------------------

def native_attempt(env, target_id, action):
    if action == "change_role":
        return env.change_role("g-1", target_id, {"role": OTHER_ROLE[USER_ROLES[target_id]]})
    if action in ("remove", "leave"):
        return env.remove_member("g-1", target_id)
    return env.transfer("g-1", {"userId": target_id})


@pytest.mark.parametrize("caller_id", list(ROLE_USERS.values()))
def test_every_advertised_action_is_accepted_and_every_withheld_one_refused(env, caller_id):
    seed(env)
    env.as_user(caller_id)
    rows = env.members("g-1").get_json()["members"]
    for row in rows:
        possible = ["change_role", "leave" if row["userId"] == caller_id else "remove"]
        # A transfer to the current owner is an idempotent no-op any member may make,
        # not an action; a transfer to anyone else is the owner's action.
        if row["userId"] != caller_id and row["role"] != "Owner":
            possible.append("transfer_ownership")
        for action in possible:
            env.reset()
            seed(env)
            env.as_user(caller_id)
            response = native_attempt(env, row["userId"], action)
            accepted = response.status_code in (200, 201)
            assert accepted == (action in row["member_actions"]), (caller_id, row["userId"], action, response.get_json())


@pytest.mark.parametrize("caller_id", list(ROLE_USERS.values()))
@pytest.mark.parametrize("status", ["active", "locked"])
def test_every_advertised_group_operation_is_accepted(env, caller_id, status):
    seed(env, status=status, pending=("applicant-1",))
    env.add_directory_user("newcomer-1")
    env.as_user(caller_id)
    operations = set(env.members("g-1").get_json()["membership_management"]["operations"])
    attempts = {
        "add_member": lambda: env.add_member("g-1", {"userId": "newcomer-1", "role": "User"}),
        "review_requests": lambda: env.pending_requests("g-1"),
        "leave": lambda: env.remove_member("g-1", caller_id),
    }
    for operation, attempt in attempts.items():
        env.reset()
        seed(env, status=status, pending=("applicant-1",))
        env.add_directory_user("newcomer-1")
        env.as_user(caller_id)
        response = attempt()
        assert (response.status_code in (200, 201)) == (operation in operations), (caller_id, status, operation)
    env.reset()
    seed(env, status=status, pending=("applicant-1",))
    env.as_user(caller_id)
    for decision in (env.approve, env.reject):
        response = decision("g-1", "applicant-1")
        assert (response.status_code == 200) == ("review_requests" in operations), (caller_id, decision)
        env.reset()
        seed(env, status=status, pending=("applicant-1",))
        env.as_user(caller_id)


def test_the_hint_is_published_only_by_the_member_list(env):
    seed(env, pending=("applicant-1",))
    env.as_user("owner-1")
    assert "membership_management" in env.members("g-1").get_json()
    assert set(env.pending_requests("g-1").get_json()) == {"requests", "total_count"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
