# test_group_membership_fixture_parity.py
"""
Per-route shape parity between the M7B group membership UI fixture and the real routes.
Version: 0.261.155
Implemented in: 0.261.155

The V2 Members browser suite mocks the network with the closed HTTP fixture
`ui_tests/fixtures/group_members.py`. A fixture whose answers drift from the server would let a
passing browser test hide a real regression, so this test holds the fixture to the real native
membership routes, driven by the isolated backend harness the membership functional tests use
(`test_support/group_directory_harness.py`, running the real membership, policy, directory, group
and settings modules against an etag-enforcing fake Cosmos), and to the real `/api/userSearch`
route function.

For every route the Members section calls it asserts that the fixture never invents a top-level or
row key the server does not return, that the keys the page reads are present in both, and that the
status, the machine-readable `error_code` and, for every refusal, the reviewed message match. It
covers every outcome the page handles (contract section 9.3): the list and its hint, the request
list, add with each directory outcome and every refusal, role change with its no-op and the owner
refusal, remove and leave with the owner refusals, approve with `already_member` and
`no_pending_request`, reject, transfer with its no-op and `owner_only`, `group_write_conflict`,
`group_not_found`, `not_a_member` and `membership_permission`. It also pins that every membership
response is `no-store` in both, that the fixture's policy is the real policy module, and that its
people search answers in the real route's shape.

The fixture handlers are the production browser-test code, exercised through the same `_dispatch`
entry the Playwright route handler calls, with a tiny fake page and route.
"""

import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN, OWNER_ID  # noqa: E402
from ui_tests.fixtures import group_members as fixture_module  # noqa: E402
from ui_tests.fixtures.group_members import (  # noqa: E402
    DMITRI, GroupMembersFixture, LEE, MAYA, NIA, NORA, OLIVIA, OMAR, PRIYA,
)

from test_support.group_directory_harness import group_directory_environment  # noqa: E402
from test_user_search_hardening import Environment as UserSearchEnvironment, graph_response  # noqa: E402


FIXTURE_GROUP = "group-a"
REAL_GROUP = "g-1"
LIST_KEYS = {"members", "page", "page_size", "total_count", "membership_management"}
ROW_KEYS = {"userId", "displayName", "email", "role", "member_actions"}
HINT_KEYS = {"schema_version", "operations"}
REQUEST_LIST_KEYS = {"requests", "total_count"}
REQUEST_ROW_KEYS = {"userId", "displayName", "email"}
ERROR_KEYS = {"error", "error_code"}
# The harness user who holds each role in the seeded group.
REAL_ROLE_USERS = {"Owner": "owner-1", "Admin": "admin-1", "DocumentManager": "manager-1", "User": "member-1"}


# --------------------------------------------------------------------------
# Fixture driving: a fake page and route that only capture the fulfilled response.
# --------------------------------------------------------------------------

class _FakeContext:
    def route(self, *args, **kwargs):
        pass

    def on(self, *args, **kwargs):
        pass


class _FakePage:
    def __init__(self):
        self.context = _FakeContext()
        self.url = "about:blank"

    def on(self, *args, **kwargs):
        pass


class _FakeRequest:
    def __init__(self, url):
        self.url = url


class _FakeRoute:
    def __init__(self, url):
        self.request = _FakeRequest(url)
        self.status = 200
        self.payload = None
        self.headers = {}

    def fulfill(self, status=200, json=None, **kwargs):
        self.status = status
        self.payload = json
        self.headers = kwargs.get("headers") or {}


class Answer:
    def __init__(self, status, payload, headers):
        self.status = status
        self.payload = payload
        self.headers = headers


def drive(fixture, method, path, body=None, query=None):
    """Dispatch one request through the fixture exactly as its Playwright route handler would."""
    entry = ApiRequest(method=method, path=path, query=query or {}, body=body)
    route = _FakeRoute(f"{ORIGIN}{path}")
    fixture._dispatch(route, entry)
    return Answer(route.status, route.payload, route.headers)


def real(response):
    return Answer(response.status_code, response.get_json(), dict(response.headers))


