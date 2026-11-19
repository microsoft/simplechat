# test_foundry_project_request_boundary.py
"""
Functional tests for the Foundry project discovery boundary (CodeQL alert 1092).
Version: 0.261.457
Implemented in: 0.261.457

The shared group endpoint harness runs real routes, settings and identity policy.
Requests prepares the recorded outbound URL without sending it, demonstrating
project confinement and refusal before tokens while preserving administrator
destinations, caller credentials and endpoint-resolution precedence.
"""

import json
import re
from unittest.mock import Mock
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit

import pytest
import requests

from test_support.app_source import run_definitions
from test_support.group_endpoint_harness import (
    GROUP_A,
    foundry_endpoint,
    group_endpoint_environment,
)


PROJECT_ENDPOINT = "https://resource.services.ai.azure.com/api/projects/project"
SAFE_ERROR = {"error": "Unable to fetch models. Review the endpoint configuration and try again."}


@pytest.fixture
def project_base():
    namespace = run_definitions("foundry_agent_runtime.py", {"resolve_foundry_project_base"}, {
        "quote": quote, "unquote": unquote, "urlsplit": urlsplit,
        "urlunsplit": urlunsplit, "re": re,
    })
    return namespace["resolve_foundry_project_base"]


@pytest.fixture(scope="module")
def module_env():
    with group_endpoint_environment() as environment:
        yield environment


@pytest.fixture
def env(module_env, monkeypatch):
    module_env.reset()
    module_env.seed_group(GROUP_A)
    credential_factory = Mock(wraps=module_env.modules.models.build_project_credential)
    monkeypatch.setattr(module_env.modules.models, "build_project_credential", credential_factory)
    monkeypatch.setattr(module_env, "credential_factory", credential_factory, raising=False)
    monkeypatch.setattr(module_env, "prepared_requests", [], raising=False)

    def send(session, prepared, **kwargs):
        module_env.prepared_requests.append(prepared)
        module_env.http_calls.append({
            "url": prepared.url, "headers": dict(prepared.headers), "timeout": kwargs["timeout"],
        })
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({
            "value": [{"name": "gpt-4o", "modelName": "gpt-4o", "modelVersion": "2024-08-06"}],
        }).encode("utf-8")
        response.request = prepared
        response.headers["Content-Type"] = "application/json"
        return response

    monkeypatch.setattr(module_env.modules.models, "requests", requests)
    monkeypatch.setattr(requests.Session, "send", send)
    yield module_env
    module_env.reset()


def prepared_discovery_call(env):
    [prepared] = env.prepared_requests
    [call] = env.http_calls
    assert call["timeout"] == 30
    assert prepared.method == "GET"
    return prepared


@pytest.mark.parametrize("project_name", [
    "project", "project name", "project.with-dots", "project_\u00e9", "project%20literal",
    "../other?api-version=evil#fragment", "project/../../other",
])
def test_project_names_cannot_change_the_prepared_discovery_path(project_base, project_name):
    base = project_base("https://resource.services.ai.azure.com", project_name)
    prepared = requests.Request("GET", f"{base}/deployments", params={
        "api-version": "v1", "deploymentType": "ModelDeployment",
    }).prepare()
    destination = urlsplit(prepared.url)
    assert destination.scheme == "https"
    assert destination.netloc == "resource.services.ai.azure.com"
    assert destination.path == f"/api/projects/{quote(project_name, safe='')}/deployments"
    assert destination.fragment == ""
    assert parse_qs(destination.query) == {"api-version": ["v1"], "deploymentType": ["ModelDeployment"]}


@pytest.mark.parametrize("project_name", [".", ".."])
def test_project_dot_segments_are_refused(project_base, project_name):
    with pytest.raises(ValueError):
        project_base("https://resource.services.ai.azure.com", project_name)


