# test_group_membership_apis.py
"""
Functional test for the native group membership APIs.
Version: 0.261.150
Implemented in: 0.261.150

The ``/api/groups/<group_id>/membership/...`` routes run for real
(``functions_group``, the membership modules and the classic
``route_backend_groups``, registered as ``app.py`` does) against the etag-enforcing
groups container, an activity container and an in-memory directory
(``test_support/group_directory_harness.py``).

It pins:

- the member list: its exact projection, ordering, de-duplication, search, role
  filter, paging and strict parameters, and the ``membership_management`` hint;
- the pending-request list, for the Owner and Admins;
- every write: its gates, its reviewed messages and error codes, and what it
  stores, including decisions 2 to 5 and 8 (status, pending clean-up, owner
  target, transfer data, directory resolution);
- every write's guard race: a concurrent change is kept, a group deleted mid-write
  is a 404 and is never recreated, a group that keeps changing is a 409, and a
  demotion or removal that lands mid-write refuses the write;
- the session and configuration gates of all eight routes, and no-store.
"""

import json

import pytest
import requests

from test_support.group_directory_harness import group_directory_environment, group_document, person


ROW_KEYS = {"userId", "displayName", "email", "role", "member_actions"}
ROUTES = [
    ("GET", "/api/groups/g-1/membership/members", None),
    ("POST", "/api/groups/g-1/membership/members", {"userId": "newcomer-1", "role": "User"}),
    ("PATCH", "/api/groups/g-1/membership/members/member-1", {"role": "Admin"}),
    ("DELETE", "/api/groups/g-1/membership/members/member-1", None),
    ("GET", "/api/groups/g-1/membership/requests", None),
    ("POST", "/api/groups/g-1/membership/requests/applicant-1/approve", None),
    ("POST", "/api/groups/g-1/membership/requests/applicant-1/reject", None),
    ("PUT", "/api/groups/g-1/membership/owner", {"userId": "member-1"}),
]


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


def assert_refused(response, status, message, error_code):
    assert response.status_code == status, response.get_json()
    assert response.get_json() == {"error": message, "error_code": error_code}
    assert response.headers["Cache-Control"] == "no-store"


def assert_nothing_written(env):
    assert env.write_calls() == []
    assert env.bumps == [] and env.notifications == [] and env.activity_records() == []


def land(env, change):
    """A concurrent writer that commits ``change`` between a guarded read and its replace."""
    def concurrent():
        record = env.stored_group("g-1")
        change(record)
        env.groups.seed(record)
    return concurrent


def rows(response):
    assert response.status_code == 200, response.get_json()
    return response.get_json()["members"]


def ids(response):
    return [row["userId"] for row in rows(response)]


# ---------------------------------------------------------------------------
# The member list
# ---------------------------------------------------------------------------

def test_every_member_gets_the_member_list_projection(env):
    seed(env, pending=("applicant-1",))
    for caller in ("owner-1", "admin-1", "manager-1", "member-1"):
        env.as_user(caller)
        response = env.members("g-1")
        assert response.headers["Cache-Control"] == "no-store"
        payload = response.get_json()
        assert set(payload) == {"members", "page", "page_size", "total_count", "membership_management"}
        assert (payload["page"], payload["page_size"], payload["total_count"]) == (1, 20, 4)
        assert payload["membership_management"]["schema_version"] == 1
        for row in payload["members"]:
            assert set(row) == ROW_KEYS
        text = json.dumps(payload)
        assert "applicant" not in text and "sk-secret-endpoint-key" not in text and "pendingUsers" not in text


def test_rows_are_ordered_by_role_then_name_then_id(env):
    document = group_document("g-1", "Team", admins=("admin-1",), managers=(), members=("member-1", "outsider-1"))
    document["users"].append({"userId": "applicant-1", "email": "", "displayName": "max member"})
    env.seed_document(document)
    env.as_user("member-1")
    assert [(row["role"], row["userId"]) for row in rows(env.members("g-1"))] == [
        ("Owner", "owner-1"), ("Admin", "admin-1"),
        # "max member" and "Max Member" casefold alike, so the id breaks the tie.
        ("User", "applicant-1"), ("User", "member-1"), ("User", "outsider-1"),
    ]


def test_the_list_repairs_what_the_classic_list_repeats_or_omits(env):
    document = group_document("g-1", "Team", managers=())
    document["users"] = [
        person("admin-1"), person("member-1"), dict(person("member-1"), displayName="Duplicate"),
        {"email": "no-id@example.test"}, "member-1", None,
        {"userId": "outsider-1", "displayName": None, "email": None},
    ]
    env.seed_document(document)
    env.as_user("member-1")
    listed = rows(env.members("g-1"))
    # The unnamed member sorts first among the Users.
    assert [row["userId"] for row in listed] == ["owner-1", "admin-1", "outsider-1", "member-1"]
    assert listed[0]["displayName"] == "Olive Owner"  # the owner, added from ``owner``
    assert (listed[2]["displayName"], listed[2]["email"]) == ("", "")
    assert listed[3]["displayName"] == "Max Member"  # the first entry wins


