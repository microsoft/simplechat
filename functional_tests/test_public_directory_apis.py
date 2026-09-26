# test_public_directory_apis.py
"""
Functional test for the native public workspace directory API.
Version: 0.261.179
Implemented in: 0.261.175

``GET /api/public_workspaces/directory`` runs for real (``functions_public_directory``
and ``route_backend_public_directory``, registered as ``app.py`` does) against the
etag-enforcing public workspaces container and its model of the directory query
(``test_support/public_directory_harness.py``). ``functions_group``,
``functions_public_workspaces`` and ``functions_workspace_branding`` are their real
modules.

It pins that:

- a row is exactly the reviewed projection for every caller: the name, the
  description, the branding, the caller's own role, its membership and the status,
  and never the owner's email or id or any member's entry (decision 22);
- the caller's role comes from the shared read predicate and both member formats
  resolve, membership is ``member`` only for a stored role, and ``hasLogo`` needs a
  stored logo and nothing else, because the logo route is reader-open;
- ``view``, ``search``, ``page`` and ``page_size`` behave as documented, rows are
  ordered by casefolded name then id, ``total_count`` counts the filtered view, and
  an unknown status is reported as ``unknown``;
- the response is GET-only, ``no-store``, carries the ``public_directory`` hint, and
  every bad request is a stable, data-free 400;
- an unauthenticated caller is refused, and a caller is refused when public
  workspaces are disabled, and neither reaches the container.
"""

import pytest

from test_support.public_directory_harness import (
    PEOPLE,
    public_directory_environment,
)


ROW_KEYS = {
    "id", "name", "description", "heroColor", "hasLogo", "logoVersion",
    "userRole", "membership", "status",
}
LOGO = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"


@pytest.fixture(scope="module")
def module_env():
    with public_directory_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def rows(response):
    assert response.status_code == 200, response.get_json()
    return response.get_json()["workspaces"]


def ids(response):
    return [row["id"] for row in rows(response)]


def assert_refused(response, status, error_code):
    assert response.status_code == status, response.get_json()
    payload = response.get_json()
    assert payload.get("error_code") == error_code
    assert isinstance(payload.get("error"), str) and payload["error"]
    assert response.headers["Cache-Control"] == "no-store"


def assert_no_identities(response):
    """No user id, no email and no member's name appears anywhere in the body."""
    text = response.get_data(as_text=True)
    for user_id, (name, email) in PEOPLE.items():
        assert user_id not in text
        assert email not in text
        assert name not in text
    for fragment in ("owner", "admins", "documentManagers", "email", "logoBase64", "_etag"):
        assert fragment not in text


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caller", ["owner-1", "admin-1", "manager-1", "reader-1", "outsider-1"])
def test_every_caller_gets_only_the_directory_projection(env, caller):
    env.seed_workspace("w-1", "Shared", logo=LOGO, status="active")
    env.seed_workspace("w-2", "Other", owner="outsider-1", admins=(), managers=())
    env.as_user(caller)
    response = env.directory()
    assert response.headers["Cache-Control"] == "no-store"
    for row in rows(response):
        assert set(row) == ROW_KEYS
    assert_no_identities(response)


def test_the_hint_identifies_the_directory(env):
    env.seed_workspace("w-1", "Shared")
    env.as_user("reader-1")
    payload = env.directory().get_json()
    assert payload["public_directory"] == {"schema_version": 1, "can_create": True}
    assert payload["page"] == 1 and payload["page_size"] == 20 and payload["total_count"] == 1


def test_the_create_hint_follows_the_creation_role_requirement(env):
    """``can_create`` mirrors the classic ``POST /api/public_workspaces`` gate, per M10A."""
    env.settings["require_member_of_create_public_workspace"] = True
    env.seed_workspace("w-1", "Shared")

    env.as_user("reader-1", roles=["User"])
    assert env.directory().get_json()["public_directory"]["can_create"] is False

    env.as_user("reader-1", roles=["User", "CreatePublicWorkspaces"])
    assert env.directory().get_json()["public_directory"]["can_create"] is True

    env.settings["enable_public_workspaces"] = False
    denied = env.directory()
    assert denied.status_code == 400
    assert denied.get_json() == {"error": "Enable Public Workspaces is disabled."}


def test_a_row_carries_the_reviewed_values(env):
    env.seed_workspace("w-1", "Marketing", description="Team space", hero_color="#112233", logo=LOGO)
    env.as_user("owner-1")
    row = rows(env.directory())[0]
    assert row == {
        "id": "w-1", "name": "Marketing", "description": "Team space",
        "heroColor": "#112233", "hasLogo": True, "logoVersion": 1,
        "userRole": "Owner", "membership": "member", "status": "active",
    }


# ---------------------------------------------------------------------------
# Role, membership and logo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caller,role,membership", [
    ("owner-1", "Owner", "member"),
    ("admin-1", "Admin", "member"),
    ("manager-1", "DocumentManager", "member"),
    ("reader-1", "User", "none"),
    ("outsider-1", "User", "none"),
])
def test_role_and_membership_follow_the_read_predicate(env, caller, role, membership):
    env.seed_workspace("w-1", "Shared")
    env.as_user(caller)
    row = rows(env.directory())[0]
    assert row["userRole"] == role
    assert row["membership"] == membership


