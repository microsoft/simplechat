# test_global_identity_admin_routes.py
"""
The administrator's global identity routes, as V2 Admin Settings calls them.
Version: 0.261.445
Implemented in: 0.261.445

V2 creates, edits and deletes global identities through
``/api/admin/workspace-identities/global/identities``. Those are the older routes: a record
carries no ``etag`` and no ``identity_actions``, and until 0.261.445 a delete refused because a
global action still used the identity answered ``400`` with a sentence and nothing else, which is
the status of a malformed request and gives a client nothing to list. The strict personal, group
and public routes have always answered that refusal as ``409`` with ``error_code`` and the
references, and the V2 identities section (``lib/identityWorkbench.ts``) reads exactly that.

The real route registration, storage and sanitizer run over the in-memory Cosmos stub of the
shared identity harness, with the real ``admin_required`` decorator. Network access is blocked.
What is pinned here:

- the shape the V2 adapter reads from a list, create and update;
- secrets never leave the server;
- a refused delete is ``409`` ``identity_in_use`` naming the global actions that use the
  identity, and nothing is removed;
- the personal route keeps the answer it always had (``400``, a sentence), because the fix is
  confined to the global routes;
- every global route is administrator-only;
- the browser fixture the V2 UI tests run against (``ui_tests/fixtures/v2_admin_global_identities.py``)
  gives the same statuses, keys and codes as the real routes for every request the section makes, so a
  passing browser suite cannot hide a real regression.
"""

import ast
import sys
from copy import deepcopy
from functools import wraps
from pathlib import Path

import pytest
from azure.cosmos._cosmos_responses import CosmosDict
from flask import Blueprint, jsonify, request, session

from test_support.agent_delegation import (
    CosmosResourceNotFoundError,
    execute_functions,
    module_stub,
)
from test_support.group_identity_harness import APP_ROOT, IdentityContainer, as_user, environment  # noqa: F401
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

# The browser fixture imports Playwright, so it has to load before the harness replaces `azure`.
from v2_admin_global_identities import GlobalIdentitiesFixture  # noqa: E402

GLOBAL_PATH = "/api/admin/workspace-identities/global/identities"
PERSONAL_PATH = "/api/workspace-identities/personal/identities"
IN_USE_MESSAGE = "This workspace identity is still used by one or more File Sync sources or actions"
SECRET = "fixture-only-global-secret"

# What lib/identityWorkbench.ts and lib/identityFields.ts read off a record and its credentials. The
# fixture may carry no fewer; the real routes carry exactly the keys the fixture carries.
IDENTITY_UI_KEYS = {"id", "name", "description", "usage_contexts", "credentials", "scope_type", "global_id"}
CREDENTIALS_UI_KEYS = {
    "auth_type", "username", "domain", "identity", "tenant_id", "managed_identity_client_id",
    "password_stored", "secret_stored",
}
REFERENCE_UI_KEYS = {"kind", "id", "name"}


class LegacyIdentityContainer(IdentityContainer):
    """The shared stub plus the two unconditional writes the older routes make.

    Point reads and writes answer as Cosmos does, with the installed SDK's ``CosmosDict``; query rows
    stay plain dictionaries.
    """

    @staticmethod
    def _sdk(document):
        return CosmosDict(deepcopy(document), response_headers={})

    def create_item(self, body):
        return self._sdk(super().create_item(body))

    def read_item(self, item, partition_key):
        return self._sdk(super().read_item(item, partition_key))

    def replace_item(self, item, body, etag=None, match_condition=None):
        return self._sdk(super().replace_item(item, body, etag=etag, match_condition=match_condition))

    def upsert_item(self, body):
        doc = deepcopy(body)
        doc["_etag"] = self._next_etag()
        self.records[(doc[self.scope_field], doc["id"])] = doc
        return self._sdk(doc)

    def delete_item(self, item, partition_key, etag=None, match_condition=None):
        if match_condition is not None:
            super().delete_item(item, partition_key, etag, match_condition)
            return
        if (partition_key, item) not in self.records:
            raise CosmosResourceNotFoundError()
        del self.records[(partition_key, item)]