def test_search_matches_a_casefolded_name_or_email_or_the_exact_id(env):
    seed(env)
    env.as_user("member-1")
    assert ids(env.members("g-1", {"search": "MAX"})) == ["member-1"]
    assert ids(env.members("g-1", {"search": "mia.manager@"})) == ["manager-1"]
    assert ids(env.members("g-1", {"search": "admin-1"})) == ["admin-1"]
    assert ids(env.members("g-1", {"search": "admin-"})) == []  # an id matches only exactly
    assert ids(env.members("g-1", {"search": "OLIVE.OWNER@EXAMPLE.TEST"})) == ["owner-1"]
    assert ids(env.members("g-1", {"search": "nobody"})) == []
    assert ids(env.members("g-1", {"search": "   "})) == ["owner-1", "admin-1", "manager-1", "member-1"]


def test_the_role_filter_is_exact(env):
    seed(env)
    env.as_user("member-1")
    for role, expected in (("Owner", ["owner-1"]), ("Admin", ["admin-1"]), ("DocumentManager", ["manager-1"]), ("User", ["member-1"])):
        response = env.members("g-1", {"role": role})
        assert ids(response) == expected and response.get_json()["total_count"] == 1


def test_pages_are_cut_after_filtering_and_sorting(env):
    document = group_document("g-1", "Team", admins=(), managers=(), members=())
    document["users"].extend({"userId": f"user-{index:02d}", "email": "", "displayName": f"Person {index:02d}"} for index in range(30))
    env.seed_document(document)
    env.as_user("owner-1")
    first = env.members("g-1")
    assert len(rows(first)) == 20 and first.get_json()["total_count"] == 31
    second = env.members("g-1", {"page": "2"})
    assert ids(second) == [f"user-{index:02d}" for index in range(19, 30)]
    assert rows(env.members("g-1", {"page": "3"})) == []
    assert ids(env.members("g-1", {"page": "2", "page_size": "5", "role": "User"})) == [f"user-{index:02d}" for index in range(5, 10)]
    assert len(rows(env.members("g-1", {"page_size": "100"}))) == 31


@pytest.mark.parametrize("query_string,message", [
    ("q=x", "Use only the search, role, page and page_size query parameters."),
    ("role=User&role=Admin", "Give each query parameter only once."),
    ("role=user", "The role must be Owner, Admin, DocumentManager or User."),
    ("role=", "The role must be Owner, Admin, DocumentManager or User."),
    ("page=0", "The page must be a whole number from 1 to 10000."),
    ("page=abc", "The page must be a whole number from 1 to 10000."),
    ("page=10001", "The page must be a whole number from 1 to 10000."),
    ("page_size=101", "The page size must be a whole number from 1 to 100."),
    ("page_size=0", "The page size must be a whole number from 1 to 100."),
    ("search=" + "x" * 201, "Search terms can be at most 200 characters."),
])
def test_unknown_repeated_or_malformed_parameters_are_refused(env, query_string, message):
    seed(env)
    env.as_user("member-1")
    assert_refused(env.call("GET", f"/api/groups/g-1/membership/members?{query_string}"), 400, message, "invalid_request")


def test_a_body_on_the_member_list_is_refused(env):
    seed(env)
    env.as_user("member-1")
    assert_refused(
        env.call("GET", "/api/groups/g-1/membership/members", {"role": "User"}), 400,
        "This request does not accept a request body.", "invalid_request",
    )


def test_only_members_can_list_members(env):
    seed(env)
    env.as_user("outsider-1")
    assert_refused(env.members("g-1"), 403, "You're not a member of this group.", "not_a_member")
    assert_refused(env.members("g-missing"), 404, "Group not found.", "group_not_found")
    env.seed_group("g-typed", "Typed", type="group_settings")
    env.as_user("member-1")
    assert_refused(env.members("g-typed"), 404, "Group not found.", "group_not_found")


@pytest.mark.parametrize("status", ["active", "upload_disabled", "locked", "inactive", "archived"])
def test_every_status_allows_reading_members_and_requests(env, status):
    seed(env, status=status, pending=("applicant-1",))
    env.as_user("admin-1")
    assert env.members("g-1").status_code == 200
    assert env.pending_requests("g-1").status_code == 200


def test_the_hint_follows_the_callers_role_and_the_status(env):
    seed(env, status="locked")
    env.as_user("admin-1")
    assert env.members("g-1").get_json()["membership_management"]["operations"] == [
        "review_requests", "change_role", "remove_member", "leave",
    ]
    env.as_user("member-1")
    assert env.members("g-1").get_json()["membership_management"]["operations"] == ["leave"]


# ---------------------------------------------------------------------------
# Pending requests
# ---------------------------------------------------------------------------

def test_the_owner_and_admins_see_each_pending_request_once(env):
    document = group_document("g-1", "Team", pending=("outsider-1", "applicant-1"))
    document["pendingUsers"].extend([person("applicant-1"), {"email": "no-id@example.test"}, None])
    env.seed_document(document)
    for caller in ("owner-1", "admin-1"):
        env.as_user(caller)
        response = env.pending_requests("g-1")
        assert response.headers["Cache-Control"] == "no-store"
        assert response.get_json() == {
            "requests": [person("applicant-1"), person("outsider-1")],
            "total_count": 2,
        }


