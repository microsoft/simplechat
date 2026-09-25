# test_public_membership_fixture_parity.py
"""
Per-route shape parity between the M10A public membership UI fixture and the real routes.
Version: 0.261.177
Implemented in: 0.261.177

The V2 public Members section reuses the shared Members section against the closed HTTP fixture
`ui_tests/fixtures/public_members.py`. A fixture whose answers drift from the server would let a
passing browser test hide a real regression, so this test holds the fixture to the real native
public membership routes -- the same real ``functions_public_membership`` logic, its policy and
disclosure projectors, its route registrar and the real ``get_user_role_in_public_workspace``
resolver -- driven through the isolated Flask app the public membership functional tests build
(`test_public_membership_apis.environment`), and pins the fixture's people search to the real
``/api/userSearch`` route.

For every route the Members section calls it asserts that the fixture never invents a top-level or
row key the server does not return, that the keys the page reads are present in both, and that the
status, the machine-readable ``error_code`` and, for every refusal, the reviewed message match. It
covers the outcomes the section handles: the list and its ``membership_management`` hint, the email
redaction a DocumentManager viewer sees (decision 18), the request list, add with each refusal and
the reviewed 400s, role change with its no-op and the owner refusal, remove with the self-removal
refusal (there is no ``leave``, decision 17), the owner refusals, approve with ``already_member``
and ``no_pending_request``, reject, transfer with its no-op, ``owner_only`` and the decision-21 old
owner, ``public_workspace_write_conflict``, ``workspace_not_found``, ``not_a_member`` and
``membership_permission``. It also pins that every membership response is ``no-store`` in both, that
the fixture's policy and disclosure are the real modules, that its messages are the server's, and
that a legacy bare-string document manager is tolerated on both sides (R5.5).

The fixture handlers are the production browser-test code, exercised through the same ``_dispatch``
entry the Playwright route handler calls, with a tiny fake page and route.
"""

import ast
import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "functional_tests", ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN, OWNER_ID  # noqa: E402
from ui_tests.fixtures import public_members as fixture_module  # noqa: E402
from ui_tests.fixtures.public_members import (  # noqa: E402
    DMITRI, LEE, LONG, MAYA, NIA, NORA, OLIVIA, OMAR, PRIYA, SAM, PublicMembersFixture,
)

# The real routes: the isolated Flask app the public membership functional tests build. Importing
# the `environment` fixture and its helpers reuses that harness verbatim, so this test drives the
# same real modules those tests do.
from test_public_membership_apis import (  # noqa: E402,F401
    environment, login, ADMIN, MANAGER, OUTSIDER, OWNER, PENDING,
    MEMBERS_PATH, OWNER_PATH, REQUESTS_PATH,
)
from test_user_search_hardening import Environment as UserSearchEnvironment, graph_response  # noqa: E402


APP_ROOT = ROOT / "application" / "single_app"
FIXTURE_WS = "pub-a"
REAL_WS = "ws-a"
LIST_KEYS = {"members", "page", "page_size", "total_count", "membership_management"}
ROW_KEYS = {"userId", "displayName", "email", "role", "member_actions"}
HINT_KEYS = {"schema_version", "operations"}
REQUEST_LIST_KEYS = {"requests", "total_count"}
REQUEST_ROW_KEYS = {"userId", "displayName", "email"}
ERROR_KEYS = {"error", "error_code"}
# The real harness user who holds each stored role in the seeded public workspace.
REAL_ROLE_USERS = {"Owner": OWNER, "Admin": ADMIN, "DocumentManager": MANAGER}


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


def new_fixture():
    return PublicMembersFixture(_FakePage())


def fbase(workspace_id):
    return f"/api/public-workspaces/{workspace_id}/membership"


# --------------------------------------------------------------------------
# Real routes: the isolated Flask app, driven by its test client.
# --------------------------------------------------------------------------

def real(env, method, path, oid, body=None, query=None):
    login(env, oid)
    call = getattr(env.client, method.lower())
    kwargs = {}
    if body is not None:
        kwargs["json"] = body
    if query is not None:
        kwargs["query_string"] = query
    response = call(path, **kwargs)
    return Answer(response.status_code, response.get_json(), dict(response.headers))