def new_fixture():
    return GroupMembersFixture(_FakePage())


def base(group_id):
    return f"/api/groups/{group_id}/membership"


# --------------------------------------------------------------------------
# Real routes: the isolated backend harness.
# --------------------------------------------------------------------------

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
    extra.setdefault("pending", ("applicant-1",))
    return env.seed_group(REAL_GROUP, "Team", **extra)


def keep_changing(env):
    """Concurrent writes that land before every replace, so the guard gives up with its 409."""
    def concurrent():
        env.seed_document(env.stored_group(REAL_GROUP))
    env.groups.before_replace.extend(concurrent for _ in range(env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS))


# --------------------------------------------------------------------------
# Parity assertions.
# --------------------------------------------------------------------------

def assert_no_invented_keys(scenario, fixture_payload, real_payload):
    invented = set(fixture_payload) - set(real_payload)
    assert not invented, (
        f"{scenario}: the fixture returns keys the server never does: {sorted(invented)} "
        f"(server keys {sorted(real_payload)})"
    )


def assert_shared_keys(scenario, fixture_payload, real_payload, required):
    for key in required:
        assert key in real_payload, f"{scenario}: the server no longer returns {key!r}; the harness or contract drifted"
        assert key in fixture_payload, f"{scenario}: the fixture dropped {key!r}, which the page reads"


def assert_same_shape(scenario, fixture_answer, real_answer, required):
    assert fixture_answer.status == real_answer.status, (
        f"{scenario}: status {fixture_answer.status} from the fixture, {real_answer.status} from the server"
    )
    assert_no_invented_keys(scenario, fixture_answer.payload, real_answer.payload)
    assert_shared_keys(scenario, fixture_answer.payload, real_answer.payload, required)


def assert_same_row(scenario, fixture_row, real_row):
    assert_no_invented_keys(scenario, fixture_row, real_row)
    assert_shared_keys(scenario, fixture_row, real_row, ROW_KEYS)


def assert_same_refusal(scenario, fixture_answer, real_answer, status, code):
    assert (fixture_answer.status, real_answer.status) == (status, status), (
        f"{scenario}: statuses {fixture_answer.status} (fixture) and {real_answer.status} (server), expected {status}"
    )
    assert_no_invented_keys(scenario, fixture_answer.payload, real_answer.payload)
    assert_shared_keys(scenario, fixture_answer.payload, real_answer.payload, ERROR_KEYS)
    assert fixture_answer.payload["error_code"] == real_answer.payload["error_code"] == code, scenario
    # The page renders the server's reviewed text, so the fixture's copy must be the server's.
    assert fixture_answer.payload["error"] == real_answer.payload["error"], scenario


def assert_no_store(scenario, fixture_answer, real_answer):
    assert real_answer.headers.get("Cache-Control") == "no-store", f"{scenario}: the server no longer sets no-store"
    assert fixture_answer.headers.get("Cache-Control") == "no-store", f"{scenario}: the fixture dropped no-store"


# --------------------------------------------------------------------------
# The policy and the messages are the server's.
# --------------------------------------------------------------------------

def test_the_fixture_policy_is_the_real_policy_module(env):
    policy = fixture_module.POLICY
    real_policy = env.modules.membership_policy
    assert Path(policy.__file__).resolve() == (ROOT / "application" / "single_app" / "functions_group_membership_policy.py").resolve()
    roles = (*real_policy.GROUP_MEMBER_ROLES, None, "Superuser")
    for caller in roles:
        for target in roles:
            for is_self in (True, False):
                assert policy.group_member_actions(caller, target, is_self=is_self) == \
                    real_policy.group_member_actions(caller, target, is_self=is_self)
        for status in ("active", "upload_disabled", "locked", "inactive", None, "archived"):
            group = {"status": status}
            assert policy.group_membership_operations(caller, group, {"enable_group_workspaces": True}) == \
                real_policy.group_membership_operations(caller, group, {"enable_group_workspaces": True})