def test_other_members_cannot_see_pending_requests(env):
    seed(env, pending=("applicant-1",))
    for caller in ("manager-1", "member-1"):
        env.as_user(caller)
        assert_refused(
            env.pending_requests("g-1"), 403,
            "Only the group's owner or an admin can manage its members.", "membership_permission",
        )
    env.as_user("applicant-1")
    assert_refused(env.pending_requests("g-1"), 403, "You're not a member of this group.", "not_a_member")


def test_the_request_list_takes_no_query_or_body(env):
    seed(env)
    env.as_user("owner-1")
    assert_refused(
        env.call("GET", "/api/groups/g-1/membership/requests?page=1"), 400,
        "This request does not accept query parameters.", "invalid_request",
    )


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------

def test_add_stores_the_directory_identity_and_the_role(env):
    seed(env, pending=("newcomer-1",))
    document = env.stored_group("g-1")
    document["pendingUsers"].append(person("newcomer-1"))
    env.seed_document(document)
    env.add_directory_user("newcomer-1")
    env.as_user("admin-1")
    response = env.add_member("g-1", {"userId": "newcomer-1", "displayName": "Typed Name", "email": "typed@example.test", "role": "DocumentManager"})
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {"member": {
        "userId": "newcomer-1", "displayName": "Nia Newcomer", "email": "nia.newcomer@example.test",
        "role": "DocumentManager", "member_actions": ["change_role", "remove"],
    }}
    stored = env.stored_group("g-1")
    assert stored["users"][-1] == person("newcomer-1")
    assert "newcomer-1" in stored["documentManagers"] and "newcomer-1" not in stored["admins"]
    assert stored["pendingUsers"] == []
    assert env.bumps == ["group_member_added"]
    assert env.directory_calls == [("by_id", "newcomer-1")]


@pytest.mark.parametrize("role,list_name", [("Admin", "admins"), ("DocumentManager", "documentManagers"), ("User", None)])
def test_add_records_the_role_in_the_classic_lists(env, role, list_name):
    seed(env)
    env.add_directory_user("newcomer-1")
    env.as_user("owner-1")
    assert env.add_member("g-1", {"userId": "newcomer-1", "role": role}).status_code == 201
    stored = env.stored_group("g-1")
    for name in ("admins", "documentManagers"):
        assert ("newcomer-1" in stored[name]) == (name == list_name)


def test_a_user_the_directory_does_not_know_is_refused(env):
    seed(env)
    env.as_user("owner-1")
    assert_refused(
        env.add_member("g-1", {"userId": "ghost-1", "displayName": "Ghost", "role": "User"}), 400,
        "That user wasn't found in the directory.", "user_not_found",
    )
    assert_nothing_written(env)


@pytest.mark.parametrize("failure", [
    PermissionError("Could not acquire access token"),
    requests.exceptions.HTTPError("403 Client Error: Forbidden"),
    requests.exceptions.ConnectionError("unreachable"),
    requests.exceptions.Timeout("slow"),
])
def test_an_unavailable_directory_falls_back_to_the_submitted_details(env, failure):
    """Decision 8: a known limitation, as classic trusts the submitted details."""
    seed(env)
    env.directory_failure = failure
    env.as_user("owner-1")
    response = env.add_member("g-1", {"userId": "newcomer-1", "displayName": "Typed Name", "email": "typed@example.test", "role": "User"})
    assert response.status_code == 201
    assert env.stored_group("g-1")["users"][-1] == {"userId": "newcomer-1", "email": "typed@example.test", "displayName": "Typed Name"}
    [log] = [entry for entry in env.logs if "directory lookup" in entry[0]]
    assert log == (
        "[WORKSPACE_ROUTE] Group member directory lookup was unavailable; the submitted details were used.",
        30, {"error_type": type(failure).__name__},
    )


def test_an_unavailable_directory_without_details_uses_the_id(env):
    seed(env)
    env.directory_failure = PermissionError("Could not acquire access token")
    env.as_user("owner-1")
    assert env.add_member("g-1", {"userId": "newcomer-1", "role": "User"}).status_code == 201
    assert env.stored_group("g-1")["users"][-1] == {"userId": "newcomer-1", "email": "", "displayName": "newcomer-1"}


@pytest.mark.parametrize("caller,message,code", [
    ("manager-1", "Only the group's owner or an admin can manage its members.", "membership_permission"),
    ("member-1", "Only the group's owner or an admin can manage its members.", "membership_permission"),
    ("outsider-1", "You're not a member of this group.", "not_a_member"),
])
def test_only_the_owner_and_admins_add(env, caller, message, code):
    seed(env)
    env.add_directory_user("newcomer-1")
    env.as_user(caller)
    assert_refused(env.add_member("g-1", {"userId": "newcomer-1", "role": "User"}), 403, message, code)
    assert env.directory_calls == []
    assert_nothing_written(env)