def real_members(env, oid, *, workspace=REAL_WS, query=None):
    return real(env, "GET", f"/api/public-workspaces/{workspace}/membership/members", oid, query=query)


# --------------------------------------------------------------------------
# Parity assertions (the group parity test's helpers, unchanged).
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
# The policy, the disclosure and the messages are the server's.
# --------------------------------------------------------------------------

def test_the_fixture_policy_and_disclosure_are_the_real_modules():
    assert Path(fixture_module.POLICY.__file__).resolve() == (APP_ROOT / "functions_public_membership_policy.py").resolve()
    assert Path(fixture_module.DISCLOSURE.__file__).resolve() == (APP_ROOT / "functions_public_membership_disclosure.py").resolve()


def _message_literals(file_name):
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    literals = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith("_MESSAGE"):
                    literals[target.id] = node.value.value
    return literals


@pytest.mark.parametrize("name", [
    "WORKSPACE_NOT_FOUND_MESSAGE", "NOT_A_MEMBER_MESSAGE", "MEMBERSHIP_PERMISSION_MESSAGE", "OWNER_ONLY_MESSAGE",
    "STATUS_UNAVAILABLE_MESSAGE", "MEMBER_NOT_FOUND_MESSAGE", "ALREADY_MEMBER_MESSAGE", "NO_PENDING_REQUEST_MESSAGE",
    "OWNER_ROLE_MESSAGE", "OWNER_REMOVAL_MESSAGE", "SELF_REMOVAL_MESSAGE",
])
def test_the_fixture_messages_are_the_server_messages(name):
    """Each refusal message is the sentence the server's source defines, verbatim."""
    literals = _message_literals("functions_public_membership.py")
    assert getattr(fixture_module, name) == literals[name]


def test_the_fixture_write_conflict_text_is_the_one_public_constant():
    """The fixture reads functions_public_workspaces' own sentence, the one the guard answers with."""
    literals = _message_literals("functions_public_workspaces.py")
    assert fixture_module.WRITE_CONFLICT_MESSAGE == literals["PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE"]
    assert fixture_module.WRITE_CONFLICT_CODE == "public_workspace_write_conflict"


# --------------------------------------------------------------------------
# Reads.
# --------------------------------------------------------------------------

def action_map(rows, caller_id):
    return {(row["role"], row["userId"] == caller_id): tuple(row["member_actions"]) for row in rows}


@pytest.mark.parametrize("role", ["Owner", "Admin", "DocumentManager"])
@pytest.mark.parametrize("status", ["active", "locked"])
def test_member_list_shape_and_hints_match(environment, role, status):
    workspace = REAL_WS if status == "active" else "locked-ws"
    real_answer = real_members(environment, REAL_ROLE_USERS[role], workspace=workspace)

    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_WS, role, status=status)
    fixture_answer = drive(fixture, "GET", f"{fbase(FIXTURE_WS)}/members")

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


def test_a_document_manager_viewer_sees_no_emails_in_both(environment):
    """Decision 18: only the Owner and Admins see members' emails; a DocumentManager sees names."""
    real_answer = real_members(environment, MANAGER)
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_WS, "DocumentManager")
    fixture_answer = drive(fixture, "GET", f"{fbase(FIXTURE_WS)}/members")

    assert (fixture_answer.status, real_answer.status) == (200, 200)
    assert real_answer.payload["members"] and fixture_answer.payload["members"]
    assert all(row["email"] == "" for row in real_answer.payload["members"])
    assert all(row["email"] == "" for row in fixture_answer.payload["members"])


def test_an_owner_viewer_sees_emails_in_both(environment):
    real_answer = real_members(environment, OWNER)
    fixture = new_fixture()
    fixture_answer = drive(fixture, "GET", f"{fbase(FIXTURE_WS)}/members")
    assert any(row["email"] for row in real_answer.payload["members"])
    assert any(row["email"] for row in fixture_answer.payload["members"])


def test_member_list_query_shape_matches(environment):
    query = {"search": "a", "role": "DocumentManager", "page": "1", "page_size": "2"}
    real_answer = real_members(environment, OWNER, query=query)

    fixture = new_fixture()
    fixture_answer = drive(fixture, "GET", f"{fbase(FIXTURE_WS)}/members",
                           query={key: [value] for key, value in query.items()})

    assert_same_shape("list-query", fixture_answer, real_answer, LIST_KEYS)
    assert (fixture_answer.payload["page"], fixture_answer.payload["page_size"]) == (1, 2)
    assert (real_answer.payload["page"], real_answer.payload["page_size"]) == (1, 2)
    assert all(row["role"] == "DocumentManager" for row in fixture_answer.payload["members"])
    assert all(row["role"] == "DocumentManager" for row in real_answer.payload["members"])