@pytest.mark.parametrize("name", [
    "GROUP_NOT_FOUND_MESSAGE", "NOT_A_MEMBER_MESSAGE", "MEMBERSHIP_PERMISSION_MESSAGE", "OWNER_ONLY_MESSAGE",
    "STATUS_UNAVAILABLE_MESSAGE", "MEMBER_NOT_FOUND_MESSAGE", "ALREADY_MEMBER_MESSAGE", "NO_PENDING_REQUEST_MESSAGE",
    "OWNER_ROLE_MESSAGE", "OWNER_REMOVAL_MESSAGE", "OWNER_LEAVE_MESSAGE", "WRITE_CONFLICT_MESSAGE",
    "USER_NOT_FOUND_MESSAGE",
])
def test_the_fixture_messages_are_the_server_messages(env, name):
    assert getattr(fixture_module, name) == getattr(env.modules.membership, name)


# --------------------------------------------------------------------------
# Reads.
# --------------------------------------------------------------------------

def action_map(rows, caller_id):
    return {(row["role"], row["userId"] == caller_id): tuple(row["member_actions"]) for row in rows}


@pytest.mark.parametrize("role", ["Owner", "Admin", "DocumentManager", "User"])
@pytest.mark.parametrize("status", ["active", "locked"])
def test_member_list_shape_and_hints_match(env, role, status):
    seed(env, status=status)
    env.as_user(REAL_ROLE_USERS[role])
    real_answer = real(env.members(REAL_GROUP))

    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_GROUP, role, status=status)
    fixture_answer = drive(fixture, "GET", f"{base(FIXTURE_GROUP)}/members")

    assert_same_shape("list", fixture_answer, real_answer, LIST_KEYS)
    assert_shared_keys("list-hint", fixture_answer.payload["membership_management"],
                       real_answer.payload["membership_management"], HINT_KEYS)
    assert fixture_answer.payload["membership_management"] == real_answer.payload["membership_management"]
    for fixture_row, real_row in zip(fixture_answer.payload["members"], real_answer.payload["members"]):
        assert_same_row("list-row", fixture_row, real_row)
    real_actions = action_map(real_answer.payload["members"], REAL_ROLE_USERS[role])
    fixture_actions = action_map(fixture_answer.payload["members"], OWNER_ID)
    shared = set(real_actions) & set(fixture_actions)
    assert shared, "The two lists share no role and self combination to compare."
    assert {key: fixture_actions[key] for key in shared} == {key: real_actions[key] for key in shared}
    assert_no_store("list", fixture_answer, real_answer)


def test_member_list_query_shape_matches(env):
    seed(env)
    env.as_user("owner-1")
    real_answer = real(env.members(REAL_GROUP, query_string={"search": "a", "role": "User", "page": "1", "page_size": "2"}))

    fixture = new_fixture()
    fixture_answer = drive(fixture, "GET", f"{base(FIXTURE_GROUP)}/members",
                           query={"search": ["a"], "role": ["User"], "page": ["1"], "page_size": ["2"]})

    assert_same_shape("list-query", fixture_answer, real_answer, LIST_KEYS)
    assert (fixture_answer.payload["page"], fixture_answer.payload["page_size"]) == (1, 2)
    assert (real_answer.payload["page"], real_answer.payload["page_size"]) == (1, 2)
    assert all(row["role"] == "User" for row in fixture_answer.payload["members"])
    assert all(row["role"] == "User" for row in real_answer.payload["members"])


@pytest.mark.parametrize("query", [
    {"bogus": "x"}, {"role": "Superuser"}, {"page": "0"}, {"page_size": "101"}, {"search": "x" * 201},
])
def test_member_list_strict_query_refusals_match(env, query):
    seed(env)
    env.as_user("owner-1")
    real_answer = real(env.members(REAL_GROUP, query_string=query))

    fixture = new_fixture()
    fixture_answer = drive(fixture, "GET", f"{base(FIXTURE_GROUP)}/members",
                           query={key: [value] for key, value in query.items()})

    assert_same_refusal(f"list-400 {query}", fixture_answer, real_answer, 400, "invalid_request")
    assert_no_store("list-400", fixture_answer, real_answer)