@pytest.mark.parametrize("status,allowed", [
    ("active", True), ("upload_disabled", True), (None, True),
    ("locked", False), ("inactive", False), ("archived", False),
])
def test_add_follows_the_group_status(env, status, allowed):
    """Decision 2: adding needs an active or upload_disabled group."""
    seed(env, **({} if status is None else {"status": status}))
    env.add_directory_user("newcomer-1")
    env.as_user("owner-1")
    response = env.add_member("g-1", {"userId": "newcomer-1", "role": "User"})
    if allowed:
        assert response.status_code == 201
    else:
        assert_refused(
            response, 403, "Members can't be added to this group in its current status.", "group_status_unavailable",
        )
        assert env.directory_calls == []
        assert_nothing_written(env)


def test_adding_an_existing_member_is_refused(env):
    seed(env)
    env.add_directory_user("member-1")
    env.as_user("owner-1")
    assert_refused(
        env.add_member("g-1", {"userId": "member-1", "role": "Admin"}), 409,
        "That person is already a member of this group.", "already_member",
    )
    assert_nothing_written(env)


@pytest.mark.parametrize("body,message", [
    ({"role": "User"}, "Invalid user identifier."),
    ({"userId": "", "role": "User"}, "Invalid user identifier."),
    ({"userId": "a,b", "role": "User"}, "Invalid user identifier."),
    ({"userId": 7, "role": "User"}, "Invalid user identifier."),
    ({"userId": "newcomer-1"}, "The role must be Admin, DocumentManager or User."),
    ({"userId": "newcomer-1", "role": "Owner"}, "The role must be Admin, DocumentManager or User."),
    ({"userId": "newcomer-1", "role": "user"}, "The role must be Admin, DocumentManager or User."),
    ({"userId": "newcomer-1", "role": "User", "admins": ["x"]}, "Only userId, displayName, email and role can be sent when adding a member."),
    ({"userId": "newcomer-1", "role": "User", "displayName": 3}, "The display name must be text."),
    ({"userId": "newcomer-1", "role": "User", "email": None}, "The email must be text."),
    ({"userId": "newcomer-1", "role": "User", "displayName": "a\nb"}, "The display name can't contain control characters."),
    ({"userId": "newcomer-1", "role": "User", "email": "x" * 257}, "The email can be at most 256 characters."),
])
def test_add_validates_the_body(env, body, message):
    seed(env)
    env.as_user("owner-1")
    assert_refused(env.add_member("g-1", body), 400, message, "invalid_request")
    assert_nothing_written(env)


def test_add_refuses_a_non_json_body_and_query_parameters(env):
    seed(env)
    env.as_user("owner-1")
    assert_refused(
        env.call("POST", "/api/groups/g-1/membership/members", raw='{"userId": "a", "userId": "b"}'), 400,
        "Duplicate fields are not supported.", "invalid_request",
    )
    assert_refused(
        env.call("POST", "/api/groups/g-1/membership/members", {"userId": "a", "role": "User"}, query_string={"x": "1"}),
        400, "This request does not accept query parameters.", "invalid_request",
    )


def test_an_approval_landing_mid_add_refuses_the_add(env):
    seed(env)
    env.add_directory_user("newcomer-1")
    env.groups.before_replace.append(land(env, lambda record: record["users"].append(person("newcomer-1"))))
    env.as_user("owner-1")
    assert_refused(
        env.add_member("g-1", {"userId": "newcomer-1", "role": "User"}), 409,
        "That person is already a member of this group.", "already_member",
    )
    assert [entry["userId"] for entry in env.stored_group("g-1")["users"]].count("newcomer-1") == 1
    assert env.bumps == [] and env.notifications == [] and env.activity_records() == []


def test_a_demotion_landing_mid_add_refuses_the_add(env):
    seed(env)
    env.add_directory_user("newcomer-1")
    env.groups.before_replace.append(land(env, lambda record: record["admins"].remove("admin-1")))
    env.as_user("admin-1")
    assert_refused(
        env.add_member("g-1", {"userId": "newcomer-1", "role": "User"}), 403,
        "Only the group's owner or an admin can manage its members.", "membership_permission",
    )
    assert "newcomer-1" not in [entry["userId"] for entry in env.stored_group("g-1")["users"]]


def test_a_lock_landing_mid_add_refuses_the_add(env):
    seed(env)
    env.add_directory_user("newcomer-1")
    env.groups.before_replace.append(land(env, lambda record: record.update(status="locked")))
    env.as_user("owner-1")
    assert_refused(
        env.add_member("g-1", {"userId": "newcomer-1", "role": "User"}), 403,
        "Members can't be added to this group in its current status.", "group_status_unavailable",
    )


# ---------------------------------------------------------------------------
# Role change
# ---------------------------------------------------------------------------