@pytest.mark.parametrize("query", [
    {"bogus": "x"}, {"role": "Superuser"}, {"page": "0"}, {"page_size": "101"}, {"search": "x" * 201},
])
def test_member_list_strict_query_refusals_match(environment, query):
    real_answer = real_members(environment, OWNER, query=query)
    fixture = new_fixture()
    fixture_answer = drive(fixture, "GET", f"{fbase(FIXTURE_WS)}/members",
                           query={key: [value] for key, value in query.items()})
    assert_same_refusal(f"list-400 {query}", fixture_answer, real_answer, 400, "invalid_request")
    assert_no_store("list-400", fixture_answer, real_answer)


def test_member_list_not_a_member_matches(environment):
    real_answer = real_members(environment, OUTSIDER)
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_WS, "User")
    fixture_answer = drive(fixture, "GET", f"{fbase(FIXTURE_WS)}/members")
    assert_same_refusal("list-not-a-member", fixture_answer, real_answer, 403, "not_a_member")


def test_member_list_workspace_not_found_matches(environment):
    real_answer = real_members(environment, OWNER, workspace="ws-missing")
    fixture_answer = drive(new_fixture(), "GET", f"{fbase('pub-missing')}/members")
    assert_same_refusal("list-workspace-not-found", fixture_answer, real_answer, 404, "workspace_not_found")


def test_a_bare_string_manager_is_tolerated_in_both(environment):
    """R5.5: a legacy bare-string document manager lists with a blank name and email, no crash."""
    real_answer = real_members(environment, OWNER)
    legacy = [row for row in real_answer.payload["members"] if row["userId"] == "legacy-admin"]
    assert legacy and legacy[0]["displayName"] == "" and legacy[0]["email"] == ""

    fixture = new_fixture()
    fixture.add_bare_string_manager(FIXTURE_WS, "legacy-dm")
    fixture_answer = drive(fixture, "GET", f"{fbase(FIXTURE_WS)}/members")
    bare = [row for row in fixture_answer.payload["members"] if row["userId"] == "legacy-dm"]
    assert bare and bare[0]["displayName"] == "" and bare[0]["email"] == ""
    assert bare[0]["role"] == "DocumentManager"


def test_request_list_shape_matches(environment):
    real_answer = real(environment, "GET", REQUESTS_PATH, OWNER)
    fixture = new_fixture()
    fixture_answer = drive(fixture, "GET", f"{fbase(FIXTURE_WS)}/requests")

    assert_same_shape("requests", fixture_answer, real_answer, REQUEST_LIST_KEYS)
    for fixture_row, real_row in zip(fixture_answer.payload["requests"], real_answer.payload["requests"]):
        assert_no_invented_keys("request-row", fixture_row, real_row)
        assert_shared_keys("request-row", fixture_row, real_row, REQUEST_ROW_KEYS)
    assert_no_store("requests", fixture_answer, real_answer)


def test_request_list_permission_refusal_matches(environment):
    real_answer = real(environment, "GET", REQUESTS_PATH, MANAGER)
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_WS, "DocumentManager")
    fixture_answer = drive(fixture, "GET", f"{fbase(FIXTURE_WS)}/requests")
    assert_same_refusal("requests-permission", fixture_answer, real_answer, 403, "membership_permission")


# --------------------------------------------------------------------------
# Add.
# --------------------------------------------------------------------------

def add_body(user_id, role="DocumentManager", name="", email=""):
    return {"userId": user_id, "displayName": name, "email": email, "role": role}


def test_add_success_shape_matches(environment):
    real_answer = real(environment, "POST", MEMBERS_PATH, OWNER, body=add_body(NORA["userId"], "Admin"))
    fixture_answer = drive(new_fixture(), "POST", f"{fbase(FIXTURE_WS)}/members", body=add_body(NORA["userId"], "Admin"))

    assert_same_shape("add", fixture_answer, real_answer, {"member"})
    assert (fixture_answer.status, real_answer.status) == (201, 201)
    assert_same_row("add-row", fixture_answer.payload["member"], real_answer.payload["member"])
    assert fixture_answer.payload["member"]["role"] == real_answer.payload["member"]["role"] == "Admin"
    assert_no_store("add", fixture_answer, real_answer)


