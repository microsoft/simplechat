# test_group_directory_apis.py
"""
Functional test for the native group directory APIs.
Version: 0.261.147
Implemented in: 0.261.147

``GET``/``POST /api/groups/directory`` and ``POST``/``DELETE
/api/groups/<group_id>/join-request`` run for real (``functions_group``, the
directory modules and the classic ``route_backend_groups``, registered as
``app.py`` does) against the etag-enforcing groups container and its model of the
directory query (``test_support/group_directory_harness.py``).

It pins that:

- a directory row is exactly the reviewed projection: the owner's display name,
  never the owner's email or id, and no member's entry, for every caller;
- membership is decided by the classic role predicate, member wins over a stale
  pending entry, and ``hasLogo`` needs a stored logo and membership;
- ``view``, ``search``, ``page`` and ``page_size`` behave as documented, rows are
  ordered by casefolded name then id, and anything else is a data-free 400;
- create uses the policy as its only gate, validates ``{name, description?}``,
  answers with reviewed messages and never an exception's text, and has the classic
  create's audit trail exactly;
- join and cancel write through the etag guard: a concurrent change is kept, a
  deleted group is never recreated, the membership rules are re-checked on every
  attempt, every status accepts them, and neither notifies, logs or bumps a cache;
- a native request is read and approved by the classic manage-page routes.
"""

import copy
import json

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError

from test_support.group_directory_harness import (
    PEOPLE,
    group_directory_environment,
    group_document,
    person,
)


ROW_KEYS = {"id", "name", "description", "owner", "member_count", "heroColor", "hasLogo", "logoVersion", "membership"}
LOGO = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"


@pytest.fixture(scope="module")
def module_env():
    with group_directory_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def rows(response):
    assert response.status_code == 200, response.get_json()
    return response.get_json()["groups"]


def ids(response):
    return [row["id"] for row in rows(response)]


def assert_refused(response, status, message, error_code):
    assert response.status_code == status
    assert response.get_json() == {"error": message, "error_code": error_code}
    assert response.headers["Cache-Control"] == "no-store"


def assert_nothing_written(env):
    assert env.write_calls() == []
    assert env.notifications == [] and env.bumps == []


def land(env, group_id, change):
    """A concurrent writer that commits ``change`` between a guarded read and its replace."""
    def concurrent():
        record = env.stored_group(group_id)
        change(record)
        env.groups.seed(record)
    return concurrent


def response_text(response):
    return json.dumps(response.get_json(), sort_keys=True)


def assert_no_identities(response, *, owner_names=()):
    """No user id, no email and no member's name; only owners' display names appear."""
    text = response_text(response)
    for user_id, (name, email) in PEOPLE.items():
        assert user_id not in text
        assert email not in text
        if name not in owner_names:
            assert name not in text
    for fragment in ("sk-secret-endpoint-key", "pendingUsers", "users", "admins", "documentManagers",
                     "email", "model_endpoints", "retention_policy", "_etag"):
        assert fragment not in text


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caller", ["owner-1", "admin-1", "manager-1", "member-1", "applicant-1", "outsider-1"])
def test_every_caller_gets_only_the_directory_projection(env, caller):
    env.seed_group("g-1", "Shared", pending=("applicant-1",), logoBase64=LOGO, logoVersion=3)
    env.seed_group("g-2", "Other", owner="outsider-1", admins=(), managers=(), members=())
    env.as_user(caller)
    response = env.directory()
    assert response.headers["Cache-Control"] == "no-store"
    for row in rows(response):
        expected = ROW_KEYS | ({"userRole"} if row["membership"] == "member" else set())
        assert set(row) == expected
        assert set(row["owner"]) == {"displayName"}
    assert_no_identities(response, owner_names={"Olive Owner", "Oscar Outsider"})


def test_the_envelope_carries_the_page_the_total_and_the_hint(env):
    env.seed_group("g-1")
    payload = env.directory().get_json()
    assert set(payload) == {"groups", "page", "page_size", "total_count", "group_directory"}
    assert (payload["page"], payload["page_size"], payload["total_count"]) == (1, 20, 1)
    assert payload["group_directory"] == {"schema_version": 1, "can_create": True, "can_request_to_join": True}


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caller,membership,role", [
    ("owner-1", "member", "Owner"),
    ("admin-1", "member", "Admin"),
    ("manager-1", "member", "DocumentManager"),
    ("member-1", "member", "User"),
    ("applicant-1", "pending", None),
    ("outsider-1", "none", None),
])
def test_membership_and_role_for_every_caller(env, caller, membership, role):
    env.seed_group("g-1", pending=("applicant-1",))
    env.as_user(caller)
    [row] = rows(env.directory())
    assert row["membership"] == membership
    assert row.get("userRole") == role