def test_member_list_refusals_match(env):
    seed(env)
    env.as_user("outsider-1")
    real_answer = real(env.members(REAL_GROUP))
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_GROUP, "User")
    fixture.remove_person(FIXTURE_GROUP, OWNER_ID)
    assert_same_refusal("list-not-a-member", drive(fixture, "GET", f"{base(FIXTURE_GROUP)}/members"), real_answer,
                        403, "not_a_member")

    env.as_user("owner-1")
    real_missing = real(env.members("g-missing"))
    fixture_missing = drive(new_fixture(), "GET", f"{base('group-missing')}/members")
    assert_same_refusal("list-group-not-found", fixture_missing, real_missing, 404, "group_not_found")


def test_request_list_shape_matches(env):
    seed(env, pending=("applicant-1", "outsider-1"))
    env.as_user("owner-1")
    real_answer = real(env.pending_requests(REAL_GROUP))

    fixture = new_fixture()
    fixture_answer = drive(fixture, "GET", f"{base(FIXTURE_GROUP)}/requests")

    assert_same_shape("requests", fixture_answer, real_answer, REQUEST_LIST_KEYS)
    for fixture_row, real_row in zip(fixture_answer.payload["requests"], real_answer.payload["requests"]):
        assert_no_invented_keys("request-row", fixture_row, real_row)
        assert_shared_keys("request-row", fixture_row, real_row, REQUEST_ROW_KEYS)
    assert_no_store("requests", fixture_answer, real_answer)


def test_request_list_refusal_matches(env):
    seed(env)
    env.as_user("manager-1")
    real_answer = real(env.pending_requests(REAL_GROUP))
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_GROUP, "DocumentManager")
    fixture_answer = drive(fixture, "GET", f"{base(FIXTURE_GROUP)}/requests")
    assert_same_refusal("requests-permission", fixture_answer, real_answer, 403, "membership_permission")


# --------------------------------------------------------------------------
# Add.
# --------------------------------------------------------------------------

def add_body(user_id, role="User", name="", email=""):
    return {"userId": user_id, "displayName": name, "email": email, "role": role}


def test_add_success_shape_matches(env):
    seed(env)
    env.add_directory_user("newcomer-1")
    env.as_user("owner-1")
    real_answer = real(env.add_member(REAL_GROUP, add_body("newcomer-1", "Admin")))

    fixture = new_fixture()
    fixture_answer = drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/members", body=add_body(NORA["userId"], "Admin"))

    assert_same_shape("add", fixture_answer, real_answer, {"member"})
    assert (fixture_answer.status, real_answer.status) == (201, 201)
    assert_same_row("add-row", fixture_answer.payload["member"], real_answer.payload["member"])
    assert fixture_answer.payload["member"]["role"] == real_answer.payload["member"]["role"] == "Admin"
    assert_no_store("add", fixture_answer, real_answer)


def test_add_with_the_directory_unavailable_uses_the_submitted_details_in_both(env):
    seed(env)
    env.directory_failure = RuntimeError("no delegated token")
    env.as_user("owner-1")
    real_answer = real(env.add_member(REAL_GROUP, add_body("newcomer-1", name="Typed Name", email="typed@example.test")))

    fixture = new_fixture()
    fixture.directory_available = False
    fixture_answer = drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/members",
                           body=add_body(NORA["userId"], name="Typed Name", email="typed@example.test"))

    assert_same_shape("add-fallback", fixture_answer, real_answer, {"member"})
    for answer in (fixture_answer, real_answer):
        assert (answer.payload["member"]["displayName"], answer.payload["member"]["email"]) == ("Typed Name", "typed@example.test")