def test_a_role_change_updates_the_classic_lists(env):
    seed(env)
    env.as_user("admin-1")
    response = env.change_role("g-1", "member-1", {"role": "Admin"})
    assert response.status_code == 200
    assert response.get_json() == {"changed": True, "member": {
        "userId": "member-1", "displayName": "Max Member", "email": "max.member@example.test",
        "role": "Admin", "member_actions": ["change_role", "remove"],
    }}
    stored = env.stored_group("g-1")
    assert "member-1" in stored["admins"] and "member-1" not in stored["documentManagers"]
    assert env.bumps == ["group_member_role_updated"]
    env.change_role("g-1", "member-1", {"role": "User"})
    stored = env.stored_group("g-1")
    assert "member-1" not in stored["admins"] and "member-1" not in stored["documentManagers"]


def test_changing_to_the_role_already_held_writes_nothing(env):
    seed(env)
    env.as_user("owner-1")
    response = env.change_role("g-1", "manager-1", {"role": "DocumentManager"})
    assert response.status_code == 200 and response.get_json()["changed"] is False
    assert_nothing_written(env)


def test_the_owners_role_cannot_be_changed(env):
    """Decision 4."""
    seed(env)
    for caller in ("owner-1", "admin-1"):
        env.as_user(caller)
        assert_refused(
            env.change_role("g-1", "owner-1", {"role": "Admin"}), 409,
            "Transfer ownership to change the owner's role.", "owner_target",
        )
    assert_nothing_written(env)
    assert "owner-1" not in env.stored_group("g-1")["admins"]


def test_an_admin_may_demote_themselves_and_other_admins(env):
    document = group_document("g-1", "Team", admins=("admin-1", "outsider-1"))
    env.seed_document(document)
    env.as_user("admin-1")
    assert env.change_role("g-1", "outsider-1", {"role": "User"}).status_code == 200
    assert env.change_role("g-1", "admin-1", {"role": "User"}).status_code == 200
    assert env.stored_group("g-1")["admins"] == []


@pytest.mark.parametrize("caller,target,status,message,code", [
    ("manager-1", "member-1", 403, "Only the group's owner or an admin can manage its members.", "membership_permission"),
    ("member-1", "member-1", 403, "Only the group's owner or an admin can manage its members.", "membership_permission"),
    ("outsider-1", "member-1", 403, "You're not a member of this group.", "not_a_member"),
    ("owner-1", "outsider-1", 404, "That person isn't a member of this group.", "member_not_found"),
])
def test_role_change_refusals(env, caller, target, status, message, code):
    seed(env)
    env.as_user(caller)
    assert_refused(env.change_role("g-1", target, {"role": "Admin"}), status, message, code)
    assert_nothing_written(env)


@pytest.mark.parametrize("body,message", [
    ({}, "The role must be Admin, DocumentManager or User."),
    ({"role": "Owner"}, "The role must be Admin, DocumentManager or User."),
    ({"role": "Admin", "userId": "x"}, "Send only the role to change a member's role."),
])
def test_role_change_validates_the_body(env, body, message):
    seed(env)
    env.as_user("owner-1")
    assert_refused(env.change_role("g-1", "member-1", body), 400, message, "invalid_request")


def test_a_demotion_landing_mid_role_change_refuses_it(env):
    seed(env)
    env.groups.before_replace.append(land(env, lambda record: record["admins"].remove("admin-1")))
    env.as_user("admin-1")
    assert_refused(
        env.change_role("g-1", "member-1", {"role": "Admin"}), 403,
        "Only the group's owner or an admin can manage its members.", "membership_permission",
    )
    assert "member-1" not in env.stored_group("g-1")["admins"]
    assert env.notifications == [] and env.activity_records() == []


# ---------------------------------------------------------------------------
# Remove and leave
# ---------------------------------------------------------------------------

def test_removing_a_member_drops_every_trace_of_their_role(env):
    document = group_document("g-1", "Team", admins=("admin-1",), managers=("manager-1",))
    document["users"].append(person("manager-1"))
    env.seed_document(document)
    env.as_user("admin-1")
    response = env.remove_member("g-1", "manager-1")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {"userId": "manager-1", "left": False}
    stored = env.stored_group("g-1")
    assert "manager-1" not in [entry["userId"] for entry in stored["users"]]
    assert "manager-1" not in stored["documentManagers"]
    assert env.bumps == ["group_member_removed"]


@pytest.mark.parametrize("caller,target,status,message,code", [
    ("owner-1", "owner-1", 409, "Transfer ownership before leaving the group.", "owner_cannot_leave"),
    ("admin-1", "owner-1", 409, "Transfer ownership before removing the owner.", "owner_target"),
    ("manager-1", "member-1", 403, "Only the group's owner or an admin can manage its members.", "membership_permission"),
    ("member-1", "manager-1", 403, "Only the group's owner or an admin can manage its members.", "membership_permission"),
    ("outsider-1", "member-1", 403, "You're not a member of this group.", "not_a_member"),
    ("outsider-1", "outsider-1", 403, "You're not a member of this group.", "not_a_member"),
    ("owner-1", "applicant-1", 404, "That person isn't a member of this group.", "member_not_found"),
])
def test_remove_and_leave_refusals(env, caller, target, status, message, code):
    seed(env)
    env.as_user(caller)
    assert_refused(env.remove_member("g-1", target), status, message, code)
    assert_nothing_written(env)