def test_the_role_predicate_decides_membership_not_the_users_list(env):
    """An owner or admin missing from ``users[]`` is still a member, as the join route sees it."""
    document = group_document("g-1")
    document["users"] = [person("member-1")]
    env.seed_document(document)
    for caller, role in (("owner-1", "Owner"), ("admin-1", "Admin"), ("manager-1", "DocumentManager")):
        env.as_user(caller)
        [row] = rows(env.directory(query_string={"view": "mine"}))
        assert (row["membership"], row["userRole"]) == ("member", role)


def test_member_wins_over_a_stale_pending_entry(env):
    env.seed_group("g-1", pending=("member-1",))
    env.as_user("member-1")
    [row] = rows(env.directory())
    assert (row["membership"], row["userRole"]) == ("member", "User")
    assert ids(env.directory(query_string={"view": "mine"})) == ["g-1"]
    assert ids(env.directory(query_string={"view": "discover"})) == []


def test_malformed_membership_entries_do_not_break_the_listing(env):
    document = group_document("g-1")
    document["users"] = [{"email": "no-id@example.test"}, "member-1", person("member-1"), None]
    document["admins"] = [{"userId": "outsider-1"}, 7]
    document["pendingUsers"] = None
    env.seed_document(document)
    env.as_user("outsider-1")
    [row] = rows(env.directory())
    assert row["membership"] == "none" and row["member_count"] == 4
    env.as_user("member-1")
    [row] = rows(env.directory())
    assert (row["membership"], row["userRole"]) == ("member", "User")


# ---------------------------------------------------------------------------
# Views, search, paging and order
# ---------------------------------------------------------------------------

def seed_three_relationships(env):
    env.seed_group("g-member", "Member group")
    env.seed_group("g-pending", "Pending group", pending=("member-1",), members=())
    env.seed_group("g-none", "None group", members=())
    env.as_user("member-1")


@pytest.mark.parametrize("view,expected", [
    (None, ["g-member", "g-none", "g-pending"]),
    ("all", ["g-member", "g-none", "g-pending"]),
    ("mine", ["g-member"]),
    ("discover", ["g-none", "g-pending"]),
])
def test_views_split_the_callers_groups_from_the_rest(env, view, expected):
    seed_three_relationships(env)
    response = env.directory(query_string={"view": view} if view else None)
    assert ids(response) == expected
    assert response.get_json()["total_count"] == len(expected)


def test_search_matches_a_casefolded_name_or_description_substring(env):
    env.seed_group("g-1", "Straße Team")
    env.seed_group("g-2", "Finance", description="Quarterly BUDGET reviews")
    env.seed_group("g-3", "Unrelated")
    assert ids(env.directory(query_string={"search": "STRASSE"})) == ["g-1"]
    assert ids(env.directory(query_string={"search": "  budget  "})) == ["g-2"]
    assert ids(env.directory(query_string={"search": "team"})) == ["g-1"]
    missing = env.directory(query_string={"search": "nothing-matches"})
    assert rows(missing) == [] and missing.get_json()["total_count"] == 0


def test_search_matches_a_group_id_only_exactly(env):
    group_id = "5b0f3c1e-8d7a-4c1b-9f2e-0a1b2c3d4e5f"
    env.seed_group(group_id, "Research")
    assert ids(env.directory(query_string={"search": group_id.upper()})) == [group_id]
    assert ids(env.directory(query_string={"search": group_id[:8]})) == []


def test_a_blank_search_lists_everything(env):
    env.seed_group("g-1")
    env.seed_group("g-2")
    assert ids(env.directory(query_string={"search": "   "})) == ["g-1", "g-2"]


def test_search_is_limited_to_200_characters(env):
    env.seed_group("g-1")
    assert rows(env.directory(query_string={"search": "x" * 200})) == []
    assert_refused(
        env.directory(query_string={"search": "x" * 201}), 400,
        "Search terms can be at most 200 characters.", "invalid_request",
    )


def test_rows_are_ordered_by_casefolded_name_then_id(env):
    env.seed_group("g-1", "Beta")
    env.seed_group("g-3", "alpha")
    env.seed_group("g-2", "Alpha")
    env.seed_group("g-11", "")
    unnamed = group_document("g-10")
    del unnamed["name"]
    env.seed_document(unnamed)
    env.seed_group("g-4", "straße")
    env.seed_group("g-5", "STRASSE")
    assert ids(env.directory()) == ["g-10", "g-11", "g-2", "g-3", "g-1", "g-4", "g-5"]


