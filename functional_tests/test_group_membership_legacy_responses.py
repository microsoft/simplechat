# test_group_membership_legacy_responses.py
"""
Functional test for the classic group membership routes' responses and audit.
Version: 0.261.150
Implemented in: 0.261.150

The classic ``route_backend_groups`` membership routes run for real through the
shared harness. Each case pins the exact status, body, stored change and audit
trail (cache bumps, activity records, logs and notifications) the route produces,
so converting the routes to the group-document guard can be shown to keep every
response, and the deliberate fixes that follow can be shown to change only what
they set out to.
"""

import pytest

from test_support.group_directory_harness import group_directory_environment, group_document, person


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


def answer(response):
    return response.status_code, response.get_json()


def user_ids(env):
    return [entry.get("userId") for entry in env.stored_group("g-1")["users"]]


def records(env):
    return sorted(
        ({key: value for key, value in record.items() if key not in ("id", "timestamp", "created_at", "_etag")}
         for record in env.activity_records()),
        key=lambda record: record.get("activity_type") or "",
    )


# ---------------------------------------------------------------------------
# POST /api/groups/<g>/requests (classic join)
# ---------------------------------------------------------------------------

def test_classic_join_adds_the_entry_without_a_bump(env):
    seed(env)
    env.as_user("outsider-1")
    assert answer(env.call("POST", "/api/groups/g-1/requests")) == (201, {"message": "Membership request created"})
    assert env.stored_group("g-1")["pendingUsers"] == [person("outsider-1")]
    assert env.bumps == [] and env.notifications == [] and env.activity_records() == []


@pytest.mark.parametrize("caller,pending,expected", [
    ("member-1", (), (400, {"error": "User is already a member"})),
    ("applicant-1", ("applicant-1",), (400, {"error": "User has already requested to join"})),
])
def test_classic_join_refusals(env, caller, pending, expected):
    seed(env, pending=pending)
    env.as_user(caller)
    assert answer(env.call("POST", "/api/groups/g-1/requests")) == expected
    assert env.write_calls() == []


def test_classic_join_on_a_missing_group(env):
    env.as_user("outsider-1")
    assert answer(env.call("POST", "/api/groups/g-missing/requests")) == (404, {"error": "Group not found"})


def test_classic_join_creates_a_missing_pending_list(env):
    """Decision 1: the guarded join creates the list instead of failing on it."""
    document = group_document("g-1", "Team")
    del document["pendingUsers"]
    env.seed_document(document)
    env.as_user("outsider-1")
    assert answer(env.call("POST", "/api/groups/g-1/requests")) == (201, {"message": "Membership request created"})
    assert env.stored_group("g-1")["pendingUsers"] == [person("outsider-1")]


# ---------------------------------------------------------------------------
# GET /api/groups/<g>/requests
# ---------------------------------------------------------------------------

def test_classic_request_list(env):
    document = group_document("g-1", "Team", pending=("applicant-1",))
    document["pendingUsers"].append({"userId": "outsider-1", "note": "raw entry"})
    env.seed_document(document)
    env.as_user("admin-1")
    assert answer(env.call("GET", "/api/groups/g-1/requests")) == (
        200, [person("applicant-1"), {"userId": "outsider-1", "note": "raw entry"}],
    )
    env.as_user("member-1")
    assert answer(env.call("GET", "/api/groups/g-1/requests")) == (
        403, {"error": "Only the owner or admin can view requests"},
    )


# ---------------------------------------------------------------------------
# PATCH /api/groups/<g>/requests/<r>
# ---------------------------------------------------------------------------

def test_classic_approve(env):
    seed(env, pending=("applicant-1",))
    env.as_user("admin-1")
    assert answer(env.call("PATCH", "/api/groups/g-1/requests/applicant-1", {"action": "approve"})) == (
        200, {"message": "User approved and added as a member"},
    )
    assert user_ids(env)[-1] == "applicant-1" and env.stored_group("g-1")["users"][-1] == person("applicant-1")
    assert env.stored_group("g-1")["pendingUsers"] == []
    assert env.bumps == ["group_member_request_approved"]
    assert env.notifications == [] and env.activity_records() == []