def test_add_refusals_match(env):
    cases = []

    # A definitive directory not-found.
    seed(env)
    env.as_user("owner-1")
    cases.append(("user_not_found", real(env.add_member(REAL_GROUP, add_body("ghost-1"))),
                  lambda fixture: drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/members", body=add_body(NIA["userId"])),
                  None, 400))

    # Someone who is already a member.
    env.reset()
    seed(env)
    env.add_directory_user("member-1")
    env.as_user("owner-1")
    cases.append(("already_member", real(env.add_member(REAL_GROUP, add_body("member-1"))),
                  lambda fixture: drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/members", body=add_body(MAYA["userId"])),
                  None, 409))

    # A group whose status can't take members.
    env.reset()
    seed(env, status="locked")
    env.add_directory_user("newcomer-1")
    env.as_user("owner-1")
    cases.append(("group_status_unavailable", real(env.add_member(REAL_GROUP, add_body("newcomer-1"))),
                  lambda fixture: drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/members", body=add_body(NORA["userId"])),
                  lambda fixture: fixture.set_status(FIXTURE_GROUP, "locked"), 403))

    # A member who doesn't manage membership, and a caller who isn't a member.
    env.reset()
    seed(env)
    env.add_directory_user("newcomer-1")
    env.as_user("manager-1")
    cases.append(("membership_permission", real(env.add_member(REAL_GROUP, add_body("newcomer-1"))),
                  lambda fixture: drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/members", body=add_body(NORA["userId"])),
                  lambda fixture: fixture.set_viewer_role(FIXTURE_GROUP, "DocumentManager"), 403))
    env.as_user("outsider-1")
    cases.append(("not_a_member", real(env.add_member(REAL_GROUP, add_body("newcomer-1"))),
                  lambda fixture: drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/members", body=add_body(NORA["userId"])),
                  lambda fixture: (fixture.set_viewer_role(FIXTURE_GROUP, "User"),
                                   fixture.remove_person(FIXTURE_GROUP, OWNER_ID)), 403))

    # A group deleted after the page loaded.
    env.as_user("owner-1")
    cases.append(("group_not_found", real(env.add_member("g-missing", add_body("newcomer-1"))),
                  lambda fixture: drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/members", body=add_body(NORA["userId"])),
                  lambda fixture: fixture.delete_group(FIXTURE_GROUP), 404))

    # A group that keeps changing.
    env.reset()
    seed(env)
    env.add_directory_user("newcomer-1")
    env.as_user("owner-1")
    keep_changing(env)
    cases.append(("group_write_conflict", real(env.add_member(REAL_GROUP, add_body("newcomer-1"))),
                  lambda fixture: drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/members", body=add_body(NORA["userId"])),
                  lambda fixture: fixture.force_conflict("POST", "members"), 409))

    for code, real_answer, send, arrange, status in cases:
        fixture = new_fixture()
        if arrange:
            arrange(fixture)
        fixture_answer = send(fixture)
        assert_same_refusal(f"add-{code}", fixture_answer, real_answer, status, code)
        assert_no_store(f"add-{code}", fixture_answer, real_answer)


@pytest.mark.parametrize("body", [
    {"userId": "x", "role": "User", "colour": "red"},
    {"userId": "x", "role": "Owner"},
    {"userId": "x", "role": "User", "displayName": 5},
    {"userId": "x", "role": "User", "email": "a" * 257},
    {"userId": "bad/id", "role": "User"},
])
def test_add_reviewed_400s_match(env, body):
    seed(env)
    env.as_user("owner-1")
    real_answer = real(env.add_member(REAL_GROUP, body))
    fixture_answer = drive(new_fixture(), "POST", f"{base(FIXTURE_GROUP)}/members", body=body)
    assert_same_refusal(f"add-400 {body}", fixture_answer, real_answer, 400, "invalid_request")


# --------------------------------------------------------------------------
# Role change.
# --------------------------------------------------------------------------

def test_role_change_shapes_match(env):
    seed(env)
    env.as_user("owner-1")
    real_changed = real(env.change_role(REAL_GROUP, "member-1", {"role": "DocumentManager"}))
    real_unchanged = real(env.change_role(REAL_GROUP, "member-1", {"role": "DocumentManager"}))

    fixture = new_fixture()
    path = f"{base(FIXTURE_GROUP)}/members/{MAYA['userId']}"
    fixture_changed = drive(fixture, "PATCH", path, body={"role": "DocumentManager"})
    fixture_unchanged = drive(fixture, "PATCH", path, body={"role": "DocumentManager"})

    for scenario, fixture_answer, real_answer, changed in (
        ("role-changed", fixture_changed, real_changed, True),
        ("role-unchanged", fixture_unchanged, real_unchanged, False),
    ):
        assert_same_shape(scenario, fixture_answer, real_answer, {"member", "changed"})
        assert_same_row(scenario, fixture_answer.payload["member"], real_answer.payload["member"])
        assert fixture_answer.payload["changed"] is real_answer.payload["changed"] is changed
        assert_no_store(scenario, fixture_answer, real_answer)