def test_pages_are_cut_after_filtering_and_sorting(env):
    for number in range(25, 0, -1):
        env.seed_group(f"g-{number:02d}", f"Group {number:02d}", members=())
    env.seed_group("g-mine", "Group 00 mine")
    env.as_user("member-1")

    first = env.directory(query_string={"view": "all"})
    assert ids(first) == ["g-mine", *(f"g-{number:02d}" for number in range(1, 20))]
    assert first.get_json()["total_count"] == 26
    second = env.directory(query_string={"page": "2"})
    assert ids(second) == [f"g-{number:02d}" for number in range(20, 26)]
    beyond = env.directory(query_string={"page": "3"})
    assert rows(beyond) == [] and beyond.get_json()["total_count"] == 26
    small = env.directory(query_string={"page": "2", "page_size": "5"})
    assert ids(small) == [f"g-{number:02d}" for number in range(5, 10)]
    assert (small.get_json()["page"], small.get_json()["page_size"]) == (2, 5)
    assert len(rows(env.directory(query_string={"page_size": "100"}))) == 26
    mine = env.directory(query_string={"view": "mine", "page_size": "1"})
    assert ids(mine) == ["g-mine"] and mine.get_json()["total_count"] == 1
    discover = env.directory(query_string={"view": "discover", "page": "2", "page_size": "10"})
    assert ids(discover) == [f"g-{number:02d}" for number in range(11, 21)]
    assert discover.get_json()["total_count"] == 25


@pytest.mark.parametrize("query_string,message", [
    ("q=x", "Use only the search, view, page and page_size query parameters."),
    ("search=a&showAll=true", "Use only the search, view, page and page_size query parameters."),
    ("page=1&page=2", "Give each query parameter only once."),
    ("view=mine&view=all", "Give each query parameter only once."),
    ("view=everything", "The view must be all, mine or discover."),
    ("view=", "The view must be all, mine or discover."),
    ("view=Mine", "The view must be all, mine or discover."),
    ("page=0", "The page must be a whole number from 1 to 10000."),
    ("page=-1", "The page must be a whole number from 1 to 10000."),
    ("page=abc", "The page must be a whole number from 1 to 10000."),
    ("page=1.5", "The page must be a whole number from 1 to 10000."),
    ("page=%2B1", "The page must be a whole number from 1 to 10000."),
    ("page=", "The page must be a whole number from 1 to 10000."),
    ("page=%20" + "1", "The page must be a whole number from 1 to 10000."),
    ("page=10001", "The page must be a whole number from 1 to 10000."),
    ("page=%EF%BC%91", "The page must be a whole number from 1 to 10000."),
    ("page_size=0", "The page size must be a whole number from 1 to 100."),
    ("page_size=101", "The page size must be a whole number from 1 to 100."),
    ("page_size=ten", "The page size must be a whole number from 1 to 100."),
])
def test_unknown_repeated_or_malformed_parameters_are_refused(env, query_string, message):
    env.seed_group("g-1")
    response = env.call("GET", f"/api/groups/directory?{query_string}")
    assert_refused(response, 400, message, "invalid_request")
    assert env.groups.queries == []


def test_the_parameter_bounds_are_accepted(env):
    env.seed_group("g-1")
    for query_string in ({"page": "10000"}, {"page_size": "100"}, {"page_size": "1"}, {"page": "1", "view": "discover"}):
        assert env.directory(query_string=query_string).status_code == 200


def test_a_body_on_the_directory_read_is_refused(env):
    assert_refused(
        env.call("GET", "/api/groups/directory", {"view": "mine"}), 400,
        "This request does not accept a request body.", "invalid_request",
    )


# ---------------------------------------------------------------------------
# Row values
# ---------------------------------------------------------------------------

def test_has_logo_needs_a_stored_logo_and_membership(env):
    env.seed_group("g-logo", "Logo", logoBase64=LOGO, pending=("applicant-1",))
    env.seed_group("g-blank", "Blank", logoBase64="   ")
    env.seed_group("g-odd", "Odd", logoBase64=123)
    env.seed_group("g-none", "None")
    expected = {
        "member-1": {"g-logo": True, "g-blank": False, "g-odd": False, "g-none": False},
        "applicant-1": {"g-logo": False, "g-blank": False, "g-odd": False, "g-none": False},
        "outsider-1": {"g-logo": False, "g-blank": False, "g-odd": False, "g-none": False},
    }
    for caller, logos in expected.items():
        env.as_user(caller)
        assert {row["id"]: row["hasLogo"] for row in rows(env.directory())} == logos


def test_hero_colour_logo_version_and_member_count_are_normalized(env):
    env.seed_group("g-1", "A", heroColor="#ABCDEF", logoVersion=7)
    env.seed_group("g-2", "B", heroColor="red", logoVersion="4")
    env.seed_group("g-3", "C", heroColor=None, logoVersion=0)
    odd = group_document("g-4", "D", logoVersion="x")
    del odd["heroColor"]
    odd["users"] = "not-a-list"
    env.seed_document(odd)
    missing_users = group_document("g-5", "E")
    del missing_users["users"]
    env.seed_document(missing_users)
    listed = {row["id"]: row for row in rows(env.directory())}
    assert [(listed[key]["heroColor"], listed[key]["logoVersion"]) for key in ("g-1", "g-2", "g-3", "g-4")] == [
        ("#ABCDEF", 7), ("#0078d4", 4), ("#0078d4", 1), ("#0078d4", 1),
    ]
    assert [listed[key]["member_count"] for key in ("g-1", "g-4", "g-5")] == [4, 0, 0]


