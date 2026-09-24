# test_group_membership_legacy_guard.py
"""
Functional test for the classic membership writers on the group-document guard.
Version: 0.261.151
Implemented in: 0.261.151

The classic join, approve and reject, direct add (the route and the SimpleChat
agent tool share ``add_group_member_for_current_user``), remove and leave, role
change and transfer routes now write through
``update_group_document_with_etag_guard``. Their responses and audit are pinned
unchanged by ``test_group_membership_legacy_responses.py``; this test pins what
the guard adds:

- every write is a conditional replace, never an upsert;
- a membership change that lands mid-write is kept;
- a group deleted mid-write is the classic 404 and is never recreated;
- a group that keeps changing is a 409 ``group_write_conflict``;
- the route's own rules are re-checked on the fresh copy, so a demotion, a removal
  or an approval that lands first refuses the write, and decision 3's fixes (no
  duplicate member, every request settled) apply to the fresh copy too;
- the cache bumps stay as they were.

It also pins that the race M7A recorded is closed: a classic write that lands after
a native join or cancel no longer undoes it. Approve and reject are left out of the
cancel half, because cancelling the request they decide changes their answer, which
``test_the_rules_are_rechecked_on_the_fresh_copy`` pins for reject.
"""

import ast
from pathlib import Path

import pytest
from flask import session

from test_support.group_directory_harness import group_directory_environment, person


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
LATE_USER = {"userId": "late-member", "email": "late.member@example.test", "displayName": "Late Member"}
CONFLICT = {
    "error": "The group changed while this change was being saved. Try again.",
    "error_code": "group_write_conflict",
}

CLASSIC_WRITES = {
    "join": ("outsider-1", "POST", "/api/groups/g-1/requests", None, 201, []),
    "approve": ("admin-1", "PATCH", "/api/groups/g-1/requests/applicant-1", {"action": "approve"}, 200,
                ["group_member_request_approved"]),
    "reject": ("admin-1", "PATCH", "/api/groups/g-1/requests/applicant-1", {"action": "reject"}, 200, []),
    "add": ("admin-1", "POST", "/api/groups/g-1/members",
            {"userId": "newcomer-1", "email": "nia.newcomer@example.test", "displayName": "Nia Newcomer"}, 200,
            ["group_member_added"]),
    "remove": ("owner-1", "DELETE", "/api/groups/g-1/members/manager-1", None, 200, ["group_member_removed"]),
    "leave": ("member-1", "DELETE", "/api/groups/g-1/members/member-1", None, 200, ["group_member_removed"]),
    "role": ("admin-1", "PATCH", "/api/groups/g-1/members/member-1", {"role": "Admin"}, 200,
             ["group_member_role_updated"]),
    "transfer": ("owner-1", "PATCH", "/api/groups/g-1/transferOwnership", {"newOwnerId": "admin-1"}, 200,
                 ["group_ownership_transferred"]),
}


@pytest.fixture(scope="module")
def module_env():
    with group_directory_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def prepare(env, write):
    caller, method, path, body, _status, _bumps = CLASSIC_WRITES[write]
    env.seed_group("g-1", "Team", pending=("applicant-1",))
    env.as_user(caller)
    return lambda: env.call(method, path, body)


def land(env, change):
    def concurrent():
        record = env.stored_group("g-1")
        change(record)
        env.groups.seed(record)
    return concurrent


@pytest.mark.parametrize("write", list(CLASSIC_WRITES))
def test_every_classic_write_is_a_conditional_replace_with_its_classic_bump(env, write):
    send = prepare(env, write)
    status, bumps = CLASSIC_WRITES[write][4], CLASSIC_WRITES[write][5]
    assert send().status_code == status
    assert [call[0] for call in env.write_calls()] == ["replace_item"]
    assert env.bumps == bumps