@pytest.mark.parametrize("endpoint", [
    "https://resource.services.ai.azure.com/api/projects/project%20name/",
    "https://resource.services.ai.azure.us/api/projects/project/",
    "https://foundry.private.example:8443/gateway/api/projects/project/",
    "https://foundry.private.example:8443/gateway/api/projects/project/custom-suffix/",
    "http://10.0.0.9:8080/api/projects/project/",
    "https://[fd00::9]:8443/api/projects/project/",
])
def test_embedded_project_endpoint_wins_without_double_encoding(project_base, endpoint):
    base = project_base(endpoint, "../ignored?query#fragment")
    assert base == endpoint.rstrip("/")
    prepared = requests.Request("GET", f"{base}/deployments").prepare()
    assert urlsplit(prepared.url).path == f"{urlsplit(endpoint).path.rstrip('/')}/deployments"
    assert "%2520" not in prepared.url


@pytest.mark.parametrize("endpoint", [
    "https://resource.services.ai.azure.com/api/projects/..",
    "https://resource.services.ai.azure.com/api/projects/%2e%2E",
    "https://resource.services.ai.azure.com/api/projects/project/../other",
    "https://resource.services.ai.azure.com/api/projects/project?other=1",
    "https://resource.services.ai.azure.com/api/projects/project#fragment",
    "https://user:password@resource.services.ai.azure.com/api/projects/project",
    "https://resource.services.ai.azure.com:invalid/api/projects/project",
    "file:///api/projects/project",
    "https://resource.services.ai.azure.com\r\n/api/projects/project",
])
def test_malformed_embedded_project_destinations_are_refused(project_base, endpoint):
    with pytest.raises(ValueError):
        project_base(endpoint, "ignored")


@pytest.mark.parametrize("path", ["/api/models/fetch", "/api/models/test-connection"])
@pytest.mark.parametrize("connection", [
    {"endpoint": "https://resource.services.ai.azure.com", "project_name": ".."},
    {"endpoint": "https://resource.services.ai.azure.com"},
    {"endpoint": f"{PROJECT_ENDPOINT}?other=1"},
    {"endpoint": f"{PROJECT_ENDPOINT}#fragment"},
])
def test_admin_discovery_validates_project_before_credentials_or_http(env, path, connection):
    env.as_user("owner", roles=("User", "Admin"))
    endpoint = foundry_endpoint("", auth={"type": "managed_identity"})
    endpoint.pop("id")
    endpoint["connection"] = {**connection, "project_api_version": "v1"}
    response = env.call("POST", path, endpoint)
    assert response.status_code == 400
    if path == "/api/models/fetch":
        assert response.get_json() == SAFE_ERROR
    else:
        assert response.get_json() == {
            "error": "Unable to validate the model connection. Review the endpoint configuration and try again.",
        }
    env.credential_factory.assert_not_called()
    assert env.credentials == []
    assert env.http_calls == []
    assert env.model_logs("validation failed")


@pytest.mark.parametrize("path", [f"/api/groups/{GROUP_A}/models/fetch", "/api/group/models/fetch", "/api/user/models/fetch"])
@pytest.mark.parametrize("auth", [
    {"type": "managed_identity"},
    {},
    {"type": "bearer"},
    {"type": "managed_identity", "foundry_scope": "https://attacker.example/.default"},
    {"type": "managed_identity", "custom_authority": "https://login.attacker.example"},
    {"type": "managed_identity", "managed_identity_client_id": "other-identity"},
])
def test_existing_non_admin_identity_refusal_still_precedes_tokens_and_http(env, path, auth):
    endpoint = foundry_endpoint("", url="https://attacker.example/api/projects/project", auth=auth)
    endpoint.pop("id")
    response = env.call("POST", path, endpoint)
    assert response.status_code == 400
    assert response.get_json()["code"].startswith("server_credential_")
    env.credential_factory.assert_not_called()
    assert env.credentials == []
    assert env.http_calls == []