def test_role_change_refusals_match(env):
    seed(env)
    path = f"{base(FIXTURE_GROUP)}/members"
    cases = []
    env.as_user("admin-1")
    cases.append(("owner_target", 409, real(env.change_role(REAL_GROUP, "owner-1", {"role": "Admin"})),
                  lambda fixture: fixture.set_viewer_role(FIXTURE_GROUP, "Admin"),
                  lambda fixture: drive(fixture, "PATCH", f"{path}/{OMAR['userId']}", body={"role": "Admin"})))
    cases.append(("member_not_found", 404, real(env.change_role(REAL_GROUP, "outsider-1", {"role": "Admin"})),
                  None, lambda fixture: drive(fixture, "PATCH", f"{path}/{PRIYA['userId']}", body={"role": "Admin"})))
    env.as_user("member-1")
    cases.append(("membership_permission", 403, real(env.change_role(REAL_GROUP, "manager-1", {"role": "Admin"})),
                  lambda fixture: fixture.set_viewer_role(FIXTURE_GROUP, "User"),
                  lambda fixture: drive(fixture, "PATCH", f"{path}/{DMITRI['userId']}", body={"role": "Admin"})))
    env.as_user("owner-1")
    cases.append(("invalid_request", 400, real(env.change_role(REAL_GROUP, "member-1", {"role": "Admin", "x": 1})),
                  None, lambda fixture: drive(fixture, "PATCH", f"{path}/{MAYA['userId']}", body={"role": "Admin", "x": 1})))
    keep_changing(env)
    cases.append(("group_write_conflict", 409, real(env.change_role(REAL_GROUP, "member-1", {"role": "Admin"})),
                  lambda fixture: fixture.force_conflict("PATCH", f"members/{MAYA['userId']}"),
                  lambda fixture: drive(fixture, "PATCH", f"{path}/{MAYA['userId']}", body={"role": "Admin"})))

    for code, status, real_answer, arrange, send in cases:
        fixture = new_fixture()
        if arrange:
            arrange(fixture)
        fixture_answer = send(fixture)
        assert_same_refusal(f"role-{code}", fixture_answer, real_answer, status, code)
        assert_no_store(f"role-{code}", fixture_answer, real_answer)


# --------------------------------------------------------------------------
# Remove and leave.
# --------------------------------------------------------------------------

def test_remove_and_leave_shapes_match(env):
    seed(env)
    env.as_user("owner-1")
    real_remove = real(env.remove_member(REAL_GROUP, "member-1"))
    env.as_user("manager-1")
    real_leave = real(env.remove_member(REAL_GROUP, "manager-1"))

    fixture = new_fixture()
    fixture_remove = drive(fixture, "DELETE", f"{base(FIXTURE_GROUP)}/members/{LEE['userId']}")
    fixture.set_viewer_role(FIXTURE_GROUP, "DocumentManager")
    fixture_leave = drive(fixture, "DELETE", f"{base(FIXTURE_GROUP)}/members/{OWNER_ID}")

    for scenario, fixture_answer, real_answer, left in (
        ("remove", fixture_remove, real_remove, False), ("leave", fixture_leave, real_leave, True),
    ):
        assert_same_shape(scenario, fixture_answer, real_answer, {"userId", "left"})
        assert fixture_answer.payload["left"] is real_answer.payload["left"] is left
        assert_no_store(scenario, fixture_answer, real_answer)