def test_classic_reject(env):
    seed(env, pending=("applicant-1",))
    env.as_user("owner-1")
    assert answer(env.call("PATCH", "/api/groups/g-1/requests/applicant-1", {"action": "reject"})) == (
        200, {"message": "User rejected"},
    )
    assert env.stored_group("g-1")["pendingUsers"] == [] and "applicant-1" not in user_ids(env)
    assert env.bumps == []


@pytest.mark.parametrize("caller,request_id,body,expected", [
    ("owner-1", "applicant-1", {"action": "remove"}, (400, {"error": "Invalid or missing 'action'. Must be 'approve' or 'reject'."})),
    ("owner-1", "outsider-1", {"action": "approve"}, (404, {"error": "Request not found"})),
    ("member-1", "applicant-1", {"action": "approve"}, (403, {"error": "Only the owner or admin can approve/reject requests"})),
])
def test_classic_decision_refusals(env, caller, request_id, body, expected):
    seed(env, pending=("applicant-1",))
    env.as_user(caller)
    assert answer(env.call("PATCH", f"/api/groups/g-1/requests/{request_id}", body)) == expected
    assert env.write_calls() == []


def test_classic_decision_on_a_missing_group(env):
    env.as_user("owner-1")
    assert answer(env.call("PATCH", "/api/groups/g-missing/requests/x", {"action": "approve"})) == (
        404, {"error": "Group not found"},
    )


def test_classic_approve_of_a_member_duplicates_them(env):
    """Recorded: decision 3 fixes it in the classic route."""
    seed(env, pending=("member-1",))
    env.as_user("owner-1")
    assert env.call("PATCH", "/api/groups/g-1/requests/member-1", {"action": "approve"}).status_code == 200
    assert user_ids(env).count("member-1") == 2


def test_classic_decisions_remove_only_the_first_entry(env):
    """Recorded: decision 3 makes both remove every entry for the user."""
    document = group_document("g-1", "Team", pending=("applicant-1", "outsider-1", "applicant-1", "outsider-1"))
    env.seed_document(document)
    env.as_user("owner-1")
    env.call("PATCH", "/api/groups/g-1/requests/applicant-1", {"action": "approve"})
    env.call("PATCH", "/api/groups/g-1/requests/outsider-1", {"action": "reject"})
    assert env.stored_group("g-1")["pendingUsers"] == [person("applicant-1"), person("outsider-1")]


# ---------------------------------------------------------------------------
# POST /api/groups/<g>/members (classic direct add)
# ---------------------------------------------------------------------------

def test_classic_add_with_details_trusts_them(env):
    seed(env)
    env.as_user("admin-1")
    response = env.call("POST", "/api/groups/g-1/members", {
        "userId": "newcomer-1", "email": "typed@example.test", "displayName": "Typed Name", "role": "admin",
    })
    assert answer(response) == (200, {"message": "Member added", "success": True})
    stored = env.stored_group("g-1")
    assert stored["users"][-1] == {"userId": "newcomer-1", "email": "typed@example.test", "displayName": "Typed Name"}
    assert "newcomer-1" in stored["admins"]
    assert env.directory_calls == []
    assert env.bumps == ["group_member_added"]
    assert records(env) == [{
        "activity_type": "add_member_directly",
        "added_by_user_id": "admin-1",
        "added_by_email": "adam.admin@example.test",
        "added_by_role": "Admin",
        "group_id": "g-1",
        "group_name": "Team",
        "member_user_id": "newcomer-1",
        "member_email": "typed@example.test",
        "member_name": "Typed Name",
        "member_role": "admin",
        "description": "Admin adam.admin@example.test added member Typed Name (typed@example.test) to group Team as admin",
    }]
    assert [(n["user_id"], n["notification_type"], n["title"], n["link_url"]) for n in env.notifications] == [
        ("newcomer-1", "group_member_added", "Added to Group", "/groups/g-1"),
        ("admin-1", "group_member_added", "Group member added", "/groups/g-1"),
    ]


