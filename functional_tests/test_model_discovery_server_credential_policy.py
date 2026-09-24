# test_model_discovery_server_credential_policy.py
"""
Functional test for the application identity on transient model discovery and tests.
Version: 0.261.140
Implemented in: 0.261.140

M5C §8. A fetch or test-model request with no ``endpoint_id`` supplies its own
connection and authentication. Unless it carries the caller's own API key or
service principal, the discovery and test clients fall back to the application's
own identity (``DefaultAzureCredential``). Before this change the destination came
from the request with no host allowlist, and the token audience and authority could
be steered by ``auth.foundry_scope``, ``auth.custom_authority`` and a ``custom``
``management_cloud``.

For the personal (``user``) and group scopes only, on the legacy
``/api/user/models/*`` and ``/api/group/models/*`` routes and the native
``/api/groups/<group_id>/models/*`` routes, this pins that:

- a request-supplied audience, authority or custom cloud is refused, and otherwise
  the server's own values are used;
- the application identity reaches only an Azure AI host of the configured cloud
  (``AZURE_AI_ENDPOINT_SUFFIXES``); anything else is a stable 400;
- a caller's own key or service principal, and custom connections, are unaffected;
- the admin (global) routes and saved-endpoint requests are unchanged;
- Foundry discovery has no transient path at all.

The real ``route_backend_models`` runs unchanged (``test_support/group_endpoint_harness.py``);
the credential factory, HTTP client and chat client are recording fakes, so each test
sees whether a token was requested, for which audience, and where it would be sent.
"""

import importlib.util

import pytest

from test_support.agent_delegation import APP_ROOT
from test_support.group_endpoint_harness import (
    GROUP_A,
    GROUP_B,
    aoai_endpoint,
    group_endpoint_environment,
)


AZURE_FOUNDRY_URL = "https://contoso.services.ai.azure.com/api/projects/proj"
AZURE_OPENAI_URL = "https://contoso.openai.azure.com"
ATTACKER_URL = "https://attacker.example.com/api/projects/proj"
PUBLIC_FOUNDRY_SCOPE = "https://ai.azure.com/.default"

FETCH_ROUTES = ("/api/user/models/fetch", "/api/group/models/fetch", f"/api/groups/{GROUP_B}/models/fetch")
TEST_ROUTES = ("/api/user/models/test-model", "/api/group/models/test-model", f"/api/groups/{GROUP_B}/models/test-model")
ENDPOINT_REFUSED = {
    "error": (
        "The application identity can be used only with an Azure AI endpoint in this cloud. "
        "Use an API key or a service principal for other endpoints."
    ),
    "code": "server_credential_endpoint_refused",
}
OVERRIDE_REFUSED = {
    "error": (
        "The application identity uses this deployment's own token audience and authority. "
        "Remove the Foundry scope, custom authority and custom cloud, or use an API key or a service principal."
    ),
    "code": "server_credential_override_refused",
}


def foundry_draft(url=AZURE_FOUNDRY_URL, **auth):
    return {
        "provider": "aifoundry",
        "connection": {"endpoint": url, "project_api_version": "v1"},
        "auth": {"type": "managed_identity", **auth},
    }


def openai_draft(url=AZURE_OPENAI_URL, **auth):
    return {
        "provider": "aoai",
        "connection": {"endpoint": url, "openai_api_version": "2024-10-21"},
        "auth": {"type": "managed_identity", **auth},
        "models": [{"id": "chat", "deploymentName": "gpt-4o", "modelName": "gpt-4o"}],
        "model": {"id": "chat", "deploymentName": "gpt-4o", "modelName": "gpt-4o"},
    }


@pytest.fixture(scope="module")
def module_env():
    with group_endpoint_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.seed_group(GROUP_A)
    module_env.seed_group(GROUP_B)
    module_env.active_group = GROUP_A
    yield module_env
    module_env.reset()


def assert_no_application_token(env):
    assert env.credentials == [], "an application-identity credential was built"
    assert env.http_calls == [] and env.chat_clients == []


# --------------------------------------------------------------------------
# The allowlist itself
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def validation():
    spec = importlib.util.spec_from_file_location(
        "tested_azure_endpoint_validation", APP_ROOT / "functions_azure_endpoint_validation.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("cloud,url,host", [
    ("public", "https://contoso.openai.azure.com", "contoso.openai.azure.com"),
    ("public", "https://contoso.services.ai.azure.com/api/projects/p", "contoso.services.ai.azure.com"),
    ("public", "https://contoso.cognitiveservices.azure.com/", "contoso.cognitiveservices.azure.com"),
    ("public", "https://eastus.api.cognitive.microsoft.com:443", "eastus.api.cognitive.microsoft.com"),
    ("government", "https://contoso.openai.azure.us", "contoso.openai.azure.us"),
    ("government", "https://contoso.services.ai.azure.us/api/projects/p", "contoso.services.ai.azure.us"),
])
def test_azure_ai_hosts_of_the_configured_cloud_are_allowed(validation, cloud, url, host):
    assert validation.validate_azure_ai_endpoint_host(url, cloud) == host