@pytest.mark.parametrize("caller", ["admin-1", "manager-1", "member-1"])
def test_any_member_but_the_owner_can_leave(env, caller):
    seed(env)
    env.as_user(caller)
    response = env.remove_member("g-1", caller)
    assert response.get_json() == {"userId": caller, "left": True}
    stored = env.stored_group("g-1")
    assert caller not in [entry["userId"] for entry in stored["users"]]
    assert caller not in stored["admins"] and caller not in stored["documentManagers"]


def test_removing_a_role_holder_without_a_users_entry_cleans_up_quietly(env):
    document = group_document("g-1", "Team")
    document["users"] = [entry for entry in document["users"] if entry["userId"] != "manager-1"]
    env.seed_document(document)
    env.as_user("owner-1")
    assert env.remove_member("g-1", "manager-1").status_code == 200
    assert env.stored_group("g-1")["documentManagers"] == []
    assert env.bumps == [] and env.activity_records() == []


def test_remove_takes_no_body_or_query(env):
    seed(env)
    env.as_user("owner-1")
    assert_refused(
        env.call("DELETE", "/api/groups/g-1/membership/members/member-1", {}), 400,
        "This request does not accept a request body.", "invalid_request",
    )
    assert_refused(
        env.call("DELETE", "/api/groups/g-1/membership/members/member-1", query_string={"force": "1"}), 400,
        "This request does not accept query parameters.", "invalid_request",
    )


def test_a_removal_landing_mid_remove_is_a_404(env):
    seed(env)
    env.groups.before_replace.append(land(env, lambda record: record.update(
        users=[entry for entry in record["users"] if entry["userId"] != "member-1"],
    )))
    env.as_user("owner-1")
    assert_refused(env.remove_member("g-1", "member-1"), 404, "That person isn't a member of this group.", "member_not_found")
    assert env.activity_records() == [] and env.bumps == []


# ---------------------------------------------------------------------------
# Approve and reject
# ---------------------------------------------------------------------------

def test_approve_adds_the_requester_once_and_clears_every_entry(env):
    document = group_document("g-1", "Team", pending=("applicant-1", "outsider-1"))
    document["pendingUsers"].append(person("applicant-1"))
    env.seed_document(document)
    env.as_user("admin-1")
    response = env.approve("g-1", "applicant-1")
    assert response.status_code == 200
    assert response.get_json() == {"already_member": False, "member": {
        "userId": "applicant-1", "displayName": "Ana Applicant", "email": "ana.applicant@example.test",
        "role": "User", "member_actions": ["change_role", "remove"],
    }}
    stored = env.stored_group("g-1")
    assert [entry["userId"] for entry in stored["users"]].count("applicant-1") == 1
    assert stored["users"][-1] == person("applicant-1")
    assert stored["pendingUsers"] == [person("outsider-1")]
    assert env.bumps == ["group_member_request_approved"]
    assert env.notifications == [] and env.activity_records() == []


def test_approving_an_existing_member_only_clears_their_entries(env):
    """Decision 3: no duplicate member."""
    seed(env, pending=("member-1",))
    env.as_user("owner-1")
    response = env.approve("g-1", "member-1")
    assert response.status_code == 200 and response.get_json()["already_member"] is True
    stored = env.stored_group("g-1")
    assert [entry["userId"] for entry in stored["users"]].count("member-1") == 1
    assert stored["pendingUsers"] == []


def test_reject_clears_every_entry_without_a_bump(env):
    document = group_document("g-1", "Team", pending=("applicant-1", "outsider-1"))
    document["pendingUsers"].append(person("applicant-1"))
    env.seed_document(document)
    env.as_user("owner-1")
    response = env.reject("g-1", "applicant-1")
    assert response.status_code == 200 and response.get_json() == {"userId": "applicant-1"}
    assert env.stored_group("g-1")["pendingUsers"] == [person("outsider-1")]
    assert env.bumps == []
    assert "applicant-1" not in [entry["userId"] for entry in env.stored_group("g-1")["users"]]


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_deciding_without_a_request_is_refused(env, decision):
    seed(env)
    env.as_user("owner-1")
    assert_refused(
        getattr(env, decision)("g-1", "applicant-1"), 409,
        "That person doesn't have a pending request to join this group.", "no_pending_request",
    )
    assert_nothing_written(env)


@pytest.mark.parametrize("decision", ["approve", "reject"])
@pytest.mark.parametrize("caller", ["manager-1", "member-1"])
def test_only_the_owner_and_admins_decide(env, decision, caller):
    seed(env, pending=("applicant-1",))
    env.as_user(caller)
    assert_refused(
        getattr(env, decision)("g-1", "applicant-1"), 403,
        "Only the group's owner or an admin can manage its members.", "membership_permission",
    )
    assert env.stored_group("g-1")["pendingUsers"] == [person("applicant-1")]


