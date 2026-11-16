# test_group_endpoint_discovery_scope.py
"""
Functional test for named-group model discovery, model tests and Foundry discovery.
Version: 0.261.140
Implemented in: 0.261.140

M5C §2.1. The legacy group discovery and test handlers resolve the account's
*active* group deep inside ``route_backend_models`` (``resolve_scoped_model_endpoints``
calls ``require_active_group``). The native routes
``/api/groups/<group_id>/models/{fetch,test-model,foundry/agents}`` authorize the path
group first and thread its ``group_id`` through those closures, so another tab
changing the active group can never retarget them.

The real ``route_backend_models`` module is loaded unchanged
(``test_support/group_endpoint_harness.py``); the active-group lookup is a recording
fake, and the Foundry credential, the HTTP client, the chat client and the Foundry
listing are recording fakes, so each test can see exactly which stored endpoint,
URL and credential a request reached.

Pinned:

- the native routes resolve only the path group and never call
  ``require_active_group``;
- with an ``endpoint_id``, the named group's stored configuration is used and the
  request's URL and credential are ignored;
- the write roles in an ``active`` group, and the availability predicate, gate all
  three routes;
- the legacy routes still resolve the active group;
- the legacy Foundry route's output is unchanged: its auth-required body equals
  today's ``str(exc)`` body, and its governance 403 still returns ``str(exc)``,
  while the native route answers with stable messages.
"""

import pytest

from test_support.group_endpoint_harness import (
    GROUP_A,
    GROUP_B,
    NON_WRITER_ROLES,
    ROLE_USERS,
    WRITER_ROLES,
    aoai_endpoint,
    foundry_endpoint,
    group_endpoint_environment,
)


FOUNDRY_A_URL = "https://group-a.services.ai.azure.com/api/projects/proj"
FOUNDRY_B_URL = "https://group-b.services.ai.azure.com/api/projects/proj"
AOAI_A_URL = "https://group-a.openai.azure.com"
AOAI_B_URL = "https://group-b.openai.azure.com"
ATTACKER_URL = "https://attacker.services.ai.azure.com/api/projects/proj"


def native(group_id, operation):
    return f"/api/groups/{group_id}/models/{operation}"


@pytest.fixture(scope="module")
def module_env():
    with group_endpoint_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.seed_group_with_legacy_endpoints(GROUP_A, [
        foundry_endpoint("fa", url=FOUNDRY_A_URL, secret="sp-a"),
        aoai_endpoint("aa", url=AOAI_A_URL, api_key="sk-a"),
    ])
    module_env.seed_group_with_legacy_endpoints(GROUP_B, [
        foundry_endpoint("fb", url=FOUNDRY_B_URL, secret="sp-b"),
        aoai_endpoint("ab", url=AOAI_B_URL, api_key="sk-b"),
    ])
    module_env.active_group = GROUP_A
    module_env.vault.reads.clear()
    yield module_env
    module_env.reset()


def post(env, path, body):
    return env.call("POST", path, body)


def delegated_auth_failure(env):
    try:
        env.raise_delegated_auth_required("https://ai.azure.com/.default")
    except env.FoundryAgentUserAuthenticationRequired as exc:
        return exc
    raise AssertionError("the real delegated-auth helper did not raise")


# --------------------------------------------------------------------------
# The path group, never the active group
# --------------------------------------------------------------------------

def test_native_fetch_resolves_the_path_group_from_its_stored_configuration(env):
    response = post(env, native(GROUP_B, "fetch"), {
        "endpoint_id": "fb",
        "connection": {"endpoint": ATTACKER_URL},
        "auth": {"type": "service_principal", "client_secret": "attacker-secret"},
    })
    assert response.status_code == 200, response.get_json()
    assert [model["deploymentName"] for model in response.get_json()["models"]] == ["gpt-4o"]
    assert [call["url"] for call in env.http_calls] == [f"{FOUNDRY_B_URL}/deployments"]
    assert [credential["auth"]["client_secret"] for credential in env.credentials] == ["sp-b"]
    assert env.vault.reads == ["fb--model-endpoint--group--model-endpoint-client-secret"]
    env.require_active_group.assert_not_called()


def test_native_test_model_resolves_the_path_group_from_its_stored_configuration(env):
    response = post(env, native(GROUP_B, "test-model"), {
        "endpoint_id": "ab",
        "model": {"id": "chat"},
        "connection": {"endpoint": "https://attacker.openai.azure.com"},
        "auth": {"type": "api_key", "api_key": "attacker-key"},
    })
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["success"] is True
    [client] = env.chat_clients
    assert client["endpoint"] == AOAI_B_URL
    assert client["auth"]["api_key"] == "sk-b"
    assert client["deployment_name"] == "gpt-4o"
    env.require_active_group.assert_not_called()