@pytest.mark.parametrize("cloud,url", [
    ("public", "https://attacker.example.com"),
    ("public", "https://openai.azure.com"),
    ("public", "https://contoso.openai.azure.com.attacker.example"),
    ("public", "http://contoso.openai.azure.com"),
    ("public", "https://contoso.openai.azure.com:8443"),
    ("public", "https://user:pass@contoso.openai.azure.com"),
    ("public", "https://contoso.openai.azure.com/?redirect=x"),
    ("public", "https://127.0.0.1"),
    ("public", "https://localhost"),
    ("public", "https://contoso.openai.azure.us"),
    ("government", "https://contoso.openai.azure.com"),
    ("custom", "https://contoso.openai.azure.com"),
    ("public", ""),
])
def test_anything_else_is_refused(validation, cloud, url):
    with pytest.raises(ValueError):
        validation.validate_azure_ai_endpoint_host(url, cloud)


# --------------------------------------------------------------------------
# Refused transient requests (personal, legacy group and native group)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", FETCH_ROUTES)
def test_a_non_azure_host_never_receives_the_application_identity_on_fetch(env, path):
    response = env.call("POST", path, foundry_draft(ATTACKER_URL))
    assert response.status_code == 400
    assert response.get_json() == ENDPOINT_REFUSED
    assert_no_application_token(env)


@pytest.mark.parametrize("path", TEST_ROUTES)
def test_a_non_azure_host_never_receives_the_application_identity_on_test_model(env, path):
    response = env.call("POST", path, openai_draft("https://attacker.example.com"))
    assert response.status_code == 400
    assert response.get_json() == ENDPOINT_REFUSED
    assert_no_application_token(env)


@pytest.mark.parametrize("path", FETCH_ROUTES + TEST_ROUTES)
def test_an_absent_auth_type_is_the_application_identity(env, path):
    draft = foundry_draft(ATTACKER_URL) if path in FETCH_ROUTES else openai_draft("https://attacker.example.com")
    draft["auth"] = {}
    response = env.call("POST", path, draft)
    assert response.status_code == 400
    assert response.get_json()["code"] == "server_credential_endpoint_refused"
    assert_no_application_token(env)


@pytest.mark.parametrize("override", [
    {"foundry_scope": "https://management.azure.com/.default"},
    {"custom_authority": "https://login.attacker.example.com"},
    {"management_cloud": "custom"},
])
@pytest.mark.parametrize("path", FETCH_ROUTES + TEST_ROUTES)
def test_a_request_supplied_audience_or_authority_is_refused(env, path, override):
    draft = foundry_draft(**override) if path in FETCH_ROUTES else openai_draft(**override)
    response = env.call("POST", path, draft)
    assert response.status_code == 400
    assert response.get_json() == OVERRIDE_REFUSED
    assert_no_application_token(env)


# --------------------------------------------------------------------------
# Allowed transient requests use the server's own values
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", FETCH_ROUTES)
def test_an_azure_ai_host_is_allowed_with_the_servers_audience(env, path):
    response = env.call("POST", path, foundry_draft(management_cloud="government"))
    assert response.status_code == 200, response.get_json()
    [credential] = env.credentials
    assert credential["scope"] == PUBLIC_FOUNDRY_SCOPE
    assert credential["auth"]["management_cloud"] == "public"
    assert "foundry_scope" not in credential["auth"] and "custom_authority" not in credential["auth"]
    assert [call["url"] for call in env.http_calls] == [f"{AZURE_FOUNDRY_URL}/deployments"]


def test_a_request_audience_equal_to_the_servers_own_is_accepted(env):
    response = env.call("POST", FETCH_ROUTES[0], foundry_draft(foundry_scope=PUBLIC_FOUNDRY_SCOPE))
    assert response.status_code == 200, response.get_json()
    assert env.credentials[0]["scope"] == PUBLIC_FOUNDRY_SCOPE


@pytest.mark.parametrize("path", TEST_ROUTES)
def test_an_azure_openai_host_is_allowed_on_test_model(env, path):
    response = env.call("POST", path, openai_draft())
    assert response.status_code == 200, response.get_json()
    [client] = env.chat_clients
    assert client["endpoint"] == AZURE_OPENAI_URL
    assert client["auth"]["management_cloud"] == "public"