def test_add_uses_the_submitted_details_in_both(environment):
    """A public add trusts the submitted name and email; neither side re-reads a directory by id."""
    body = add_body(NORA["userId"], name="Typed Name", email="typed@example.test")
    real_answer = real(environment, "POST", MEMBERS_PATH, OWNER, body=body)
    fixture_answer = drive(new_fixture(), "POST", f"{fbase(FIXTURE_WS)}/members", body=body)
    assert_same_shape("add-typed", fixture_answer, real_answer, {"member"})
    for answer in (fixture_answer, real_answer):
        assert (answer.payload["member"]["displayName"], answer.payload["member"]["email"]) == ("Typed Name", "typed@example.test")


def test_add_already_member_matches(environment):
    real_answer = real(environment, "POST", MEMBERS_PATH, OWNER, body=add_body(MANAGER))
    fixture_answer = drive(new_fixture(), "POST", f"{fbase(FIXTURE_WS)}/members", body=add_body(MAYA["userId"]))
    assert_same_refusal("add-already-member", fixture_answer, real_answer, 409, "already_member")
    assert_no_store("add-already-member", fixture_answer, real_answer)


def test_add_status_unavailable_matches(environment):
    real_answer = real(environment, "POST", "/api/public-workspaces/locked-ws/membership/members", OWNER, body=add_body(NORA["userId"]))
    fixture = new_fixture()
    fixture.set_status(FIXTURE_WS, "locked")
    fixture_answer = drive(fixture, "POST", f"{fbase(FIXTURE_WS)}/members", body=add_body(NORA["userId"]))
    assert_same_refusal("add-status", fixture_answer, real_answer, 403, "public_status_unavailable")
    assert_no_store("add-status", fixture_answer, real_answer)


def test_add_membership_permission_matches(environment):
    real_answer = real(environment, "POST", MEMBERS_PATH, MANAGER, body=add_body(NORA["userId"]))
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_WS, "DocumentManager")
    fixture_answer = drive(fixture, "POST", f"{fbase(FIXTURE_WS)}/members", body=add_body(NORA["userId"]))
    assert_same_refusal("add-permission", fixture_answer, real_answer, 403, "membership_permission")


def test_add_not_a_member_matches(environment):
    real_answer = real(environment, "POST", MEMBERS_PATH, OUTSIDER, body=add_body(NORA["userId"]))
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_WS, "User")
    fixture_answer = drive(fixture, "POST", f"{fbase(FIXTURE_WS)}/members", body=add_body(NORA["userId"]))
    assert_same_refusal("add-not-a-member", fixture_answer, real_answer, 403, "not_a_member")


def test_add_workspace_not_found_matches(environment):
    real_answer = real(environment, "POST", "/api/public-workspaces/ws-missing/membership/members", OWNER, body=add_body(NORA["userId"]))
    fixture_answer = drive(new_fixture(), "POST", f"{fbase('pub-missing')}/members", body=add_body(NORA["userId"]))
    assert_same_refusal("add-workspace-not-found", fixture_answer, real_answer, 404, "workspace_not_found")


def test_add_write_conflict_matches(environment):
    environment.conflict["raise"] = True
    real_answer = real(environment, "POST", MEMBERS_PATH, OWNER, body=add_body(NORA["userId"]))
    fixture = new_fixture()
    fixture.force_conflict("POST", "members")
    fixture_answer = drive(fixture, "POST", f"{fbase(FIXTURE_WS)}/members", body=add_body(NORA["userId"]))
    assert_same_refusal("add-conflict", fixture_answer, real_answer, 409, "public_workspace_write_conflict")
    assert_no_store("add-conflict", fixture_answer, real_answer)