def test_native_foundry_discovery_resolves_the_path_group(env):
    response = post(env, native(GROUP_B, "foundry/agents"), {"endpoint_id": "fb"})
    assert response.status_code == 200, response.get_json()
    assert response.get_json() == {
        "agents": [{"id": "agents-1", "name": "agents one"}],
        "provider": "aifoundry",
        "responses_api_version": "",
    }
    [call] = env.foundry_calls
    assert call["settings"]["endpoint"] == FOUNDRY_B_URL
    assert call["settings"]["client_secret"] == "sp-b"
    env.require_active_group.assert_not_called()


@pytest.mark.parametrize("operation,body", [
    ("fetch", {"endpoint_id": "fa"}),
    ("test-model", {"endpoint_id": "aa", "model": {"id": "chat"}}),
    ("foundry/agents", {"endpoint_id": "fa"}),
])
def test_another_groups_endpoint_is_not_found_through_the_path_group(env, operation, body):
    response = post(env, native(GROUP_B, operation), body)
    assert response.status_code == 404
    assert env.credentials == [] and env.chat_clients == [] and env.foundry_calls == []
    assert env.vault.reads == []


def test_path_authority_ignores_where_the_caller_manages_the_active_group(env):
    # ``admin`` manages group A (active) but is only a member of group B.
    record = env.stored_group(GROUP_B)
    record["admins"] = []
    env.groups.seed(record)
    env.as_user("admin")
    refused = post(env, native(GROUP_B, "fetch"), {"endpoint_id": "fb"})
    assert refused.status_code == 403
    assert env.credentials == [] and env.vault.reads == []
    allowed = post(env, native(GROUP_A, "fetch"), {"endpoint_id": "fa"})
    assert allowed.status_code == 200


def test_transient_discovery_uses_only_the_request_fields(env):
    response = post(env, native(GROUP_B, "fetch"), {
        "provider": "aifoundry",
        "connection": {"endpoint": FOUNDRY_B_URL, "project_api_version": "v1"},
        "auth": {"type": "service_principal", "tenant_id": "t", "client_id": "c", "client_secret": "draft-secret"},
    })
    assert response.status_code == 200, response.get_json()
    assert [credential["auth"]["client_secret"] for credential in env.credentials] == ["draft-secret"]
    assert env.vault.reads == []
    env.require_active_group.assert_not_called()


# --------------------------------------------------------------------------
# Roles, statuses, availability and strict requests
# --------------------------------------------------------------------------

OPERATIONS = [
    ("fetch", {"endpoint_id": "fb"}),
    ("test-model", {"endpoint_id": "ab", "model": {"id": "chat"}}),
    ("foundry/agents", {"endpoint_id": "fb"}),
]


@pytest.mark.parametrize("operation,body", OPERATIONS)
@pytest.mark.parametrize("role", WRITER_ROLES)
def test_writers_can_discover_and_test(env, operation, body, role):
    env.as_user(ROLE_USERS[role])
    assert post(env, native(GROUP_B, operation), body).status_code == 200


@pytest.mark.parametrize("operation,body", OPERATIONS)
@pytest.mark.parametrize("role", NON_WRITER_ROLES)
def test_readers_cannot_load_stored_credentials(env, operation, body, role):
    env.as_user(ROLE_USERS[role])
    response = post(env, native(GROUP_B, operation), body)
    assert response.status_code == 403
    assert response.get_json() == {"error": "You do not have permission to manage this group's model endpoints."}
    assert env.vault.reads == [] and env.credentials == [] and env.foundry_calls == []


@pytest.mark.parametrize("operation,body", OPERATIONS)
@pytest.mark.parametrize("status", ["locked", "upload_disabled", "inactive"])
def test_discovery_needs_an_active_group(env, operation, body, status):
    record = env.stored_group(GROUP_B)
    record["status"] = status
    env.groups.seed(record)
    response = post(env, native(GROUP_B, operation), body)
    assert response.status_code == 403
    assert env.vault.reads == []


@pytest.mark.parametrize("user_id,group_id,status", [("outsider", GROUP_B, 403), ("owner", "missing", 404)])
def test_discovery_refuses_outsiders_and_missing_groups(env, user_id, group_id, status):
    env.as_user(user_id)
    for operation, body in OPERATIONS:
        assert post(env, native(group_id, operation), body).status_code == status


@pytest.mark.parametrize("flag", [
    "enable_semantic_kernel", "per_user_semantic_kernel",
    "allow_group_custom_endpoints", "enable_multi_model_endpoints",
])
def test_discovery_follows_the_availability_predicate(env, flag):
    env.settings[flag] = False
    for operation, body in OPERATIONS:
        response = post(env, native(GROUP_B, operation), body)
        assert response.status_code == 403
        assert response.get_json() == {"error": "Group model endpoints are not enabled."}