def test_a_government_deployment_allows_only_government_hosts(env, monkeypatch):
    monkeypatch.setattr(env.modules.models, "get_model_endpoint_management_cloud_for_environment", lambda: "government")
    refused = env.call("POST", FETCH_ROUTES[2], foundry_draft())
    assert refused.status_code == 400 and refused.get_json() == ENDPOINT_REFUSED
    allowed = env.call("POST", FETCH_ROUTES[2], foundry_draft("https://contoso.services.ai.azure.us/api/projects/proj"))
    assert allowed.status_code == 200, allowed.get_json()
    assert env.credentials[0]["scope"] == "https://ai.azure.us/.default"
    assert env.credentials[0]["auth"]["management_cloud"] == "government"


# --------------------------------------------------------------------------
# Unaffected: caller credentials, custom connections, admin and stored endpoints
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", FETCH_ROUTES)
def test_a_callers_own_service_principal_is_unaffected(env, path):
    draft = foundry_draft(ATTACKER_URL)
    draft["auth"] = {
        "type": "service_principal", "tenant_id": "t", "client_id": "c", "client_secret": "caller-secret",
        "foundry_scope": "https://caller.example.com/.default",
    }
    response = env.call("POST", path, draft)
    assert response.status_code == 200, response.get_json()
    assert env.credentials[0]["auth"]["client_secret"] == "caller-secret"
    assert env.credentials[0]["scope"] == "https://caller.example.com/.default"


@pytest.mark.parametrize("path", TEST_ROUTES)
def test_a_callers_own_api_key_is_unaffected(env, path):
    draft = openai_draft("https://gateway.example.com")
    draft["auth"] = {"type": "api_key", "api_key": "caller-key"}
    response = env.call("POST", path, draft)
    assert response.status_code == 200, response.get_json()
    assert env.chat_clients[0]["endpoint"] == "https://gateway.example.com"
    assert env.chat_clients[0]["auth"]["api_key"] == "caller-key"


def test_custom_connections_are_unaffected(env):
    # The harness infers the Azure OpenAI wire protocol for every client, so the
    # custom draft carries an API version; the policy itself never inspects it.
    response = env.call("POST", TEST_ROUTES[0], {
        "provider": "custom", "api_type": "openai", "name": "Gateway",
        "connection": {"endpoint": "https://gateway.example.com/v1", "api_version": "2024-10-21"},
        "auth": {"type": "api_key", "api_key": "caller-key", "foundry_scope": "https://caller.example.com/.default"},
        "models": [{"id": "m", "modelName": "model-a"}],
        "model": {"id": "m", "modelName": "model-a"},
    })
    assert response.status_code == 200, response.get_json()
    assert env.chat_clients[0]["endpoint"] == "https://gateway.example.com/v1"
    assert env.chat_clients[0]["auth"]["api_key"] == "caller-key"


def test_the_admin_routes_are_unchanged(env):
    env.as_user("owner", roles=("User", "Admin"))
    fetched = env.call("POST", "/api/models/fetch", foundry_draft(ATTACKER_URL, foundry_scope="https://management.azure.com/.default"))
    assert fetched.status_code == 200, fetched.get_json()
    assert env.credentials[0]["scope"] == "https://management.azure.com/.default"
    assert env.http_calls[0]["url"] == f"{ATTACKER_URL}/deployments"
    tested = env.call("POST", "/api/models/test-model", openai_draft("https://attacker.example.com"))
    assert tested.status_code == 200, tested.get_json()


@pytest.mark.parametrize("path", [
    "/api/group/models/test-model", f"/api/groups/{GROUP_A}/models/test-model",
])
def test_saved_endpoints_keep_todays_behaviour(env, path):
    """Stored configuration is out of scope here (reported separately), and unchanged."""
    stored = env.legacy_stored_endpoints(GROUP_A, [aoai_endpoint(
        "saved-mi", url="https://attacker.example.com", auth={"type": "managed_identity"},
    )])
    env.seed_group(GROUP_A, endpoints=stored)
    response = env.call("POST", path, {"endpoint_id": "saved-mi", "model": {"id": "chat"}})
    assert response.status_code == 200, response.get_json()
    assert env.chat_clients[0]["endpoint"] == "https://attacker.example.com"


@pytest.mark.parametrize("path", ["/api/models/foundry/agents", f"/api/groups/{GROUP_B}/models/foundry/agents"])
def test_foundry_discovery_has_no_transient_path(env, path):
    response = env.call("POST", path, {**foundry_draft(ATTACKER_URL), "scope": "group"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "endpoint_id is required."}
    assert env.foundry_calls == [] and env.credentials == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