@pytest.mark.parametrize("write", list(CLASSIC_WRITES))
def test_a_concurrent_membership_change_is_kept(env, write):
    send = prepare(env, write)
    env.groups.before_replace.append(land(env, lambda record: record["users"].append(LATE_USER)))
    assert send().status_code == CLASSIC_WRITES[write][4]
    assert LATE_USER in env.stored_group("g-1")["users"]
    assert [call[0] for call in env.write_calls()] == ["replace_item", "replace_item"]


@pytest.mark.parametrize("write", list(CLASSIC_WRITES))
def test_a_group_deleted_mid_write_is_404_and_never_recreated(env, write):
    send = prepare(env, write)
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    response = send()
    assert (response.status_code, response.get_json()) == (404, {"error": "Group not found"})
    assert env.stored_group("g-1") is None
    assert not [call for call in env.groups.calls if call[0] in ("create_item", "upsert_item")]
    assert env.bumps == [] and env.notifications == [] and env.activity_records() == []


@pytest.mark.parametrize("write", list(CLASSIC_WRITES))
def test_a_group_that_keeps_changing_is_a_write_conflict(env, write):
    send = prepare(env, write)
    for _ in range(env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS):
        env.groups.before_replace.append(land(env, lambda record: record.update(description=record["description"] + ".")))
    response = send()
    assert (response.status_code, response.get_json()) == (409, CONFLICT)
    assert env.bumps == [] and env.notifications == [] and env.activity_records() == []


@pytest.mark.parametrize("write,change,expected", [
    ("approve", lambda record: record["admins"].remove("admin-1"),
     (403, {"error": "Only the owner or admin can approve/reject requests"})),
    ("add", lambda record: record["admins"].remove("admin-1"),
     (403, {"error": "Only the owner or admin can add members"})),
    ("add", lambda record: record["users"].append(person("newcomer-1")),
     (400, {"error": "User is already a member"})),
    ("role", lambda record: record["admins"].remove("admin-1"),
     (403, {"error": "Only the owner or admin can update roles"})),
    ("remove", lambda record: record.update(owner={"id": "admin-1", "email": "", "displayName": ""}),
     (403, {"error": "Only the owner or admin can remove other members"})),
    ("transfer", lambda record: record.update(owner={"id": "admin-1", "email": "", "displayName": ""}),
     (403, {"error": "Only the current owner can transfer ownership"})),
    ("join", lambda record: record["users"].append(person("outsider-1")),
     (400, {"error": "User is already a member"})),
    ("reject", lambda record: record["pendingUsers"].clear(), (404, {"error": "Request not found"})),
])
def test_the_rules_are_rechecked_on_the_fresh_copy(env, write, change, expected):
    send = prepare(env, write)
    env.groups.before_replace.append(land(env, change))
    response = send()
    assert (response.status_code, response.get_json()) == expected
    assert [call[0] for call in env.write_calls()] == ["replace_item"]
    assert env.bumps == [] and env.notifications == [] and env.activity_records() == []


def test_a_classic_approve_does_not_duplicate_a_member_added_first(env):
    """Decision 3 on the fresh copy: an add that lands first is not duplicated."""
    send = prepare(env, "approve")
    env.groups.before_replace.append(land(env, lambda record: record["users"].append(person("applicant-1"))))
    assert send().status_code == 200
    stored = env.stored_group("g-1")
    assert [entry["userId"] for entry in stored["users"]].count("applicant-1") == 1
    assert stored["pendingUsers"] == []


def test_a_classic_add_clears_a_request_that_lands_first(env):
    """Decision 3 on the fresh copy: the added user's request, made mid-write, is settled."""
    send = prepare(env, "add")
    env.groups.before_replace.append(land(env, lambda record: record["pendingUsers"].append(person("newcomer-1"))))
    assert send().status_code == 200
    assert env.stored_group("g-1")["pendingUsers"] == [person("applicant-1")]