def test_remove_and_leave_refusals_match(env):
    seed(env)
    env.as_user("owner-1")
    real_owner_leave = real(env.remove_member(REAL_GROUP, "owner-1"))
    env.as_user("admin-1")
    real_owner_remove = real(env.remove_member(REAL_GROUP, "owner-1"))
    env.as_user("member-1")
    real_permission = real(env.remove_member(REAL_GROUP, "manager-1"))

    fixture = new_fixture()
    assert_same_refusal("owner-leave", drive(fixture, "DELETE", f"{base(FIXTURE_GROUP)}/members/{OWNER_ID}"),
                        real_owner_leave, 409, "owner_cannot_leave")
    fixture.set_viewer_role(FIXTURE_GROUP, "Admin")
    owner_id = fixture.document(FIXTURE_GROUP)["owner"]["id"]
    assert_same_refusal("owner-remove", drive(fixture, "DELETE", f"{base(FIXTURE_GROUP)}/members/{owner_id}"),
                        real_owner_remove, 409, "owner_target")
    fixture.set_viewer_role(FIXTURE_GROUP, "User")
    assert_same_refusal("remove-permission", drive(fixture, "DELETE", f"{base(FIXTURE_GROUP)}/members/{DMITRI['userId']}"),
                        real_permission, 403, "membership_permission")


# --------------------------------------------------------------------------
# Join requests.
# --------------------------------------------------------------------------

def test_approve_and_reject_shapes_match(env):
    seed(env, pending=("applicant-1", "outsider-1", "member-1"))
    env.as_user("owner-1")
    real_approve = real(env.approve(REAL_GROUP, "applicant-1"))
    real_already = real(env.approve(REAL_GROUP, "member-1"))
    real_reject = real(env.reject(REAL_GROUP, "outsider-1"))

    fixture = new_fixture()
    fixture.add_pending(FIXTURE_GROUP, MAYA)
    fixture_approve = drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/requests/{PRIYA['userId']}/approve")
    fixture_already = drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/requests/{MAYA['userId']}/approve")
    fixture_reject = drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/requests/{fixture_module.SAM['userId']}/reject")

    for scenario, fixture_answer, real_answer, already in (
        ("approve", fixture_approve, real_approve, False), ("approve-member", fixture_already, real_already, True),
    ):
        assert_same_shape(scenario, fixture_answer, real_answer, {"member", "already_member"})
        assert_same_row(scenario, fixture_answer.payload["member"], real_answer.payload["member"])
        assert fixture_answer.payload["already_member"] is real_answer.payload["already_member"] is already
        assert_no_store(scenario, fixture_answer, real_answer)
    assert_same_shape("reject", fixture_reject, real_reject, {"userId"})
    assert_no_store("reject", fixture_reject, real_reject)


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_decisions_without_a_request_match(env, decision):
    seed(env, pending=())
    env.as_user("owner-1")
    real_answer = real(getattr(env, decision)(REAL_GROUP, "outsider-1"))
    fixture = new_fixture()
    fixture.approve_elsewhere(FIXTURE_GROUP, PRIYA["userId"])
    fixture_answer = drive(fixture, "POST", f"{base(FIXTURE_GROUP)}/requests/{PRIYA['userId']}/{decision}")
    assert_same_refusal(f"{decision}-none", fixture_answer, real_answer, 409, "no_pending_request")
    assert_no_store(f"{decision}-none", fixture_answer, real_answer)


# --------------------------------------------------------------------------
# Transfer.
# --------------------------------------------------------------------------

def test_transfer_shapes_match(env):
    seed(env)
    env.as_user("owner-1")
    real_changed = real(env.transfer(REAL_GROUP, {"userId": "admin-1"}))
    real_unchanged = real(env.transfer(REAL_GROUP, {"userId": "admin-1"}))

    fixture = new_fixture()
    fixture_changed = drive(fixture, "PUT", f"{base(FIXTURE_GROUP)}/owner", body={"userId": OLIVIA["userId"]})
    fixture_unchanged = drive(fixture, "PUT", f"{base(FIXTURE_GROUP)}/owner", body={"userId": OLIVIA["userId"]})

    for scenario, fixture_answer, real_answer, changed in (
        ("transfer", fixture_changed, real_changed, True), ("transfer-again", fixture_unchanged, real_unchanged, False),
    ):
        assert_same_shape(scenario, fixture_answer, real_answer, {"owner", "changed"})
        assert_same_row(scenario, fixture_answer.payload["owner"], real_answer.payload["owner"])
        assert fixture_answer.payload["changed"] is real_answer.payload["changed"] is changed
        assert fixture_answer.payload["owner"]["role"] == real_answer.payload["owner"]["role"] == "Owner"
        assert_no_store(scenario, fixture_answer, real_answer)