def test_discovery_sits_behind_the_group_workspaces_flag(env):
    env.settings["enable_group_workspaces"] = False
    for operation, body in OPERATIONS:
        assert post(env, native(GROUP_B, operation), body).status_code == 400


@pytest.mark.parametrize("operation,body", OPERATIONS)
def test_discovery_requests_are_strict(env, operation, body):
    query = env.call("POST", native(GROUP_B, operation), body, query_string={"group_id": GROUP_A})
    assert query.status_code == 400
    duplicate = env.call("POST", native(GROUP_B, operation), raw='{"endpoint_id": "fb", "endpoint_id": "fa"}')
    assert duplicate.status_code == 400
    assert duplicate.get_json() == {"error": "Duplicate fields are not supported."}
    array = env.call("POST", native(GROUP_B, operation), raw="[]")
    assert array.status_code == 400
    assert env.vault.reads == []


def test_foundry_discovery_needs_a_foundry_endpoint_id(env):
    missing = post(env, native(GROUP_B, "foundry/agents"), {})
    assert missing.status_code == 400
    assert missing.get_json() == {"error": "endpoint_id is required."}
    not_foundry = post(env, native(GROUP_B, "foundry/agents"), {"endpoint_id": "ab"})
    assert not_foundry.status_code == 400
    assert not_foundry.get_json() == {"error": "Selected endpoint is not a Foundry endpoint."}


# --------------------------------------------------------------------------
# Legacy routes are unchanged
# --------------------------------------------------------------------------

def test_the_legacy_group_fetch_still_resolves_the_active_group(env):
    response = post(env, "/api/group/models/fetch", {"endpoint_id": "fa"})
    assert response.status_code == 200
    assert [call["url"] for call in env.http_calls] == [f"{FOUNDRY_A_URL}/deployments"]
    assert env.require_active_group.call_count == 2
    # The active group's endpoints are the only group endpoints it can reach.
    assert post(env, "/api/group/models/fetch", {"endpoint_id": "fb"}).status_code == 404


def test_the_legacy_group_test_model_still_resolves_the_active_group(env):
    response = post(env, "/api/group/models/test-model", {"endpoint_id": "aa", "model": {"id": "chat"}})
    assert response.status_code == 200
    assert [client["endpoint"] for client in env.chat_clients] == [AOAI_A_URL]
    assert env.require_active_group.call_count == 2


def test_the_legacy_foundry_route_still_resolves_the_active_group(env):
    response = post(env, "/api/models/foundry/agents", {"endpoint_id": "fa", "scope": "group"})
    assert response.status_code == 200
    assert env.foundry_calls[0]["settings"]["endpoint"] == FOUNDRY_A_URL
    assert env.require_active_group.call_count == 2


def test_the_legacy_foundry_auth_required_body_is_unchanged(env):
    failure = delegated_auth_failure(env)
    env.foundry_failure = failure
    response = post(env, "/api/models/foundry/agents", {"endpoint_id": "fa", "scope": "group"})
    assert response.status_code == 401
    # Today's body: ``{"error": str(exc), "auth_required": True, "scopes": ..., urls}``.
    assert response.get_json() == {
        "error": str(failure),
        "auth_required": True,
        "scopes": ["https://ai.azure.com/.default"],
        "consent_url": "https://login.example.test/consent",
        "auth_url": "https://login.example.test/consent",
    }
    assert str(failure) == env.FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE


def test_the_legacy_foundry_governance_refusal_still_returns_the_exception_text(env):
    env.recheck_denials.add("fa")
    response = post(env, "/api/models/foundry/agents", {"endpoint_id": "fa", "scope": "group"})
    assert response.status_code == 403
    assert response.get_json() == {"error": "Governance policy blocks access to global_endpoint 'fa'."}


def test_the_native_foundry_route_answers_with_stable_messages(env):
    env.recheck_denials.add("fb")
    refused = post(env, native(GROUP_B, "foundry/agents"), {"endpoint_id": "fb"})
    assert refused.status_code == 403
    assert refused.get_json() == {"error": "You do not have access to this model connection."}
    env.recheck_denials.clear()
    env.governance_calls.clear()
    env.foundry_failure = delegated_auth_failure(env)
    auth_required = post(env, native(GROUP_B, "foundry/agents"), {"endpoint_id": "fb"})
    assert auth_required.status_code == 401
    body = auth_required.get_json()
    assert body["error"] == env.FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE
    assert body["auth_required"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