@pytest.mark.parametrize("body", [
    {"userId": "x", "role": "DocumentManager", "colour": "red"},
    {"userId": "x", "role": "Owner"},
    {"userId": "x", "role": "User"},
    {"userId": "x", "role": "DocumentManager", "displayName": 5},
    {"userId": "x", "role": "DocumentManager", "email": "a" * 257},
    {"userId": "bad/id", "role": "DocumentManager"},
])
def test_add_reviewed_400s_match(environment, body):
    real_answer = real(environment, "POST", MEMBERS_PATH, OWNER, body=body)
    fixture_answer = drive(new_fixture(), "POST", f"{fbase(FIXTURE_WS)}/members", body=body)
    assert_same_refusal(f"add-400 {body}", fixture_answer, real_answer, 400, "invalid_request")


# --------------------------------------------------------------------------
# Role change.
# --------------------------------------------------------------------------

def test_role_change_shapes_match(environment):
    real_changed = real(environment, "PATCH", f"{MEMBERS_PATH}/{MANAGER}", OWNER, body={"role": "Admin"})
    real_unchanged = real(environment, "PATCH", f"{MEMBERS_PATH}/{MANAGER}", OWNER, body={"role": "Admin"})

    fixture = new_fixture()
    path = f"{fbase(FIXTURE_WS)}/members/{DMITRI['userId']}"
    fixture_changed = drive(fixture, "PATCH", path, body={"role": "Admin"})
    fixture_unchanged = drive(fixture, "PATCH", path, body={"role": "Admin"})

    for scenario, fixture_answer, real_answer, changed in (
        ("role-changed", fixture_changed, real_changed, True),
        ("role-unchanged", fixture_unchanged, real_unchanged, False),
    ):
        assert_same_shape(scenario, fixture_answer, real_answer, {"member", "changed"})
        assert_same_row(scenario, fixture_answer.payload["member"], real_answer.payload["member"])
        assert fixture_answer.payload["changed"] is real_answer.payload["changed"] is changed
        assert_no_store(scenario, fixture_answer, real_answer)


def test_role_change_owner_target_matches(environment):
    real_answer = real(environment, "PATCH", f"{MEMBERS_PATH}/{OWNER}", ADMIN, body={"role": "Admin"})
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_WS, "Admin")
    owner_id = fixture.document(FIXTURE_WS)["owner"]["userId"]
    fixture_answer = drive(fixture, "PATCH", f"{fbase(FIXTURE_WS)}/members/{owner_id}", body={"role": "Admin"})
    assert_same_refusal("role-owner-target", fixture_answer, real_answer, 409, "owner_target")


def test_role_change_member_not_found_matches(environment):
    real_answer = real(environment, "PATCH", f"{MEMBERS_PATH}/{OUTSIDER}", OWNER, body={"role": "Admin"})
    fixture_answer = drive(new_fixture(), "PATCH", f"{fbase(FIXTURE_WS)}/members/{PRIYA['userId']}", body={"role": "Admin"})
    assert_same_refusal("role-member-not-found", fixture_answer, real_answer, 404, "member_not_found")


def test_role_change_permission_matches(environment):
    real_answer = real(environment, "PATCH", f"{MEMBERS_PATH}/{MANAGER}", MANAGER, body={"role": "Admin"})
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_WS, "DocumentManager")
    fixture_answer = drive(fixture, "PATCH", f"{fbase(FIXTURE_WS)}/members/{LEE['userId']}", body={"role": "Admin"})
    assert_same_refusal("role-permission", fixture_answer, real_answer, 403, "membership_permission")


@pytest.mark.parametrize("body", [{"role": "Admin", "x": 1}, {"role": "Owner"}, {"role": "User"}, {}])
def test_role_change_reviewed_400s_match(environment, body):
    real_answer = real(environment, "PATCH", f"{MEMBERS_PATH}/{MANAGER}", OWNER, body=body)
    fixture_answer = drive(new_fixture(), "PATCH", f"{fbase(FIXTURE_WS)}/members/{DMITRI['userId']}", body=body)
    assert_same_refusal(f"role-400 {body}", fixture_answer, real_answer, 400, "invalid_request")


# --------------------------------------------------------------------------
# Remove (there is no leave).
# --------------------------------------------------------------------------

def test_remove_shape_matches(environment):
    real_answer = real(environment, "DELETE", f"{MEMBERS_PATH}/{MANAGER}", OWNER)
    fixture_answer = drive(new_fixture(), "DELETE", f"{fbase(FIXTURE_WS)}/members/{LEE['userId']}")
    assert_same_shape("remove", fixture_answer, real_answer, {"userId"})
    assert_no_store("remove", fixture_answer, real_answer)


