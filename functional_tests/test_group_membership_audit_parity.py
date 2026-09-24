# test_group_membership_audit_parity.py
"""
Functional test for audit parity between the native and classic membership writes.
Version: 0.261.150
Implemented in: 0.261.150

Each native membership write and its classic counterpart run for real, through the
shared harness, from the same stored group. They must leave the same group
document and the same audit trail: the chat bootstrap cache bumps, the activity
records, the logs and the notifications, apart from the generated ids and
timestamps. The classic role-change record and notification now come from the
shared ``functions_group_membership_audit`` helpers, and the native add reuses
``_log_group_member_addition`` and ``_notify_group_member_addition``, so this
also pins that the extraction changed nothing.
"""

import pytest

from test_support.group_directory_harness import group_directory_environment


VOLATILE = ("id", "timestamp", "created_at", "_etag", "modifiedDate")


@pytest.fixture(scope="module")
def module_env():
    with group_directory_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def strip(value):
    if isinstance(value, dict):
        return {key: strip(item) for key, item in value.items() if key not in VOLATILE}
    if isinstance(value, list):
        return [strip(item) for item in value]
    return value


def outcome(env, response):
    return {
        "status": response.status_code,
        "group": strip(env.stored_group("g-1")),
        "bumps": list(env.bumps),
        "records": sorted((strip(record) for record in env.activity_records()), key=repr),
        "logs": [(message, level, strip(extra)) for message, level, extra in env.logs],
        "notifications": strip(env.notifications),
    }


CASES = {
    "add": (
        "admin-1",
        lambda env: env.call("POST", "/api/groups/g-1/members", {
            "userId": "newcomer-1", "email": "nia.newcomer@example.test", "displayName": "Nia Newcomer", "role": "admin",
        }),
        lambda env: env.add_member("g-1", {"userId": "newcomer-1", "role": "Admin"}),
    ),
    "role": (
        "admin-1",
        lambda env: env.call("PATCH", "/api/groups/g-1/members/member-1", {"role": "DocumentManager"}),
        lambda env: env.change_role("g-1", "member-1", {"role": "DocumentManager"}),
    ),
    "remove": (
        "owner-1",
        lambda env: env.call("DELETE", "/api/groups/g-1/members/manager-1"),
        lambda env: env.remove_member("g-1", "manager-1"),
    ),
    "leave": (
        "member-1",
        lambda env: env.call("DELETE", "/api/groups/g-1/members/member-1"),
        lambda env: env.remove_member("g-1", "member-1"),
    ),
    "approve": (
        "admin-1",
        lambda env: env.call("PATCH", "/api/groups/g-1/requests/applicant-1", {"action": "approve"}),
        lambda env: env.approve("g-1", "applicant-1"),
    ),
    "reject": (
        "owner-1",
        lambda env: env.call("PATCH", "/api/groups/g-1/requests/applicant-1", {"action": "reject"}),
        lambda env: env.reject("g-1", "applicant-1"),
    ),
    "transfer": (
        "owner-1",
        lambda env: env.call("PATCH", "/api/groups/g-1/transferOwnership", {"newOwnerId": "admin-1"}),
        lambda env: env.transfer("g-1", {"userId": "admin-1"}),
    ),
}


def run(env, caller, write):
    env.reset()
    env.seed_group("g-1", "Team", pending=("applicant-1",))
    env.add_directory_user("newcomer-1")
    env.as_user(caller)
    return outcome(env, write(env))


@pytest.mark.parametrize("operation", list(CASES))
def test_native_and_classic_writes_leave_the_same_group_and_audit(env, operation):
    caller, classic, native = CASES[operation]
    classic_outcome = run(env, caller, classic)
    native_outcome = run(env, caller, native)
    assert classic_outcome["status"] == 200
    assert native_outcome["status"] in (200, 201)
    for key in ("group", "bumps", "records", "logs", "notifications"):
        assert native_outcome[key] == classic_outcome[key], key


def test_the_parity_cases_exercise_every_audit_channel(env):
    """The comparison is not vacuous: between them, the cases produce each kind of audit."""
    seen = {"bumps": set(), "records": set(), "logs": 0, "notifications": 0}
    for caller, _classic, native in CASES.values():
        result = run(env, caller, native)
        seen["bumps"].update(result["bumps"])
        seen["records"].update(record.get("activity_type") for record in result["records"])
        seen["logs"] += len(result["logs"])
        seen["notifications"] += len(result["notifications"])
    assert seen["bumps"] == {
        "group_member_added", "group_member_role_updated", "group_member_removed",
        "group_member_request_approved", "group_ownership_transferred",
    }
    assert seen["records"] == {"add_member_directly", "update_member_role", "group_member_deleted"}
    assert seen["logs"] == 2 and seen["notifications"] == 3


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