def test_the_add_audit_describes_the_committed_copy(env):
    """The audit and notification use the copy that was written, and the role that
    authorised the write on it, not the copy read before the guard."""
    send = prepare(env, "add")

    def renamed_and_promoted(record):
        record["name"] = "Team Renamed"
        record["owner"] = {"id": "admin-1", "email": "", "displayName": ""}

    env.groups.before_replace.append(land(env, renamed_and_promoted))
    assert send().status_code == 200
    [record] = [entry for entry in env.activity_records() if entry.get("activity_type") == "add_member_directly"]
    assert (record["added_by_role"], record["group_name"]) == ("Owner", "Team Renamed")
    assert "Team Renamed" in record["description"] and record["description"].startswith("Owner ")


def test_the_agent_tool_add_is_guarded_too(env):
    """``add_group_member_for_current_user`` backs the SimpleChat agent tool."""
    add = env.operations_namespace["add_group_member_for_current_user"]
    details = {"group_id": "g-1", "user_id": "newcomer-1", "email": "n@example.test", "display_name": "N"}
    with env.app.test_request_context("/"):
        session["user"] = {
            "oid": "owner-1", "roles": ["User"], "name": "Olive Owner", "preferred_username": "olive.owner@example.test",
        }
        env.seed_group("g-1", "Team")
        env.groups.before_replace.append(lambda: env.groups.records.clear())
        with pytest.raises(LookupError):
            add(**details)
        env.seed_group("g-1", "Team")
        for _ in range(env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS):
            env.groups.before_replace.append(land(env, lambda record: record.update(description="x")))
        with pytest.raises(env.modules.group.GroupDocumentWriteConflict):
            add(**details)
        env.groups.before_replace.clear()
        result = add(**details)
    assert result["success"] is True and result["group"]["users"][-1]["userId"] == "newcomer-1"
    assert not [call for call in env.groups.calls if call[0] in ("create_item", "upsert_item")]


@pytest.mark.parametrize("write", ["approve", "add", "remove", "role", "transfer", "reject"])
def test_a_classic_write_no_longer_undoes_a_native_join(env, write):
    """M7A's recorded race: a classic writer working from a stale copy used to put
    back the pending list it read, dropping a join that landed in between."""
    send = prepare(env, write)

    def native_join_lands():
        record = env.stored_group("g-1")
        record["pendingUsers"].append(LATE_USER)
        env.groups.seed(record)

    env.groups.before_replace.append(native_join_lands)
    assert send().status_code in (200, 201)
    assert LATE_USER in env.stored_group("g-1")["pendingUsers"]


@pytest.mark.parametrize("write", ["add", "remove", "leave", "role", "transfer"])
def test_a_classic_write_no_longer_undoes_a_native_cancel(env, write):
    """The other half of M7A's race: a stale copy used to restore a cancelled request."""
    send = prepare(env, write)

    def native_cancel_lands():
        record = env.stored_group("g-1")
        record["pendingUsers"] = [entry for entry in record["pendingUsers"] if entry["userId"] != "applicant-1"]
        env.groups.seed(record)

    env.groups.before_replace.append(native_cancel_lands)
    assert send().status_code == 200
    assert env.stored_group("g-1")["pendingUsers"] == []


def _function_calls(path, function_name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return {
                call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
                for call in ast.walk(node) if isinstance(call, ast.Call)
            }
    raise AssertionError(f"{function_name} not found in {path.name}")


@pytest.mark.parametrize("path,function_name", [
    (APP_DIR / "route_backend_groups.py", "request_to_join"),
    (APP_DIR / "route_backend_groups.py", "approve_reject_request"),
    (APP_DIR / "route_backend_groups.py", "remove_member"),
    (APP_DIR / "route_backend_groups.py", "update_member_role"),
    (APP_DIR / "route_backend_groups.py", "transfer_ownership"),
    (APP_DIR / "functions_simplechat_operations.py", "add_group_member_for_current_user"),
])
def test_no_classic_membership_writer_upserts_the_group(path, function_name):
    calls = _function_calls(path, function_name)
    assert "upsert_item" not in calls
    assert calls & {"_guarded_group_write", "update_group_document_with_etag_guard"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