def test_remove_self_is_refused_in_both(environment):
    """Decision 17: a public manager can't remove themselves; there is no leave."""
    real_answer = real(environment, "DELETE", f"{MEMBERS_PATH}/{MANAGER}", MANAGER)
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_WS, "DocumentManager")
    fixture_answer = drive(fixture, "DELETE", f"{fbase(FIXTURE_WS)}/members/{OWNER_ID}")
    assert_same_refusal("remove-self", fixture_answer, real_answer, 403, "cannot_leave")
    assert_no_store("remove-self", fixture_answer, real_answer)


def test_remove_owner_is_refused_in_both(environment):
    real_answer = real(environment, "DELETE", f"{MEMBERS_PATH}/{OWNER}", ADMIN)
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_WS, "Admin")
    owner_id = fixture.document(FIXTURE_WS)["owner"]["userId"]
    fixture_answer = drive(fixture, "DELETE", f"{fbase(FIXTURE_WS)}/members/{owner_id}")
    assert_same_refusal("remove-owner", fixture_answer, real_answer, 409, "owner_target")


def test_remove_member_not_found_matches(environment):
    real_answer = real(environment, "DELETE", f"{MEMBERS_PATH}/{OUTSIDER}", OWNER)
    fixture_answer = drive(new_fixture(), "DELETE", f"{fbase(FIXTURE_WS)}/members/{PRIYA['userId']}")
    assert_same_refusal("remove-member-not-found", fixture_answer, real_answer, 404, "member_not_found")


def test_remove_permission_matches(environment):
    real_answer = real(environment, "DELETE", f"{MEMBERS_PATH}/{ADMIN}", MANAGER)
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_WS, "DocumentManager")
    fixture_answer = drive(fixture, "DELETE", f"{fbase(FIXTURE_WS)}/members/{LEE['userId']}")
    assert_same_refusal("remove-permission", fixture_answer, real_answer, 403, "membership_permission")


# --------------------------------------------------------------------------
# Join requests.
# --------------------------------------------------------------------------

def test_approve_and_reject_shapes_match(environment):
    # A second pending entry that is already a document manager, so approve reports already_member.
    environment.store[REAL_WS]["pendingDocumentManagers"].append(
        {"userId": MANAGER, "displayName": "Mona Manager", "email": "mona@example.com"})
    real_approve = real(environment, "POST", f"{REQUESTS_PATH}/{PENDING}/approve", OWNER)
    real_already = real(environment, "POST", f"{REQUESTS_PATH}/{MANAGER}/approve", OWNER)

    fixture = new_fixture()
    fixture.add_pending(FIXTURE_WS, MAYA)
    fixture_approve = drive(fixture, "POST", f"{fbase(FIXTURE_WS)}/requests/{PRIYA['userId']}/approve")
    fixture_already = drive(fixture, "POST", f"{fbase(FIXTURE_WS)}/requests/{MAYA['userId']}/approve")

    for scenario, fixture_answer, real_answer, already in (
        ("approve", fixture_approve, real_approve, False), ("approve-member", fixture_already, real_already, True),
    ):
        assert_same_shape(scenario, fixture_answer, real_answer, {"member", "already_member"})
        assert_same_row(scenario, fixture_answer.payload["member"], real_answer.payload["member"])
        assert fixture_answer.payload["already_member"] is real_answer.payload["already_member"] is already
        assert_no_store(scenario, fixture_answer, real_answer)


def test_reject_shape_matches(environment):
    real_answer = real(environment, "POST", f"{REQUESTS_PATH}/{PENDING}/reject", OWNER)
    fixture = new_fixture()
    fixture_answer = drive(fixture, "POST", f"{fbase(FIXTURE_WS)}/requests/{SAM['userId']}/reject")
    assert_same_shape("reject", fixture_answer, real_answer, {"userId"})
    assert_no_store("reject", fixture_answer, real_answer)


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_decisions_without_a_request_match(environment, decision):
    real_answer = real(environment, "POST", f"{REQUESTS_PATH}/{OUTSIDER}/{decision}", OWNER)
    fixture = new_fixture()
    fixture.approve_elsewhere(FIXTURE_WS, PRIYA["userId"])
    fixture_answer = drive(fixture, "POST", f"{fbase(FIXTURE_WS)}/requests/{PRIYA['userId']}/{decision}")
    assert_same_refusal(f"{decision}-none", fixture_answer, real_answer, 409, "no_pending_request")
    assert_no_store(f"{decision}-none", fixture_answer, real_answer)