@pytest.mark.parametrize("status", ["locked", "inactive", "archived"])
def test_decisions_are_allowed_in_every_status(env, status):
    seed(env, status=status, pending=("applicant-1", "outsider-1"))
    env.as_user("owner-1")
    assert env.approve("g-1", "applicant-1").status_code == 200
    assert env.reject("g-1", "outsider-1").status_code == 200


def test_a_cancel_landing_mid_approve_is_refused_on_the_retry(env):
    seed(env, pending=("applicant-1",))
    env.groups.before_replace.append(land(env, lambda record: record["pendingUsers"].clear()))
    env.as_user("owner-1")
    assert_refused(
        env.approve("g-1", "applicant-1"), 409,
        "That person doesn't have a pending request to join this group.", "no_pending_request",
    )
    assert "applicant-1" not in [entry["userId"] for entry in env.stored_group("g-1")["users"]]


# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------

def test_transfer_moves_ownership_and_keeps_the_old_owner_as_a_user(env):
    seed(env)
    env.as_user("owner-1")
    response = env.transfer("g-1", {"userId": "admin-1"})
    assert response.status_code == 200
    assert response.get_json() == {"changed": True, "owner": {
        "userId": "admin-1", "displayName": "Adam Admin", "email": "adam.admin@example.test",
        "role": "Owner", "member_actions": [],
    }}
    stored = env.stored_group("g-1")
    assert stored["owner"] == {"id": "admin-1", "email": "adam.admin@example.test", "displayName": "Adam Admin"}
    assert "admin-1" not in stored["admins"]
    assert person("owner-1") in stored["users"]
    assert env.bumps == ["group_ownership_transferred"]
    env.as_user("owner-1")
    [row] = [row for row in rows(env.members("g-1")) if row["userId"] == "owner-1"]
    assert row["role"] == "User"


def test_an_old_owner_missing_from_users_is_appended_with_their_details(env):
    """Decision 5."""
    document = group_document("g-1", "Team")
    document["users"] = [entry for entry in document["users"] if entry["userId"] != "owner-1"]
    document["admins"].append("owner-1")
    env.seed_document(document)
    env.as_user("owner-1")
    assert env.transfer("g-1", {"userId": "member-1"}).status_code == 200
    stored = env.stored_group("g-1")
    assert stored["users"][-1] == {"userId": "owner-1", "email": "olive.owner@example.test", "displayName": "Olive Owner"}
    assert "owner-1" not in stored["admins"]


@pytest.mark.parametrize("caller", ["owner-1", "admin-1", "manager-1", "member-1"])
def test_a_transfer_to_the_current_owner_is_a_no_op_for_any_member(env, caller):
    """Decision 5: a retry after a lost response succeeds without a write."""
    seed(env)
    env.as_user(caller)
    response = env.transfer("g-1", {"userId": "owner-1"})
    assert response.status_code == 200 and response.get_json()["changed"] is False
    assert response.get_json()["owner"]["userId"] == "owner-1"
    assert_nothing_written(env)


@pytest.mark.parametrize("caller,target,status,message,code", [
    ("admin-1", "member-1", 403, "Only the group's owner can transfer ownership.", "owner_only"),
    ("member-1", "manager-1", 403, "Only the group's owner can transfer ownership.", "owner_only"),
    ("outsider-1", "owner-1", 403, "You're not a member of this group.", "not_a_member"),
    ("owner-1", "outsider-1", 404, "That person isn't a member of this group.", "member_not_found"),
])
def test_transfer_refusals(env, caller, target, status, message, code):
    seed(env)
    env.as_user(caller)
    assert_refused(env.transfer("g-1", {"userId": target}), status, message, code)
    assert_nothing_written(env)


def test_a_transfer_needs_a_users_entry_for_the_new_owner(env):
    document = group_document("g-1", "Team")
    document["users"] = [entry for entry in document["users"] if entry["userId"] != "admin-1"]
    env.seed_document(document)
    env.as_user("owner-1")
    assert_refused(env.transfer("g-1", {"userId": "admin-1"}), 404, "That person isn't a member of this group.", "member_not_found")


@pytest.mark.parametrize("body,message", [
    ({}, "Invalid user identifier."),
    ({"userId": "admin-1", "keepRole": True}, "Send only the userId of the new owner."),
    ({"newOwnerId": "admin-1"}, "Send only the userId of the new owner."),
])
def test_transfer_validates_the_body(env, body, message):
    seed(env)
    env.as_user("owner-1")
    assert_refused(env.transfer("g-1", body), 400, message, "invalid_request")


def test_a_transfer_landing_first_makes_a_retry_a_no_op(env):
    seed(env)
    env.groups.before_replace.append(land(env, lambda record: record.update(
        owner={"id": "admin-1", "email": "adam.admin@example.test", "displayName": "Adam Admin"},
    )))
    env.as_user("owner-1")
    response = env.transfer("g-1", {"userId": "admin-1"})
    assert response.status_code == 200 and response.get_json()["changed"] is False
    assert env.bumps == []


# ---------------------------------------------------------------------------
# Guard races shared by every write
# ---------------------------------------------------------------------------