def test_classic_add_by_id_uses_the_directory_or_the_bare_id(env):
    seed(env)
    env.add_directory_user("newcomer-1")
    env.as_user("owner-1")
    assert env.call("POST", "/api/groups/g-1/members", {"userId": "newcomer-1"}).status_code == 200
    assert env.stored_group("g-1")["users"][-1] == person("newcomer-1")
    assert env.call("POST", "/api/groups/g-1/members", {"userId": "ghost-1"}).status_code == 200
    assert env.stored_group("g-1")["users"][-1] == {"userId": "ghost-1", "email": "", "displayName": "ghost-1"}


@pytest.mark.parametrize("caller,body,expected", [
    ("owner-1", {"userId": "member-1", "email": "m@example.test", "displayName": "M"}, (400, {"error": "User is already a member"})),
    ("owner-1", {"userId": "newcomer-1", "email": "n@example.test", "displayName": "N", "role": "manager"}, (400, {"error": "Invalid role. Must be: admin, document_manager, user"})),
    ("owner-1", {"userId": "newcomer-1", "email": "n@example.test", "displayName": "N", "role": "owner"}, (400, {"error": "Invalid role. Must be: admin, document_manager, user"})),
    ("member-1", {"userId": "newcomer-1", "email": "n@example.test", "displayName": "N"}, (403, {"error": "Insufficient permissions for this group"})),
    ("outsider-1", {"userId": "newcomer-1", "email": "n@example.test", "displayName": "N"}, (403, {"error": "User is not a member of this group"})),
])
def test_classic_add_refusals(env, caller, body, expected):
    seed(env)
    env.as_user(caller)
    assert answer(env.call("POST", "/api/groups/g-1/members", body)) == expected
    assert env.write_calls() == [] and env.notifications == []


def test_classic_add_on_a_missing_group(env):
    env.as_user("owner-1")
    assert answer(env.call("POST", "/api/groups/g-missing/members", {"userId": "x", "email": "e", "displayName": "d"})) == (
        404, {"error": "Group not found"},
    )


def test_classic_add_ignores_the_group_status_and_pending_entries(env):
    """Recorded: decision 3 makes the classic add clear the user's pending entries."""
    seed(env, status="locked", pending=("newcomer-1",))
    env.as_user("owner-1")
    assert env.call("POST", "/api/groups/g-1/members", {
        "userId": "newcomer-1", "email": "nia.newcomer@example.test", "displayName": "Nia Newcomer",
    }).status_code == 200
    assert env.stored_group("g-1")["pendingUsers"] == [person("newcomer-1")]


# ---------------------------------------------------------------------------
# DELETE /api/groups/<g>/members/<m>
# ---------------------------------------------------------------------------

def test_classic_leave(env):
    seed(env)
    env.as_user("member-1")
    assert answer(env.call("DELETE", "/api/groups/g-1/members/member-1")) == (200, {"message": "You have left the group"})
    assert "member-1" not in user_ids(env)
    assert env.bumps == ["group_member_removed"]
    assert records(env) == [{
        "user_id": "member-1",
        "activity_type": "group_member_deleted",
        "removed_by": {"user_id": "member-1", "email": "max.member@example.test", "role": "Member"},
        "removed_member": {"user_id": "member-1", "email": "max.member@example.test", "name": "Max Member"},
        "group": {"group_id": "g-1", "group_name": "Team"},
        "description": "Member max.member@example.test left group Team",
    }]
    assert [(message, level) for message, level, _extra in env.logs] == [
        ("Group member deleted: Max Member (max.member@example.test) removed from Team", 20),
    ]


def test_classic_remove(env):
    seed(env)
    env.as_user("owner-1")
    assert answer(env.call("DELETE", "/api/groups/g-1/members/manager-1")) == (200, {"message": "User removed"})
    stored = env.stored_group("g-1")
    assert "manager-1" not in user_ids(env) and "manager-1" not in stored["documentManagers"]
    assert env.bumps == ["group_member_removed"]
    [record] = records(env)
    assert record["removed_by"] == {"user_id": "owner-1", "email": "olive.owner@example.test", "role": "Owner"}
    assert record["description"] == (
        "Owner olive.owner@example.test removed member Mia Manager (mia.manager@example.test) from group Team"
    )