# --------------------------------------------------------------------------
# Transfer.
# --------------------------------------------------------------------------

def test_transfer_shapes_match(environment):
    real_changed = real(environment, "PUT", OWNER_PATH, OWNER, body={"userId": ADMIN})
    real_unchanged = real(environment, "PUT", OWNER_PATH, OWNER, body={"userId": ADMIN})

    fixture = new_fixture()
    fixture_changed = drive(fixture, "PUT", f"{fbase(FIXTURE_WS)}/owner", body={"userId": OLIVIA["userId"]})
    fixture_unchanged = drive(fixture, "PUT", f"{fbase(FIXTURE_WS)}/owner", body={"userId": OLIVIA["userId"]})

    for scenario, fixture_answer, real_answer, changed in (
        ("transfer", fixture_changed, real_changed, True), ("transfer-again", fixture_unchanged, real_unchanged, False),
    ):
        assert_same_shape(scenario, fixture_answer, real_answer, {"owner", "changed"})
        assert_same_row(scenario, fixture_answer.payload["owner"], real_answer.payload["owner"])
        assert fixture_answer.payload["changed"] is real_answer.payload["changed"] is changed
        assert fixture_answer.payload["owner"]["role"] == real_answer.payload["owner"]["role"] == "Owner"
        assert_no_store(scenario, fixture_answer, real_answer)


def test_transfer_makes_the_old_owner_a_document_manager_in_both(environment):
    """Decision 21: the old owner stays a DocumentManager, with their name and email carried over."""
    real(environment, "PUT", OWNER_PATH, OWNER, body={"userId": ADMIN})
    real_after = real_members(environment, ADMIN)
    real_old = [row for row in real_after.payload["members"] if row["userId"] == OWNER]
    assert real_old and real_old[0]["role"] == "DocumentManager"

    fixture = new_fixture()
    drive(fixture, "PUT", f"{fbase(FIXTURE_WS)}/owner", body={"userId": OLIVIA["userId"]})
    fixture_after = drive(fixture, "GET", f"{fbase(FIXTURE_WS)}/members")
    fixture_old = [row for row in fixture_after.payload["members"] if row["userId"] == OWNER_ID]
    assert fixture_old and fixture_old[0]["role"] == "DocumentManager"
    assert fixture_old[0]["displayName"] == fixture_module.VIEWER_NAME


def test_transfer_owner_only_matches(environment):
    real_answer = real(environment, "PUT", OWNER_PATH, ADMIN, body={"userId": MANAGER})
    fixture = new_fixture()
    fixture.set_viewer_role(FIXTURE_WS, "Admin")
    fixture_answer = drive(fixture, "PUT", f"{fbase(FIXTURE_WS)}/owner", body={"userId": DMITRI["userId"]})
    assert_same_refusal("transfer-owner-only", fixture_answer, real_answer, 403, "owner_only")


def test_transfer_member_not_found_matches(environment):
    real_answer = real(environment, "PUT", OWNER_PATH, OWNER, body={"userId": OUTSIDER})
    fixture_answer = drive(new_fixture(), "PUT", f"{fbase(FIXTURE_WS)}/owner", body={"userId": PRIYA["userId"]})
    assert_same_refusal("transfer-member-not-found", fixture_answer, real_answer, 404, "member_not_found")


@pytest.mark.parametrize("body", [{"userId": OWNER, "x": 1}, {"role": "Admin"}, {}])
def test_transfer_reviewed_400s_match(environment, body):
    real_answer = real(environment, "PUT", OWNER_PATH, OWNER, body=body)
    fixture_answer = drive(new_fixture(), "PUT", f"{fbase(FIXTURE_WS)}/owner", body=body)
    assert_same_refusal(f"transfer-400 {body}", fixture_answer, real_answer, 400, "invalid_request")


# --------------------------------------------------------------------------
# The people search (the shared /api/userSearch route).
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