def route_constant(name):
    """A module-level literal of the real route module, read without importing it."""
    tree = ast.parse((APP_ROOT / "route_backend_workspace_identities.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"route_backend_workspace_identities.py defines no {name}")


@pytest.fixture
def routes(environment, monkeypatch):
    env = environment
    env.global_container = LegacyIdentityContainer("global_id")
    env.personal_container = LegacyIdentityContainer("user_id")
    env.state.global_actions = []
    env.state.personal_actions = []
    monkeypatch.setattr(env.identities, "cosmos_global_workspace_identities_container", env.global_container)
    monkeypatch.setattr(env.identities, "cosmos_personal_workspace_identities_container", env.personal_container)
    monkeypatch.setitem(sys.modules, "functions_global_actions", module_stub(
        "functions_global_actions",
        get_global_actions=lambda return_type=None, include_disabled=False: list(env.state.global_actions),
    ))
    monkeypatch.setitem(sys.modules, "functions_personal_actions", module_stub(
        "functions_personal_actions", get_personal_actions=lambda user_id: list(env.state.personal_actions),
    ))

    auth = sys.modules["functions_authentication"]
    guards = {"wraps": wraps, "session": session, "request": request, "jsonify": jsonify}
    execute_functions("functions_authentication.py", {"admin_required"}, guards)
    namespace = {
        "jsonify": jsonify,
        "request": request,
        "admin_required": guards["admin_required"],
        "login_required": auth.login_required,
        "user_required": auth.user_required,
        "get_current_user_id": auth.get_current_user_id,
        "swagger_route": lambda **_kwargs: (lambda function: function),
        "get_auth_security": lambda: [{"sessionAuth": []}],
        "list_file_sync_sources": sys.modules["functions_file_sync"].list_file_sync_sources,
        "find_group_by_id": sys.modules["functions_group"].find_group_by_id,
        "assert_group_role": sys.modules["functions_group"].assert_group_role,
        "require_active_group": lambda user_id, allowed_roles=None: "group-a",
        "find_public_workspace_by_id": lambda workspace_id: None,
        "get_user_role_in_public_workspace": lambda workspace, user_id: None,
        "WORKSPACE_IDENTITY_MANAGER_ROLES": route_constant("WORKSPACE_IDENTITY_MANAGER_ROLES"),
        "IDENTITY_IN_USE_MESSAGE": route_constant("IDENTITY_IN_USE_MESSAGE"),
    }
    for name in (
        "WORKSPACE_IDENTITY_SCOPE_GLOBAL", "WORKSPACE_IDENTITY_SCOPE_GROUP",
        "WORKSPACE_IDENTITY_SCOPE_PERSONAL", "WORKSPACE_IDENTITY_SCOPE_PUBLIC",
        "create_workspace_identity", "delete_workspace_identity", "get_action_identity_reference_id",
        "list_workspace_identities", "log_workspace_identity_reference_block",
        "sanitize_workspace_identity", "update_workspace_identity",
    ):
        namespace[name] = getattr(env.identities, name)
    execute_functions(
        "route_backend_workspace_identities.py", {"register_route_backend_workspace_identities"}, namespace,
    )
    blueprint = Blueprint("backend_workspace_identities_admin_contract", __name__)
    namespace["register_route_backend_workspace_identities"](blueprint)
    env.app.register_blueprint(blueprint)
    as_user(env, "admin-user", roles=("Admin",))
    return env


def global_action(identifier="action-1", display_name="Ticket search", **fields):
    return {"id": identifier, "name": identifier, "displayName": display_name, "type": "openapi", **fields}


def create_global(env, name="Reporting API key", **fields):
    response = env.client.post(GLOBAL_PATH, json={
        "name": name,
        "description": "Used by the ticket action.",
        "provider": "action",
        "source_type": "action",
        "usage_contexts": ["action"],
        "supported_source_types": ["action"],
        "credentials": {"auth_type": "api_key", "secret": SECRET},
        **fields,
    })
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["identity"]


def test_version():
    assert_app_version_at_least("0.261.445")


def test_a_global_identity_round_trips_with_the_shape_the_v2_adapter_reads(routes):
    env = routes
    created = create_global(env)

    # The keys lib/identityWorkbench.ts and lib/identityFields.ts read off every record.
    for key in ("id", "name", "description", "usage_contexts", "credentials", "scope_type", "global_id"):
        assert key in created, key
    assert created["scope_type"] == "global" and created["global_id"] == "global"
    assert created["usage_contexts"] == ["action"]
    credentials = created["credentials"]
    for key in (
        "auth_type", "username", "domain", "identity", "tenant_id", "managed_identity_client_id",
        "password_stored", "secret_stored",
    ):
        assert key in credentials, key
    assert credentials["auth_type"] == "api_key" and credentials["secret_stored"] is True
    assert "auth" not in created and "_etag" not in created

    listing = env.client.get(GLOBAL_PATH)
    assert listing.status_code == 200
    body = listing.get_json()
    assert set(body) == {"identities"}
    assert [identity["id"] for identity in body["identities"]] == [created["id"]]

    updated = env.client.patch(f"{GLOBAL_PATH}/{created['id']}", json={
        "name": "Renamed key",
        "credentials": {"auth_type": "api_key", "secret": ""},
    })
    assert updated.status_code == 200
    record = updated.get_json()["identity"]
    assert record["name"] == "Renamed key" and record["id"] == created["id"]
    stored = env.identities.get_workspace_identity("global", "global", created["id"])
    assert stored["auth"]["secret"] == SECRET, "A blank secret on edit must keep the stored value."

    # A secret is never in any response body.
    for response in (listing, updated):
        assert SECRET not in response.get_data(as_text=True)


def test_a_missing_global_identity_is_a_404_and_a_bad_body_a_400(routes):
    env = routes
    assert env.client.patch(f"{GLOBAL_PATH}/no-such-identity", json={"name": "x"}).status_code == 404
    assert env.client.delete(f"{GLOBAL_PATH}/no-such-identity").status_code == 404
    bad = env.client.post(GLOBAL_PATH, json={
        "name": "No password", "usage_contexts": ["file_sync"],
        "credentials": {"auth_type": "username_password", "username": "svc", "password": ""},
    })
    assert bad.status_code == 400
    assert bad.get_json()["error"] == "Username/password identities require a password"


def test_a_refused_delete_is_a_409_that_names_the_global_actions_still_using_the_identity(routes):
    env = routes
    created = create_global(env)
    env.state.global_actions = [
        global_action("action-1", "Ticket search", additionalFields={"identity_id": created["id"]}),
        global_action("action-2", "Unrelated"),
        global_action("action-3", "Roadmap", identity_id=created["id"]),
    ]

    refused = env.client.delete(f"{GLOBAL_PATH}/{created['id']}")

    assert refused.status_code == 409
    body = refused.get_json()
    assert body["error"] == IN_USE_MESSAGE
    assert body["error_code"] == "identity_in_use"
    assert body["references"] == [
        {"kind": "action", "id": "action-1", "name": "Ticket search"},
        {"kind": "action", "id": "action-3", "name": "Roadmap"},
    ]
    assert ("global", created["id"]) in env.global_container.records, "A refused delete removes nothing."

    # Once nothing uses it, the same request deletes it.
    env.state.global_actions = [global_action("action-2", "Unrelated")]
    deleted = env.client.delete(f"{GLOBAL_PATH}/{created['id']}")
    assert deleted.status_code == 200
    assert ("global", created["id"]) not in env.global_container.records
    assert env.client.get(GLOBAL_PATH).get_json() == {"identities": []}


def test_the_personal_route_keeps_the_refusal_it_always_had(routes):
    env = routes
    as_user(env, "member-user")
    created = env.client.post(PERSONAL_PATH, json={
        "name": "Personal key", "usage_contexts": ["action"],
        "credentials": {"auth_type": "api_key", "secret": SECRET},
    })
    assert created.status_code == 201, created.get_data(as_text=True)
    identity_id = created.get_json()["identity"]["id"]
    env.state.personal_actions = [global_action("action-9", "Mine", identity_id=identity_id)]

    refused = env.client.delete(f"{PERSONAL_PATH}/{identity_id}")

    # The classic personal editor shows the sentence; nothing about the status or body changed.
    assert refused.status_code == 400
    assert refused.get_json() == {"error": IN_USE_MESSAGE}
    assert ("member-user", identity_id) in env.personal_container.records


@pytest.mark.parametrize("roles", [("User",), ()])
def test_only_an_administrator_can_read_or_change_global_identities(routes, roles):
    env = routes
    created = create_global(env)
    before = deepcopy(env.global_container.records)
    as_user(env, "member-user", roles=roles)

    responses = [
        env.client.get(GLOBAL_PATH),
        env.client.post(GLOBAL_PATH, json={"name": "Sneaky"}),
        env.client.patch(f"{GLOBAL_PATH}/{created['id']}", json={"name": "Sneaky"}),
        env.client.delete(f"{GLOBAL_PATH}/{created['id']}"),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
    assert env.global_container.records == before


# --------------------------------------------------------------------------
# The browser fixture answers what the real routes answer
# --------------------------------------------------------------------------

class _FakePage:
    """The two calls a fixture makes on its page while it is built."""

    def on(self, *args, **kwargs):
        pass

    def route(self, *args, **kwargs):
        pass


@pytest.fixture
def ui_fixture():
    """The V2 browser fixture, built on a stand-in page so only its request logic runs.

    A test lists this fixture before ``routes``: building the fixture imports application modules
    for its schema, which has to happen before the harness stubs ``config`` and ``azure``.
    """
    return GlobalIdentitiesFixture(_FakePage())


def assert_same_record_shape(real, fixture, label):
    """The fixture carries exactly the keys the server does, and the keys the UI reads are among them."""
    assert IDENTITY_UI_KEYS <= set(fixture), f"{label}: the fixture drops {sorted(IDENTITY_UI_KEYS - set(fixture))}"
    assert set(fixture) == set(real), (
        f"{label}: fixture keys differ from the server's: "
        f"fixture only {sorted(set(fixture) - set(real))}, server only {sorted(set(real) - set(fixture))}"
    )
    assert CREDENTIALS_UI_KEYS <= set(fixture["credentials"])
    assert set(fixture["credentials"]) == set(real["credentials"]), f"{label}: credentials keys differ"
    assert fixture["scope_type"] == real["scope_type"] == "global"
    assert fixture["global_id"] == real["global_id"] == "global"
    assert "etag" not in fixture and "identity_actions" not in fixture, (
        f"{label}: the server sends neither, so the fixture must not"
    )


def test_the_fixture_answers_a_list_a_create_and_an_update_with_the_servers_shape(ui_fixture, routes):
    env = routes
    ui = ui_fixture
    body = {
        "name": "Reporting API key", "description": "Used by the reporting action.",
        "provider": "action", "source_type": "action", "usage_contexts": ["action"],
        "supported_source_types": ["action"],
        "credentials": {
            "auth_type": "api_key", "username": "", "domain": "", "identity": "", "client_id": "",
            "secret": SECRET,
        },
    }

    real_created = env.client.post(GLOBAL_PATH, json=body)
    fixture_status, fixture_created = ui.handle_identity_request("POST", GLOBAL_PATH, deepcopy(body))
    assert real_created.status_code == fixture_status == 201
    assert set(real_created.get_json()) == set(fixture_created) == {"identity"}
    assert_same_record_shape(real_created.get_json()["identity"], fixture_created["identity"], "create")

    real_list = env.client.get(GLOBAL_PATH)
    fixture_status, fixture_list = ui.handle_identity_request("GET", GLOBAL_PATH)
    assert real_list.status_code == fixture_status == 200
    assert set(real_list.get_json()) == set(fixture_list) == {"identities"}
    real_item = real_list.get_json()["identities"][0]
    for fixture_item in fixture_list["identities"]:
        assert_same_record_shape(real_item, fixture_item, "list")

    update = {"name": "Renamed key", "credentials": {"auth_type": "api_key", "secret": ""}}
    real_id = real_created.get_json()["identity"]["id"]
    fixture_id = fixture_created["identity"]["id"]
    real_updated = env.client.patch(f"{GLOBAL_PATH}/{real_id}", json=update)
    fixture_status, fixture_updated = ui.handle_identity_request("PATCH", f"{GLOBAL_PATH}/{fixture_id}", deepcopy(update))
    assert real_updated.status_code == fixture_status == 200
    assert set(real_updated.get_json()) == set(fixture_updated) == {"identity"}
    assert_same_record_shape(real_updated.get_json()["identity"], fixture_updated["identity"], "update")
    # Both keep the stored secret masked with the flag set after a blank-secret edit.
    for credentials in (real_updated.get_json()["identity"]["credentials"], fixture_updated["identity"]["credentials"]):
        assert credentials["secret_stored"] is True and credentials["secret"] == "Stored_In_KeyVault"


def test_the_fixture_gives_the_servers_statuses_and_bodies_for_every_refusal(ui_fixture, routes):
    env = routes
    ui = ui_fixture
    no_password = {
        "name": "No password", "usage_contexts": ["file_sync"],
        "credentials": {"auth_type": "username_password", "username": "svc", "password": ""},
    }

    real = env.client.post(GLOBAL_PATH, json=no_password)
    status, body = ui.handle_identity_request("POST", GLOBAL_PATH, deepcopy(no_password))
    assert (real.status_code, real.get_json()) == (status, body) == (400, {"error": "Username/password identities require a password"})

    no_secret = {"name": "No secret", "usage_contexts": ["action"], "credentials": {"auth_type": "api_key", "secret": ""}}
    real = env.client.post(GLOBAL_PATH, json=no_secret)
    status, body = ui.handle_identity_request("POST", GLOBAL_PATH, deepcopy(no_secret))
    assert (real.status_code, real.get_json()) == (status, body) == (400, {"error": "This identity type requires a secret value"})

    missing = f"{GLOBAL_PATH}/no-such-identity"
    for method, payload in (("PATCH", {"name": "x"}), ("DELETE", None)):
        real = getattr(env.client, method.lower())(missing, **({} if payload is None else {"json": payload}))
        status, body = ui.handle_identity_request(method, missing, payload)
        assert (real.status_code, real.get_json()) == (status, body) == (404, {"error": "Workspace identity not found"})

    ui.admin = False
    as_user(env, "member-user", roles=("User",))
    for method, path, payload in (
        ("GET", GLOBAL_PATH, None), ("POST", GLOBAL_PATH, {"name": "x"}),
        ("PATCH", f"{GLOBAL_PATH}/any", {"name": "x"}), ("DELETE", f"{GLOBAL_PATH}/any", None),
    ):
        real = getattr(env.client, method.lower())(path, **({} if payload is None else {"json": payload}))
        status, body = ui.handle_identity_request(method, path, payload)
        assert (real.status_code, real.get_json()) == (status, body) == (403, {
            "error": "Forbidden", "message": "Insufficient permissions (Admin role required)",
        })


def test_the_fixture_refuses_a_delete_the_way_the_server_does(ui_fixture, routes):
    env = routes
    ui = ui_fixture
    created = create_global(env)
    env.state.global_actions = [global_action("ticket_search", "Ticket search", identity_id=created["id"])]
    real = env.client.delete(f"{GLOBAL_PATH}/{created['id']}")

    ui.references = {"fixture-identity": [{"kind": "action", "id": "ticket_search", "name": "Ticket search"}]}
    ui.identities[0]["id"] = "fixture-identity"
    status, body = ui.handle_identity_request("DELETE", f"{GLOBAL_PATH}/fixture-identity")

    assert real.status_code == status == 409
    assert real.get_json() == body
    assert body["error_code"] == "identity_in_use" and body["error"] == IN_USE_MESSAGE
    for reference in body["references"]:
        assert set(reference) == REFERENCE_UI_KEYS

    # And, once nothing uses it, the same delete has the same answer.
    env.state.global_actions = []
    ui.references = {}
    real = env.client.delete(f"{GLOBAL_PATH}/{created['id']}")
    status, body = ui.handle_identity_request("DELETE", f"{GLOBAL_PATH}/fixture-identity")
    assert real.status_code == status == 200
    assert set(real.get_json()) == set(body) == {"message", "delete_result"}
    assert set(real.get_json()["delete_result"]) == set(body["delete_result"]) == {"identity_id", "deleted_by"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