@pytest.mark.parametrize("provider", ["aifoundry", "new_foundry"])
@pytest.mark.parametrize("endpoint_url,cloud,scope", [
    ("https://resource.services.ai.azure.com", "public", "https://ai.azure.com/.default"),
    ("https://resource.services.ai.azure.us", "government", "https://ai.azure.us/.default"),
    ("https://foundry.private.example:8443/gateway", "custom", "https://ai.custom.example/.default"),
    ("http://10.0.0.9:8080", "custom", "https://ai.custom.example/.default"),
])
def test_admin_prepared_discovery_keeps_cloud_and_custom_destinations(env, provider, endpoint_url, cloud, scope):
    env.as_user("owner", roles=("User", "Admin"))
    endpoint = foundry_endpoint("", provider=provider, auth={
        "type": "managed_identity",
        "management_cloud": cloud,
        "foundry_scope": scope,
        "custom_authority": "https://login.custom.example" if cloud == "custom" else "",
        "managed_identity_client_id": "admin-selected-identity",
    })
    endpoint.pop("id")
    endpoint["connection"] = {
        "endpoint": endpoint_url, "project_name": "project name", "project_api_version": "v2",
    }
    response = env.call("POST", "/api/models/fetch", endpoint)
    assert response.status_code == 200, response.get_json()
    [credential] = env.credentials
    assert credential["scope"] == scope
    assert credential["auth"]["managed_identity_client_id"] == "admin-selected-identity"
    prepared = prepared_discovery_call(env)
    destination = urlsplit(prepared.url)
    origin = urlsplit(endpoint_url)
    assert (destination.scheme, destination.netloc) == (origin.scheme, origin.netloc)
    assert destination.path == f"{origin.path}/api/projects/project%20name/deployments"
    assert parse_qs(destination.query) == {"api-version": ["v2"], "deploymentType": ["ModelDeployment"]}
    assert destination.fragment == ""
    assert prepared.headers["Authorization"] == "Bearer fixture-only-access-token"


@pytest.mark.parametrize("path", [f"/api/groups/{GROUP_A}/models/fetch", "/api/user/models/fetch"])
def test_non_admin_caller_service_principal_keeps_custom_destination(env, path):
    endpoint = foundry_endpoint("", url="https://foundry.private.example:8443/api/projects/project%20name")
    endpoint.pop("id")
    response = env.call("POST", path, endpoint)
    assert response.status_code == 200, response.get_json()
    [credential] = env.credentials
    assert credential["auth"]["type"] == "service_principal"
    prepared = prepared_discovery_call(env)
    assert prepared.url.startswith("https://foundry.private.example:8443/api/projects/project%20name/deployments?")
    assert "%2520" not in prepared.url


@pytest.mark.parametrize("environment,url,scope", [
    ("public", "https://resource.services.ai.azure.com", "https://ai.azure.com/.default"),
    ("usgovernment", "https://resource.services.ai.azure.us", "https://ai.azure.us/.default"),
])
@pytest.mark.parametrize("path", [f"/api/groups/{GROUP_A}/models/fetch", "/api/user/models/fetch"])
def test_non_admin_application_identity_keeps_the_deployments_cloud(env, monkeypatch, environment, url, scope, path):
    monkeypatch.setattr(env.modules.settings, "AZURE_ENVIRONMENT", environment)
    endpoint = foundry_endpoint("", url=url, auth={"type": "managed_identity"})
    endpoint.pop("id")
    endpoint["connection"]["project_name"] = "project name"
    response = env.call("POST", path, endpoint)
    assert response.status_code == 200, response.get_json()
    [credential] = env.credentials
    assert credential["scope"] == scope
    prepared = prepared_discovery_call(env)
    assert urlsplit(prepared.url).netloc == urlsplit(url).netloc
    assert urlsplit(prepared.url).path == "/api/projects/project%20name/deployments"


def test_stored_global_endpoint_reached_from_group_keeps_administrator_trust(env):
    endpoint = foundry_endpoint("global-foundry", url="https://foundry.private.example/api/projects/project",
                               auth={"type": "managed_identity"})
    normalized, _changed = env.modules.settings.normalize_model_endpoints([endpoint])
    env.settings["model_endpoints"] = normalized
    response = env.call("POST", f"/api/groups/{GROUP_A}/models/fetch", {"endpoint_id": "global-foundry"})
    assert response.status_code == 200, response.get_json()
    assert len(env.credentials) == 1
    prepared = prepared_discovery_call(env)
    assert urlsplit(prepared.url).netloc == "foundry.private.example"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "test_support.cosmos_network_guard"]))