def test_untyped_and_group_typed_documents_are_listed_and_others_are_not(env):
    env.seed_group("g-untyped", "Untyped")
    env.seed_group("g-typed", "Typed", type="group")
    env.seed_group("g-null", "Null type", type=None)
    env.seed_group("g-other", "Other type", type="group_settings")
    assert ids(env.directory()) == ["g-typed", "g-untyped"]


def test_the_listing_sends_the_pinned_query_once_with_the_callers_id(env):
    env.seed_group("g-1")
    env.as_user("member-1")
    env.directory(query_string={"view": "mine", "search": "group", "page_size": "5"})
    assert [(query["parameters"], query["enable_cross_partition_query"]) for query in env.groups.queries] == [
        ([{"name": "@user_id", "value": "member-1"}], True),
    ]
    assert env.groups.queries[0]["query"] == env.modules.directory.GROUP_DIRECTORY_QUERY


def odd_documents():
    """Stored shapes the classic writers can leave behind, alongside a regular group."""
    regular = group_document("g-regular", "Regular", pending=("applicant-1",), logoBase64=LOGO)
    owner_outside_users = group_document("g-owner-outside", "Owner outside")
    owner_outside_users["users"] = [person("member-1")]
    malformed = group_document("g-malformed", 42, description=None, heroColor="blue", logoVersion="7")
    malformed["users"] = [{"email": "no-id@example.test"}, None, person("member-1"), {"userId": 5}]
    malformed["admins"] = [{"userId": "admin-1"}, "admin-1", 3]
    malformed["documentManagers"] = "manager-1"
    malformed["pendingUsers"] = [None, {"userId": "applicant-1"}, "applicant-1"]
    no_owner = group_document("g-no-owner", "No owner", logoBase64="  ")
    del no_owner["owner"]
    string_owner = group_document("g-string-owner", "String owner", logoVersion=None)
    string_owner["owner"] = "owner-1"
    no_arrays = {"id": "g-bare", "name": "Bare"}
    return [regular, owner_outside_users, malformed, no_owner, string_owner, no_arrays]


@pytest.mark.parametrize("caller", ["owner-1", "admin-1", "manager-1", "member-1", "applicant-1", "outsider-1"])
def test_write_responses_project_a_group_exactly_as_the_listing_does(env, caller):
    """Create, join and cancel build their row from the whole document; the listing
    builds it from the query's projection. The two must agree for every shape."""
    for document in odd_documents():
        env.seed_document(document)
    env.as_user(caller)
    listed = {row["id"]: row for row in rows(env.directory(query_string={"page_size": "100"}))}
    assert set(listed) == {document["id"] for document in odd_documents()}
    for document in odd_documents():
        stored = env.stored_group(document["id"])
        assert env.modules.directory.build_group_directory_row(stored, caller) == listed[document["id"]]