@pytest.mark.parametrize("caller,target,expected", [
    ("owner-1", "owner-1", (403, {"error": "The owner cannot leave the group. Transfer ownership or delete the group."})),
    ("member-1", "manager-1", (403, {"error": "Only the owner or admin can remove other members"})),
    ("admin-1", "owner-1", (403, {"error": "Cannot remove the group owner"})),
])
def test_classic_remove_refusals(env, caller, target, expected):
    seed(env)
    env.as_user(caller)
    assert answer(env.call("DELETE", f"/api/groups/g-1/members/{target}")) == expected
    assert env.write_calls() == []


@pytest.mark.parametrize("caller,target,expected", [
    ("owner-1", "outsider-1", (404, {"error": "User not found in group"})),
    ("outsider-1", "outsider-1", (404, {"error": "You are not in this group"})),
])
def test_classic_remove_of_a_non_member_answers_404_without_writing(env, caller, target, expected):
    """Decision 1: the guarded removal writes only when something changes."""
    seed(env)
    env.as_user(caller)
    assert answer(env.call("DELETE", f"/api/groups/g-1/members/{target}")) == expected
    assert env.write_calls() == []
    assert env.bumps == [] and env.activity_records() == []


def test_classic_remove_of_a_role_holder_without_a_users_entry_cleans_up(env):
    document = group_document("g-1", "Team")
    document["users"] = [entry for entry in document["users"] if entry["userId"] != "manager-1"]
    env.seed_document(document)
    env.as_user("owner-1")
    assert answer(env.call("DELETE", "/api/groups/g-1/members/manager-1")) == (404, {"error": "User not found in group"})
    assert env.stored_group("g-1")["documentManagers"] == []
    assert [call[0] for call in env.write_calls()] == ["replace_item"]
    assert env.bumps == [] and env.activity_records() == []


# ---------------------------------------------------------------------------
# PATCH /api/groups/<g>/members/<m> (role)
# ---------------------------------------------------------------------------

def test_classic_role_change(env):
    seed(env)
    env.as_user("admin-1")
    assert answer(env.call("PATCH", "/api/groups/g-1/members/member-1", {"role": "Admin"})) == (
        200, {"message": "User member-1 updated to Admin"},
    )
    assert "member-1" in env.stored_group("g-1")["admins"]
    assert env.bumps == ["group_member_role_updated"]
    assert records(env) == [{
        "type": "group_member_role_changed",
        "activity_type": "update_member_role",
        "changed_by_user_id": "admin-1",
        "changed_by_email": "adam.admin@example.test",
        "changed_by_role": "Admin",
        "group_id": "g-1",
        "group_name": "Team",
        "member_user_id": "member-1",
        "member_email": "max.member@example.test",
        "member_name": "Max Member",
        "old_role": "User",
        "new_role": "Admin",
        "description": "Admin adam.admin@example.test changed Max Member (max.member@example.test) role from User to Admin in group Team",
    }]
    assert env.notifications == [{
        "user_id": "member-1",
        "notification_type": "system_announcement",
        "title": "Role Changed",
        "message": "Your role in group 'Team' has been changed from User to Admin by adam.admin@example.test.",
        "link_url": "/groups/g-1",
        "metadata": {
            "group_id": "g-1", "group_name": "Team", "changed_by": "adam.admin@example.test",
            "old_role": "User", "new_role": "Admin",
        },
    }]


@pytest.mark.parametrize("caller,target,body,expected", [
    ("owner-1", "member-1", {"role": "Owner"}, (400, {"error": "Invalid role. Must be Admin, DocumentManager, or User"})),
    ("manager-1", "member-1", {"role": "Admin"}, (403, {"error": "Only the owner or admin can update roles"})),
    ("owner-1", "outsider-1", {"role": "Admin"}, (404, {"error": "Member is not in the group"})),
])
def test_classic_role_change_refusals(env, caller, target, body, expected):
    seed(env)
    env.as_user(caller)
    assert answer(env.call("PATCH", f"/api/groups/g-1/members/{target}", body)) == expected
    assert env.write_calls() == [] and env.notifications == []


def test_classic_role_change_on_the_owner_stores_invalid_data(env):
    """Recorded: decision 4 turns it into a 409 in the classic route."""
    seed(env)
    env.as_user("admin-1")
    assert env.call("PATCH", "/api/groups/g-1/members/owner-1", {"role": "Admin"}).status_code == 200
    assert "owner-1" in env.stored_group("g-1")["admins"]