def test_dict_member_entries_also_resolve_the_role(env):
    env.seed_workspace("w-1", "Shared", admins=(("admin-1", "dict"),), managers=(("manager-1", "dict"),))
    env.as_user("admin-1")
    assert rows(env.directory())[0]["userRole"] == "Admin"
    env.as_user("manager-1")
    assert rows(env.directory())[0]["userRole"] == "DocumentManager"


def test_haslogo_needs_only_a_stored_logo(env):
    env.seed_workspace("with-logo", "With logo", logo=LOGO)
    env.seed_workspace("without-logo", "Without logo", logo="")
    env.as_user("outsider-1")
    by_id = {row["id"]: row for row in rows(env.directory())}
    assert by_id["with-logo"]["hasLogo"] is True
    assert by_id["without-logo"]["hasLogo"] is False


def test_an_unknown_status_is_reported_as_unknown(env):
    env.seed_workspace("w-1", "Shared", status="archived")
    env.seed_workspace("w-2", "Locked", status="locked")
    env.as_user("outsider-1")
    by_id = {row["id"]: row for row in rows(env.directory())}
    assert by_id["w-1"]["status"] == "unknown"
    assert by_id["w-2"]["status"] == "locked"


# ---------------------------------------------------------------------------
# view, search, ordering and paging
# ---------------------------------------------------------------------------

def test_view_mine_keeps_only_the_callers_workspaces(env):
    env.seed_workspace("mine", "Mine", admins=("admin-1",))
    env.seed_workspace("theirs", "Theirs", owner="outsider-1", admins=(), managers=())
    env.as_user("admin-1")
    assert ids(env.directory(query_string={"view": "all"})) == ["mine", "theirs"]
    assert ids(env.directory(query_string={"view": "mine"})) == ["mine"]


def test_search_matches_name_description_or_exact_id(env):
    env.seed_workspace("alpha-id", "Alpha", description="First team")
    env.seed_workspace("beta-id", "Beta", description="Second team")
    env.as_user("outsider-1")
    assert ids(env.directory(query_string={"search": "alpha"})) == ["alpha-id"]
    assert ids(env.directory(query_string={"search": "Second"})) == ["beta-id"]
    assert ids(env.directory(query_string={"search": "BETA-ID"})) == ["beta-id"]
    assert ids(env.directory(query_string={"search": "team"})) == ["alpha-id", "beta-id"]


def test_rows_are_ordered_by_casefolded_name_then_id(env):
    env.seed_workspace("z-1", "apple")
    env.seed_workspace("a-2", "Apple")
    env.seed_workspace("m-3", "Banana")
    env.as_user("outsider-1")
    assert ids(env.directory()) == ["a-2", "z-1", "m-3"]


def test_paging_cuts_the_sorted_filtered_view(env):
    for index in range(5):
        env.seed_workspace(f"w-{index}", f"Name {index}")
    env.as_user("outsider-1")
    first = env.directory(query_string={"page": "1", "page_size": "2"}).get_json()
    assert [row["id"] for row in first["workspaces"]] == ["w-0", "w-1"]
    assert first["total_count"] == 5
    second = env.directory(query_string={"page": "3", "page_size": "2"}).get_json()
    assert [row["id"] for row in second["workspaces"]] == ["w-4"]


# ---------------------------------------------------------------------------
# Strict requests and refusals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query_string", [
    {"nope": "1"},
    {"view": "everyone"},
    {"page": "0"},
    {"page": "abc"},
    {"page_size": "0"},
    {"page_size": "1000"},
    {"search": "x" * 201},
])
def test_bad_requests_are_stable_data_free_400s(env, query_string):
    env.seed_workspace("w-1", "Shared")
    env.as_user("outsider-1")
    assert_refused(env.directory(query_string=query_string), 400, "invalid_request")


def test_a_repeated_parameter_is_refused(env):
    env.as_user("outsider-1")
    assert_refused(env.directory(query_string="view=all&view=mine"), 400, "invalid_request")


def test_a_request_body_is_refused(env):
    env.as_user("outsider-1")
    response = env.call("GET", "/api/public_workspaces/directory", body={"view": "all"})
    assert_refused(response, 400, "invalid_request")


def test_an_unauthenticated_caller_is_refused_before_the_container(env):
    env.seed_workspace("w-1", "Shared")
    env.sign_out()
    env.public_workspaces.calls.clear()
    response = env.directory()
    assert response.status_code == 401
    assert env.public_workspaces.calls == []


def test_disabled_public_workspaces_refuses_before_the_container(env):
    env.settings["enable_public_workspaces"] = False
    env.seed_workspace("w-1", "Shared")
    env.as_user("outsider-1")
    env.public_workspaces.calls.clear()
    response = env.directory()
    assert response.status_code == 400
    assert env.public_workspaces.calls == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