def test_an_unexpected_failure_is_a_logged_generic_500(env, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("AccountKey=secret-connection-detail")

    monkeypatch.setattr(env.groups, "query_items", fail)
    response = env.directory()
    assert_refused(
        response, 500, "The group directory request could not be completed. Try again.",
        "group_directory_unavailable",
    )
    assert "secret-connection-detail" not in response.get_data(as_text=True)
    assert env.logs == [("[WORKSPACE_ROUTE] Group directory request failed.", 40, {"error_type": "RuntimeError"})]


def test_an_oversized_body_keeps_its_status_with_a_data_free_message(env, monkeypatch):
    monkeypatch.setitem(env.app.config, "MAX_CONTENT_LENGTH", 64)
    response = env.create({"name": "n", "description": "d" * 200})
    assert_refused(response, 413, "The request could not be processed.", "invalid_request")
    assert_nothing_written(env)
    assert env.logs == []


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_returns_the_new_group_as_a_directory_row(env):
    env.as_user("outsider-1")
    response = env.create({"name": "  Launch team  ", "description": "  Plans and notes  "})
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    group = response.get_json()["group"]
    assert group == {
        "id": group["id"],
        "name": "Launch team",
        "description": "Plans and notes",
        "owner": {"displayName": "Oscar Outsider"},
        "member_count": 1,
        "heroColor": "#0078d4",
        "hasLogo": False,
        "logoVersion": 1,
        "membership": "member",
        "userRole": "Owner",
    }
    assert_no_identities(response, owner_names={"Oscar Outsider"})
    stored = env.stored_group(group["id"])
    assert stored["owner"] == {"id": "outsider-1", "email": "oscar.outsider@example.test", "displayName": "Oscar Outsider"}
    assert stored["users"] == [person("outsider-1")]
    assert (stored["admins"], stored["documentManagers"], stored["pendingUsers"]) == ([], [], [])
    assert ids(env.directory(query_string={"view": "mine"})) == [group["id"]]


def _audit(env):
    return {
        "notifications": copy.deepcopy(env.notifications),
        "bumps": list(env.bumps),
        "activity": list(env.activity.calls),
        "logs": list(env.logs),
        "user_settings_writes": list(env.user_settings_writes),
        "writes": [call[0] for call in env.write_calls()],
    }


def _normalized_audit(audit, group_id):
    return json.loads(json.dumps(audit).replace(group_id, "<group>"))


def test_create_has_the_classic_create_audit_trail_exactly(env):
    """Same notification, same cache bump, no activity record, no log, not made active."""
    env.as_user("outsider-1")
    classic = env.call("POST", "/api/groups", {"name": "Audit team", "description": "Parity"})
    assert classic.status_code == 201
    classic_audit = _normalized_audit(_audit(env), classic.get_json()["id"])
    classic_document = env.stored_group(classic.get_json()["id"])

    env.reset()
    env.as_user("outsider-1")
    native = env.create({"name": "Audit team", "description": "Parity"})
    assert native.status_code == 201
    native_id = native.get_json()["group"]["id"]
    assert _normalized_audit(_audit(env), native_id) == classic_audit
    assert classic_audit["notifications"][0]["notification_type"] == "group_created"
    assert classic_audit["bumps"] == ["group_created"]
    assert classic_audit["activity"] == [] and classic_audit["logs"] == []
    assert classic_audit["user_settings_writes"] == [] and classic_audit["writes"] == ["create_item"]

    native_document = env.stored_group(native_id)
    for document in (classic_document, native_document):
        for key in ("id", "createdDate", "modifiedDate", "_etag"):
            document.pop(key)
    assert native_document == classic_document


@pytest.mark.parametrize("settings,roles,status,message,error_code", [
    ({"enable_group_creation": False}, ("User",), 403, "Group creation is turned off.", "group_creation_disabled"),
    ({"require_member_of_create_group": True}, ("User",), 403,
     "You need the CreateGroups role to create groups.", "create_groups_role_required"),
    ({"require_member_of_create_group": True}, ("Admin",), 403,
     "You need the CreateGroups role to create groups.", "create_groups_role_required"),
    ({"enable_group_creation": False, "require_member_of_create_group": True}, ("User",), 403,
     "Group creation is turned off.", "group_creation_disabled"),
])
def test_create_gates_answer_with_reviewed_messages(env, settings, roles, status, message, error_code):
    env.settings.update(settings)
    env.as_user("outsider-1", roles=roles)
    assert_refused(env.create({"name": "Refused"}), status, message, error_code)
    assert_nothing_written(env)


def test_the_create_groups_role_opens_narrowed_creation(env):
    env.settings["require_member_of_create_group"] = True
    env.as_user("outsider-1", roles=("User", "CreateGroups"))
    assert env.create({"name": "Allowed"}).status_code == 201


def test_a_refused_creator_is_refused_before_the_body_is_read(env):
    env.settings["enable_group_creation"] = False
    response = env.call("POST", "/api/groups/directory", raw="{not json", content_type="application/json")
    assert_refused(response, 403, "Group creation is turned off.", "group_creation_disabled")


@pytest.mark.parametrize("request_kwargs,message", [
    ({"raw": "{not json"}, "Provide valid JSON with no duplicate fields."),
    ({"raw": '{"name": "a", "name": "b"}'}, "Duplicate fields are not supported."),
    ({"raw": "name=a", "content_type": "application/x-www-form-urlencoded"}, "A JSON object is required for this request."),
    ({}, "A JSON object is required for this request."),
    ({"body": ["name"]}, "A JSON object is required for this request."),
    ({"body": {"name": "a", "heroColor": "#000000"}}, "Only a name and a description can be set when creating a group."),
    ({"body": {"name": "a", "owner": {"id": "someone-else"}}}, "Only a name and a description can be set when creating a group."),
    ({"body": {}}, "Enter a group name."),
    ({"body": {"name": None}}, "Enter a group name."),
    ({"body": {"name": "   "}}, "Enter a group name."),
    ({"body": {"name": 5}}, "The group name must be text."),
    ({"body": {"name": ["a"]}}, "The group name must be text."),
    ({"body": {"name": "x" * 81}}, "Group names can be at most 80 characters."),
    ({"body": {"name": "a\x00b"}}, "Group names cannot contain control characters."),
    ({"body": {"name": "a\nb"}}, "Group names cannot contain control characters."),
    ({"body": {"name": "a\tb"}}, "Group names cannot contain control characters."),
    ({"body": {"name": "a\x7fb"}}, "Group names cannot contain control characters."),
    ({"body": {"name": "a\x85b"}}, "Group names cannot contain control characters."),
    ({"body": {"name": "a", "description": None}}, "The group description must be text."),
    ({"body": {"name": "a", "description": 3}}, "The group description must be text."),
    ({"body": {"name": "a", "description": "d" * 501}}, "Group descriptions can be at most 500 characters."),
])
def test_create_validates_the_body_with_reviewed_messages(env, request_kwargs, message):
    response = env.call("POST", "/api/groups/directory", **request_kwargs)
    assert_refused(response, 400, message, "invalid_request")
    assert_nothing_written(env)


def test_create_limits_apply_after_stripping(env):
    response = env.create({"name": f"  {'n' * 80}  ", "description": f"\n{'d' * 500}\n"})
    assert response.status_code == 201
    stored = env.stored_group(response.get_json()["group"]["id"])
    assert (len(stored["name"]), len(stored["description"])) == (80, 500)


def test_create_refuses_query_parameters(env):
    response = env.call("POST", "/api/groups/directory", {"name": "a"}, query_string={"view": "mine"})
    assert_refused(response, 400, "This request does not accept query parameters.", "invalid_request")
    assert_nothing_written(env)


def test_a_storage_failure_is_a_generic_500_without_the_exception_text(env, monkeypatch):
    def fail(body, **kwargs):
        raise CosmosHttpResponseError(status_code=503, message="AccountKey=secret-storage-detail")

    monkeypatch.setattr(env.groups, "create_item", fail)
    response = env.create({"name": "Doomed"})
    assert_refused(response, 500, "The group could not be created. Try again.", "group_create_failed")
    assert "secret-storage-detail" not in response.get_data(as_text=True)
    assert env.logs == [
        ("[WORKSPACE_ROUTE] Group directory create failed.", 40, {"error_type": "CosmosHttpResponseError"}),
    ]
    assert env.notifications == [] and env.bumps == []


def test_a_refusal_from_the_create_helper_is_a_generic_403(env):
    """The helper re-reads the settings; if creation was switched off in between, it refuses."""
    env.operations_namespace["get_settings"] = lambda: {**env.settings, "enable_group_creation": False}
    response = env.create({"name": "Raced"})
    assert_refused(response, 403, "Group creation isn't available right now.", "group_creation_unavailable")
    assert_nothing_written(env)


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------

def test_join_adds_the_classic_pending_entry_and_nothing_else(env):
    env.seed_group("g-1", pending=("outsider-1",))
    before = env.stored_group("g-1")
    env.as_user("applicant-1")
    response = env.join("g-1")
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["group"]["membership"] == "pending"
    assert "userRole" not in response.get_json()["group"]
    assert_no_identities(response, owner_names={"Olive Owner"})

    after = env.stored_group("g-1")
    assert after["pendingUsers"] == [person("outsider-1"), person("applicant-1")]
    assert after["modifiedDate"] != before["modifiedDate"]
    for document in (before, after):
        for key in ("pendingUsers", "modifiedDate", "_etag"):
            document.pop(key)
    assert after == before
    assert [call[0] for call in env.write_calls()] == ["replace_item"]


@pytest.mark.parametrize("caller", ["owner-1", "admin-1", "manager-1", "member-1"])
def test_a_member_cannot_ask_to_join(env, caller):
    env.seed_group("g-1")
    env.as_user(caller)
    assert_refused(env.join("g-1"), 409, "You're already a member of this group.", "already_member")
    assert_nothing_written(env)


def test_asking_twice_is_refused(env):
    env.seed_group("g-1", pending=("applicant-1",))
    env.as_user("applicant-1")
    assert_refused(env.join("g-1"), 409, "You've already asked to join this group.", "request_pending")
    assert_nothing_written(env)


@pytest.mark.parametrize("pending", ["missing", None])
def test_join_creates_a_missing_pending_list(env, pending):
    document = group_document("g-1")
    if pending == "missing":
        del document["pendingUsers"]
    else:
        document["pendingUsers"] = None
    env.seed_document(document)
    env.as_user("applicant-1")
    assert env.join("g-1").status_code == 201
    assert env.stored_group("g-1")["pendingUsers"] == [person("applicant-1")]


def test_joining_a_missing_group_is_404_and_writes_nothing(env):
    env.as_user("applicant-1")
    assert_refused(env.join("g-missing"), 404, "Group not found.", "group_not_found")
    assert env.write_calls() == []


def test_a_group_deleted_mid_join_is_not_recreated(env):
    env.seed_group("g-1")
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    env.as_user("applicant-1")
    assert_refused(env.join("g-1"), 404, "Group not found.", "group_not_found")
    assert env.stored_group("g-1") is None
    assert [call[0] for call in env.write_calls()] == ["replace_item"]


def test_a_membership_change_landing_mid_join_is_kept(env):
    env.seed_group("g-1")
    env.groups.before_replace.append(land(env, "g-1", lambda record: record["users"].append(person("outsider-1"))))
    env.as_user("applicant-1")
    assert env.join("g-1").status_code == 201
    stored = env.stored_group("g-1")
    assert person("outsider-1") in stored["users"]
    assert stored["pendingUsers"] == [person("applicant-1")]
    assert [call[0] for call in env.write_calls()] == ["replace_item", "replace_item"]


def test_an_approval_landing_mid_join_is_refused_on_the_retry(env):
    env.seed_group("g-1")
    env.groups.before_replace.append(land(env, "g-1", lambda record: record["users"].append(person("applicant-1"))))
    env.as_user("applicant-1")
    assert_refused(env.join("g-1"), 409, "You're already a member of this group.", "already_member")
    assert env.stored_group("g-1")["pendingUsers"] == []


def test_a_duplicate_request_landing_mid_join_is_refused_on_the_retry(env):
    env.seed_group("g-1")
    env.groups.before_replace.append(land(env, "g-1", lambda record: record["pendingUsers"].append(person("applicant-1"))))
    env.as_user("applicant-1")
    assert_refused(env.join("g-1"), 409, "You've already asked to join this group.", "request_pending")
    assert env.stored_group("g-1")["pendingUsers"] == [person("applicant-1")]


def test_a_group_that_keeps_changing_is_a_write_conflict(env):
    env.seed_group("g-1")
    attempts = env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS
    for number in range(attempts):
        env.groups.before_replace.append(
            land(env, "g-1", lambda record, number=number: record["users"].append(person("outsider-1")))
        )
    env.as_user("applicant-1")
    assert_refused(
        env.join("g-1"), 409, "The group changed while your request was being saved. Try again.",
        "group_write_conflict",
    )
    assert env.stored_group("g-1")["pendingUsers"] == []


def test_join_refuses_a_non_group_document(env):
    env.seed_group("g-1", type="group_settings")
    env.as_user("applicant-1")
    assert_refused(env.join("g-1"), 404, "Group not found.", "group_not_found")
    assert env.write_calls() == []


@pytest.mark.parametrize("status", ["active", "locked", "upload_disabled", "inactive", None, "archived"])
def test_every_group_status_accepts_a_request_and_its_cancellation(env, status):
    """Decision §2.4: today's classic behaviour, preserved. Inactive groups accept requests."""
    extra = {} if status is None else {"status": status}
    env.seed_group("g-1", **extra)
    env.as_user("applicant-1")
    assert env.join("g-1").status_code == 201
    assert env.cancel("g-1").status_code == 200
    assert env.stored_group("g-1").get("status") == status


def test_join_and_cancel_do_not_notify_log_or_bump(env):
    env.seed_group("g-1")
    env.as_user("applicant-1")
    env.join("g-1")
    env.cancel("g-1")
    assert (env.notifications, env.bumps, env.activity.calls, env.logs) == ([], [], [], [])


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_join_and_cancel_take_no_body_or_query(env, method):
    env.seed_group("g-1", pending=("applicant-1",))
    env.as_user("applicant-1")
    assert_refused(
        env.call(method, "/api/groups/g-1/join-request", {}), 400,
        "This request does not accept a request body.", "invalid_request",
    )
    assert_refused(
        env.call(method, "/api/groups/g-1/join-request", query_string={"userId": "outsider-1"}), 400,
        "This request does not accept query parameters.", "invalid_request",
    )
    assert env.write_calls() == []


@pytest.mark.parametrize("method", ["POST", "DELETE"])
@pytest.mark.parametrize("encoded_id", ["a,b", "%20padded", "%2E%2E", "%00", "x" * 513])
def test_join_and_cancel_refuse_an_invalid_group_id(env, method, encoded_id):
    env.as_user("applicant-1")
    assert_refused(
        env.call(method, f"/api/groups/{encoded_id}/join-request"), 400,
        "Invalid group identifier.", "invalid_request",
    )
    assert env.groups.calls == []


def test_the_classic_manage_page_reads_and_approves_a_native_request(env):
    env.seed_group("g-1")
    env.as_user("applicant-1")
    assert env.join("g-1").status_code == 201

    env.as_user("owner-1")
    pending = env.call("GET", "/api/groups/g-1/requests")
    assert pending.status_code == 200 and pending.get_json() == [person("applicant-1")]
    approved = env.call("PATCH", "/api/groups/g-1/requests/applicant-1", {"action": "approve"})
    assert approved.status_code == 200

    env.as_user("applicant-1")
    [row] = rows(env.directory())
    assert (row["membership"], row["userRole"]) == ("member", "User")


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def test_cancel_removes_only_the_callers_request(env):
    env.seed_group("g-1", pending=("applicant-1", "outsider-1"))
    env.as_user("applicant-1")
    response = env.cancel("g-1")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["group"]["membership"] == "none"
    assert_no_identities(response, owner_names={"Olive Owner"})
    assert env.stored_group("g-1")["pendingUsers"] == [person("outsider-1")]


@pytest.mark.parametrize("pending", [(), ("outsider-1",), "missing"])
def test_cancel_without_a_request_is_refused(env, pending):
    document = group_document("g-1", pending=() if pending == "missing" else pending)
    if pending == "missing":
        del document["pendingUsers"]
    env.seed_document(document)
    env.as_user("applicant-1")
    assert_refused(
        env.cancel("g-1"), 409, "You don't have a pending request to join this group.", "no_pending_request",
    )
    assert env.write_calls() == []


def test_cancel_removes_every_entry_for_the_caller(env):
    document = group_document("g-1", pending=("applicant-1", "outsider-1", "applicant-1"))
    env.seed_document(document)
    env.as_user("applicant-1")
    assert env.cancel("g-1").status_code == 200
    assert env.stored_group("g-1")["pendingUsers"] == [person("outsider-1")]


def test_cancel_clears_a_stale_entry_left_for_a_member(env):
    env.seed_group("g-1", pending=("member-1",))
    env.as_user("member-1")
    response = env.cancel("g-1")
    assert response.status_code == 200
    assert (response.get_json()["group"]["membership"], response.get_json()["group"]["userRole"]) == ("member", "User")
    assert env.stored_group("g-1")["pendingUsers"] == []


def test_cancelling_on_a_missing_or_deleted_group_is_404(env):
    env.as_user("applicant-1")
    assert_refused(env.cancel("g-missing"), 404, "Group not found.", "group_not_found")
    env.seed_group("g-1", pending=("applicant-1",))
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    assert_refused(env.cancel("g-1"), 404, "Group not found.", "group_not_found")
    assert env.stored_group("g-1") is None
    assert not [call for call in env.groups.calls if call[0] in ("create_item", "upsert_item")]


def test_a_change_landing_mid_cancel_is_kept(env):
    env.seed_group("g-1", pending=("applicant-1",))
    env.groups.before_replace.append(land(env, "g-1", lambda record: record["pendingUsers"].append(person("outsider-1"))))
    env.as_user("applicant-1")
    assert env.cancel("g-1").status_code == 200
    assert env.stored_group("g-1")["pendingUsers"] == [person("outsider-1")]


def test_a_cancel_landing_mid_cancel_is_refused_on_the_retry(env):
    env.seed_group("g-1", pending=("applicant-1",))
    env.groups.before_replace.append(land(env, "g-1", lambda record: record["pendingUsers"].clear()))
    env.as_user("applicant-1")
    assert_refused(
        env.cancel("g-1"), 409, "You don't have a pending request to join this group.", "no_pending_request",
    )


# ---------------------------------------------------------------------------
# Session and configuration gates
# ---------------------------------------------------------------------------

ROUTE_CALLS = [
    ("GET", "/api/groups/directory", None),
    ("POST", "/api/groups/directory", {"name": "x"}),
    ("POST", "/api/groups/g-1/join-request", None),
    ("DELETE", "/api/groups/g-1/join-request", None),
]


@pytest.mark.parametrize("method,path,body", ROUTE_CALLS)
def test_every_route_needs_a_signed_in_user(env, method, path, body):
    env.seed_group("g-1", pending=("applicant-1",))
    env.sign_out()
    response = env.call(method, path, body)
    assert response.status_code == 401
    assert env.write_calls() == [] and env.groups.queries == []


@pytest.mark.parametrize("method,path,body", ROUTE_CALLS)
def test_every_route_needs_the_user_app_role(env, method, path, body):
    env.seed_group("g-1", pending=("applicant-1",))
    env.as_user("applicant-1", roles=("CreateGroups",))
    response = env.call(method, path, body)
    assert response.status_code == 403
    assert env.write_calls() == [] and env.groups.queries == []


@pytest.mark.parametrize("method,path,body", ROUTE_CALLS)
def test_every_route_is_off_without_group_workspaces(env, method, path, body):
    env.seed_group("g-1", pending=("applicant-1",))
    env.settings["enable_group_workspaces"] = False
    env.as_user("applicant-1")
    response = env.call(method, path, body)
    assert response.status_code == 400
    assert response.get_json() == {"error": "Enable Group Workspaces is disabled."}
    assert env.write_calls() == [] and env.groups.queries == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