def test_classic_role_change_on_a_missing_group(env):
    env.as_user("owner-1")
    assert answer(env.call("PATCH", "/api/groups/g-missing/members/member-1", {"role": "Admin"})) == (
        404, {"error": "Group not found"},
    )


# ---------------------------------------------------------------------------
# GET /api/groups/<g>/members
# ---------------------------------------------------------------------------

def test_classic_member_list(env):
    document = group_document("g-1", "Team")
    document["users"].append(person("member-1"))
    env.seed_document(document)
    env.as_user("member-1")
    status, body = answer(env.call("GET", "/api/groups/g-1/members"))
    assert status == 200
    assert [(row["userId"], row["role"]) for row in body] == [
        ("owner-1", "Owner"), ("admin-1", "Admin"), ("manager-1", "DocumentManager"),
        ("member-1", "User"), ("member-1", "User"),
    ]
    assert set(body[0]) == {"userId", "displayName", "email", "role"}
    assert [row["userId"] for row in env.call("GET", "/api/groups/g-1/members?search=MIA").get_json()] == ["manager-1"]
    assert [row["userId"] for row in env.call("GET", "/api/groups/g-1/members?role=Admin").get_json()] == ["admin-1"]
    env.as_user("outsider-1")
    assert answer(env.call("GET", "/api/groups/g-1/members")) == (403, {"error": "You are not a member of this group"})


def test_classic_member_list_breaks_on_malformed_entries(env):
    """Recorded: the member list fix skips them (commit 3)."""
    document = group_document("g-1", "Team")
    document["users"].append({"email": "no-id@example.test"})
    env.seed_document(document)
    env.as_user("member-1")
    with pytest.raises(KeyError):
        env.call("GET", "/api/groups/g-1/members")
    document = group_document("g-1", "Team")
    document["users"].append({"userId": "outsider-1", "displayName": None, "email": None})
    env.seed_document(document)
    with pytest.raises(AttributeError):
        env.call("GET", "/api/groups/g-1/members?search=x")


# ---------------------------------------------------------------------------
# PATCH /api/groups/<g>/transferOwnership
# ---------------------------------------------------------------------------

def test_classic_transfer(env):
    seed(env)
    env.as_user("owner-1")
    assert answer(env.call("PATCH", "/api/groups/g-1/transferOwnership", {"newOwnerId": "admin-1"})) == (
        200, {"message": "Ownership transferred successfully"},
    )
    stored = env.stored_group("g-1")
    assert stored["owner"] == {"id": "admin-1", "email": "adam.admin@example.test", "displayName": "Adam Admin"}
    assert "admin-1" not in stored["admins"] and person("owner-1") in stored["users"]
    assert env.bumps == ["group_ownership_transferred"]
    assert env.notifications == [] and env.activity_records() == []


@pytest.mark.parametrize("caller,body,expected", [
    ("owner-1", {}, (400, {"error": "Missing newOwnerId"})),
    ("admin-1", {"newOwnerId": "member-1"}, (403, {"error": "Only the current owner can transfer ownership"})),
    ("owner-1", {"newOwnerId": "outsider-1"}, (400, {"error": "The specified new owner is not a member of the group"})),
])
def test_classic_transfer_refusals(env, caller, body, expected):
    seed(env)
    env.as_user(caller)
    assert answer(env.call("PATCH", "/api/groups/g-1/transferOwnership", body)) == expected
    assert env.write_calls() == []


def test_classic_transfer_on_a_missing_group(env):
    env.as_user("owner-1")
    assert answer(env.call("PATCH", "/api/groups/g-missing/transferOwnership", {"newOwnerId": "x"})) == (
        404, {"error": "Group not found"},
    )


def test_classic_transfer_appends_a_missing_old_owner_bare(env):
    """Recorded: decision 5 appends the old owner with their email and name."""
    document = group_document("g-1", "Team")
    document["users"] = [entry for entry in document["users"] if entry["userId"] != "owner-1"]
    env.seed_document(document)
    env.as_user("owner-1")
    assert env.call("PATCH", "/api/groups/g-1/transferOwnership", {"newOwnerId": "member-1"}).status_code == 200
    assert env.stored_group("g-1")["users"][-1] == {"userId": "owner-1"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