WRITES = {
    "add": lambda env: env.add_member("g-1", {"userId": "newcomer-1", "role": "User"}),
    "role": lambda env: env.change_role("g-1", "member-1", {"role": "Admin"}),
    "remove": lambda env: env.remove_member("g-1", "manager-1"),
    "leave": lambda env: env.remove_member("g-1", "member-1"),
    "approve": lambda env: env.approve("g-1", "applicant-1"),
    "reject": lambda env: env.reject("g-1", "applicant-1"),
    "transfer": lambda env: env.transfer("g-1", {"userId": "admin-1"}),
}
CALLERS = {"leave": "member-1"}


def prepare(env, write):
    seed(env, pending=("applicant-1",))
    env.add_directory_user("newcomer-1")
    env.as_user(CALLERS.get(write, "owner-1"))


@pytest.mark.parametrize("write", list(WRITES))
def test_a_concurrent_membership_change_is_kept(env, write):
    prepare(env, write)
    env.groups.before_replace.append(land(env, lambda record: record["users"].append(person("outsider-1"))))
    assert WRITES[write](env).status_code in (200, 201)
    assert person("outsider-1") in env.stored_group("g-1")["users"]
    assert [call[0] for call in env.write_calls()] == ["replace_item", "replace_item"]


@pytest.mark.parametrize("write", list(WRITES))
def test_a_group_deleted_mid_write_is_a_404_and_not_recreated(env, write):
    prepare(env, write)
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    assert_refused(WRITES[write](env), 404, "Group not found.", "group_not_found")
    assert env.stored_group("g-1") is None
    assert not [call for call in env.groups.calls if call[0] in ("create_item", "upsert_item")]
    assert env.bumps == [] and env.notifications == [] and env.activity_records() == []


@pytest.mark.parametrize("write", list(WRITES))
def test_a_group_that_keeps_changing_is_a_write_conflict(env, write):
    prepare(env, write)
    for _ in range(env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS):
        env.groups.before_replace.append(land(env, lambda record: record.update(description=record["description"] + ".")))
    assert_refused(
        WRITES[write](env), 409, "The group changed while this change was being saved. Try again.", "group_write_conflict",
    )
    assert env.bumps == [] and env.notifications == [] and env.activity_records() == []


@pytest.mark.parametrize("write", list(WRITES))
def test_a_missing_group_is_a_404(env, write):
    env.add_directory_user("newcomer-1")
    env.as_user(CALLERS.get(write, "owner-1"))
    assert_refused(WRITES[write](env), 404, "Group not found.", "group_not_found")
    assert env.write_calls() == []


# ---------------------------------------------------------------------------
# Session, configuration and identifier gates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_route_needs_a_signed_in_user(env, method, path, body):
    seed(env, pending=("applicant-1",))
    env.sign_out()
    assert env.call(method, path, body).status_code == 401
    assert env.write_calls() == []


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_route_needs_the_user_app_role(env, method, path, body):
    seed(env, pending=("applicant-1",))
    env.as_user("owner-1", roles=("CreateGroups",))
    assert env.call(method, path, body).status_code == 403
    assert env.write_calls() == []


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_route_is_off_without_group_workspaces(env, method, path, body):
    seed(env, pending=("applicant-1",))
    env.settings["enable_group_workspaces"] = False
    env.as_user("owner-1")
    response = env.call(method, path, body)
    assert (response.status_code, response.get_json()) == (400, {"error": "Enable Group Workspaces is disabled."})
    assert env.write_calls() == []


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_route_refuses_an_invalid_group_id(env, method, path, body):
    env.as_user("owner-1")
    response = env.call(method, path.replace("/g-1/", "/a,b/"), body)
    assert_refused(response, 400, "Invalid group identifier.", "invalid_request")


def test_member_routes_refuse_an_invalid_user_id(env):
    seed(env, pending=("applicant-1",))
    env.as_user("owner-1")
    for method, path, body in (
        ("PATCH", "/api/groups/g-1/membership/members/a,b", {"role": "Admin"}),
        ("DELETE", "/api/groups/g-1/membership/members/%2E%2E", None),
        ("POST", "/api/groups/g-1/membership/requests/%20x/approve", None),
        ("POST", "/api/groups/g-1/membership/requests/a,b/reject", None),
    ):
        assert_refused(env.call(method, path, body), 400, "Invalid user identifier.", "invalid_request")
    assert env.write_calls() == []


def test_an_unexpected_failure_is_a_logged_generic_500(env, monkeypatch):
    seed(env)

    def fail(*args, **kwargs):
        raise RuntimeError("AccountKey=secret-connection-detail")

    monkeypatch.setattr(env.groups, "read_item", fail)
    env.as_user("owner-1")
    response = env.members("g-1")
    assert_refused(
        response, 500, "The membership request could not be completed. Try again.", "group_membership_unavailable",
    )
    assert "secret-connection-detail" not in response.get_data(as_text=True)
    assert env.logs == [("[WORKSPACE_ROUTE] Group membership request failed.", 40, {"error_type": "RuntimeError"})]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