def test_transfer_refusals_match(env):
    seed(env)
    env.as_user("admin-1")
    real_owner_only = real(env.transfer(REAL_GROUP, {"userId": "member-1"}))
    env.as_user("owner-1")
    real_not_member = real(env.transfer(REAL_GROUP, {"userId": "outsider-1"}))

    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_GROUP, "Admin")
    assert_same_refusal("transfer-owner-only", drive(fixture, "PUT", f"{base(FIXTURE_GROUP)}/owner", body={"userId": MAYA["userId"]}),
                        real_owner_only, 403, "owner_only")
    fixture.set_viewer_role(FIXTURE_GROUP, "Owner")
    assert_same_refusal("transfer-not-member", drive(fixture, "PUT", f"{base(FIXTURE_GROUP)}/owner", body={"userId": PRIYA["userId"]}),
                        real_not_member, 404, "member_not_found")


# --------------------------------------------------------------------------
# The people search.
# --------------------------------------------------------------------------

def test_people_search_answers_in_the_real_route_shape():
    search = UserSearchEnvironment()
    search.graph.answer = graph_response(200, {"value": [
        {"id": "u-1", "displayName": "Nora Newcomer", "mail": "nora@example.test", "userPrincipalName": "nora@corp.test"},
    ]})
    real_status, real_body, _text = search.search("Nora")

    fixture = new_fixture()
    fixture_answer = drive(fixture, "GET", "/api/userSearch", query={"query": ["Nora"]})

    assert (fixture_answer.status, real_status) == (200, 200)
    assert isinstance(fixture_answer.payload, list) and isinstance(real_body, list)
    assert fixture_answer.payload and real_body
    for row in fixture_answer.payload:
        assert set(row) == set(real_body[0]) == {"id", "displayName", "email"}


@pytest.mark.parametrize("failure,status", [
    ("timeout", 504), ("transport", 502), ("token", 401),
])
def test_people_search_failures_match(failure, status):
    search = UserSearchEnvironment()
    if failure == "timeout":
        search.graph.answer = requests.exceptions.ReadTimeout("slow")
    elif failure == "transport":
        search.graph.answer = requests.exceptions.ConnectionError("refused")
    else:
        search.token = None
    real_status, real_body, _text = search.search("Nora")

    fixture = new_fixture()
    message = {
        "timeout": fixture_module.USER_SEARCH_TIMEOUT_MESSAGE,
        "transport": fixture_module.USER_SEARCH_FAILED_MESSAGE,
        "token": fixture_module.USER_SEARCH_TOKEN_MESSAGE,
    }[failure]
    fixture.user_search_failure = (status, message)
    fixture_answer = drive(fixture, "GET", "/api/userSearch", query={"query": ["Nora"]})

    assert (fixture_answer.status, real_status) == (status, status)
    assert fixture_answer.payload == real_body == {"error": message}


# --------------------------------------------------------------------------
# The fixture refuses what the server would never be asked by this page.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("GET", "/api/groups/group-a/members"),
    ("POST", "/api/groups/group-a/members"),
    ("DELETE", "/api/groups/group-a/members/someone"),
    ("GET", "/api/groups/group-a/requests"),
    ("PATCH", "/api/groups/group-a/requests/someone"),
    ("PATCH", "/api/groups/group-a/transferOwnership"),
])
def test_the_fixture_traps_the_classic_membership_routes(method, path):
    fixture = new_fixture()
    drive(fixture, method, path)
    assert fixture.unexpected_requests and "classic membership route" in fixture.unexpected_requests[0]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
