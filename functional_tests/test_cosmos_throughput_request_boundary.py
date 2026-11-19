# test_cosmos_throughput_request_boundary.py
"""
Functional tests for the Cosmos ARM resource request boundary (CodeQL alert 1089).
Version: 0.261.457
Implemented in: 0.261.457

Real resource builders and Requests URL preparation run without cloud access.
Malformed paths must fail before credential acquisition or HTTP, while encoded
resource names, management-cloud configuration, payloads and shared tokens survive.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, quote, urlsplit

import pytest
import requests

from test_support.agent_delegation import module_stub


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
SETTINGS = {
    "cosmos_throughput_subscription_id": "sub-123",
    "cosmos_throughput_resource_group": "rg-demo",
    "cosmos_throughput_account_name": "simplechat-cosmos",
    "cosmos_throughput_database_name": "SimpleChat",
}
DATABASE_PATH = (
    "/subscriptions/sub-123/resourceGroups/rg-demo"
    "/providers/Microsoft.DocumentDB/databaseAccounts/simplechat-cosmos"
    "/sqlDatabases/SimpleChat"
)


@pytest.fixture
def arm(monkeypatch):
    logs = Mock()
    monkeypatch.setitem(sys.modules, "functions_appinsights", module_stub("functions_appinsights", log_event=logs))
    spec = importlib.util.spec_from_file_location("azure_arm_boundary", APP_ROOT / "functions_cosmos_throughput.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    credential = Mock()
    credential.get_token.return_value = SimpleNamespace(token="fixture-only-arm-token")
    credential_factory = Mock(return_value=credential)
    monkeypatch.setattr(module, "DefaultAzureCredential", credential_factory)
    config = module_stub(
        "config",
        resource_manager="https://management.azure.com",
        authority="https://login.microsoftonline.com",
        credential_scopes=["https://management.azure.com/.default"],
    )
    monkeypatch.setitem(sys.modules, "config", config)
    sent = []

    def send(session, prepared, **kwargs):
        sent.append((prepared, kwargs))
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({
            "properties": {"resource": {"autoscaleSettings": {"maxThroughput": 4000}}},
        }).encode("utf-8")
        response.headers["Content-Type"] = "application/json"
        response.request = prepared
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    return SimpleNamespace(
        module=module, config=config, sent=sent, credential=credential,
        credential_factory=credential_factory, logs=logs,
    )


@pytest.mark.parametrize("container_name", [".", ".."])
def test_container_dot_segments_cannot_select_database_throughput(arm, container_name):
    with pytest.raises(arm.module.CosmosThroughputError):
        arm.module.get_container_throughput(SETTINGS, container_name)
    arm.credential_factory.assert_not_called()
    arm.credential.get_token.assert_not_called()
    assert arm.sent == []


@pytest.mark.parametrize("resource_path", [
    f"{DATABASE_PATH}/containers/../throughputSettings/default",
    f"{DATABASE_PATH}/containers/%2e/throughputSettings/default",
    f"{DATABASE_PATH}/containers/%2E%2e/throughputSettings/default",
    f"{DATABASE_PATH}/containers/docs/../../throughputSettings/default",
    f"{DATABASE_PATH}/containers/docs/throughputSettings/default?other=1",
    f"{DATABASE_PATH}/containers/docs/throughputSettings/default#fragment",
    f"{DATABASE_PATH}/containers//throughputSettings/default",
    f"{DATABASE_PATH}/containers/docs\\other/throughputSettings/default",
    f"{DATABASE_PATH}/containers/docs%ZZ/throughputSettings/default",
    f"{DATABASE_PATH}/containers/docs\r\n/throughputSettings/default",
    "//attacker.example/containers/docs/throughputSettings/default",
    "https://attacker.example/containers/docs/throughputSettings/default",
    "/subscriptions/sub-123/providers/Microsoft.Compute/virtualMachines/target",
])
@pytest.mark.parametrize("shared_context", [False, True])
def test_outbound_arm_boundary_refuses_malformed_resource_paths(arm, resource_path, shared_context):
    context = {
        "resource_manager_endpoint": arm.config.resource_manager,
        "token": "fixture-only-shared-token",
        "credential_elapsed_ms": 7,
    } if shared_context else None
    with pytest.raises(arm.module.CosmosThroughputError):
        arm.module._arm_request("GET", resource_path, request_context=context)
    arm.credential_factory.assert_not_called()
    arm.credential.get_token.assert_not_called()
    assert arm.sent == []


@pytest.mark.parametrize("endpoint,authority,scope", [
    ("https://management.azure.com", "https://login.microsoftonline.com", "https://management.azure.com/.default"),
    ("https://management.usgovcloudapi.net", "https://login.microsoftonline.us", "https://management.core.usgovcloudapi.net/.default"),
    ("https://arm.private.example:8443/gateway", "https://login.custom.example", "https://arm.custom.example/.default"),
    ("http://10.0.0.8:8080/arm", "https://login.custom.example", "https://arm.custom.example/.default"),
])
def test_prepared_arm_request_keeps_configured_cloud_and_encoded_resources(arm, endpoint, authority, scope):
    arm.config.resource_manager = f"{endpoint}/"
    arm.config.authority = authority
    arm.config.credential_scopes = [scope]
    settings = {
        **SETTINGS,
        "cosmos_throughput_resource_group": "rg (production)",
        "cosmos_throughput_database_name": "database \u00e9",
    }
    resource_ids = arm.module.build_cosmos_resource_ids(settings)
    container_name = "documents%20archive"
    container_ids = arm.module.build_cosmos_container_resource_ids(resource_ids, container_name)
    payload = {"properties": {"resource": {"throughput": 400}}}
    result = arm.module._arm_request("PUT", container_ids["throughput_id"], payload=payload)

    arm.credential_factory.assert_called_once_with(authority=authority)
    arm.credential.get_token.assert_called_once_with(scope)
    [(prepared, options)] = arm.sent
    expected_path = (
        f"{urlsplit(endpoint).path}{resource_ids['database_id']}"
        f"/containers/{quote(container_name, safe='')}/throughputSettings/default"
    )
    destination = urlsplit(prepared.url)
    assert (destination.scheme, destination.netloc) == (urlsplit(endpoint).scheme, urlsplit(endpoint).netloc)
    assert destination.path == expected_path
    assert "%2520archive" in destination.path
    assert "%252520archive" not in destination.path
    assert parse_qs(destination.query) == {"api-version": [arm.module.COSMOS_THROUGHPUT_ARM_API_VERSION]}
    assert destination.fragment == ""
    assert prepared.headers["Authorization"] == "Bearer fixture-only-arm-token"
    assert prepared.method == "PUT"
    assert json.loads(prepared.body) == payload
    assert options["timeout"] == 30
    assert result["properties"]["resource"]["autoscaleSettings"]["maxThroughput"] == 4000


@pytest.mark.parametrize("suffix", [
    "/throughputSettings/default",
    "/throughputSettings/default/migrateToAutoscale",
    "/containers",
    "/containers/documents/throughputSettings/default",
    "/containers/documents/throughputSettings/default/migrateToAutoscale",
])
def test_supported_arm_operations_reuse_a_shared_request_context(arm, suffix):
    context = {
        "resource_manager_endpoint": "https://management.usgovcloudapi.net",
        "token": "fixture-only-shared-token",
        "credential_elapsed_ms": 7,
    }
    arm.module._arm_request("POST" if suffix.endswith("migrateToAutoscale") else "GET", f"{DATABASE_PATH}{suffix}", request_context=context)
    arm.credential_factory.assert_not_called()
    arm.credential.get_token.assert_not_called()
    [(prepared, _options)] = arm.sent
    assert prepared.headers["Authorization"] == "Bearer fixture-only-shared-token"
    assert urlsplit(prepared.url).path == f"{DATABASE_PATH}{suffix}"


def test_resource_manager_configuration_still_precedes_environment_fallback(arm, monkeypatch):
    monkeypatch.setenv("CUSTOM_RESOURCE_MANAGER_URL_VALUE", "https://fallback.private.example/arm/")
    configured = arm.module._get_resource_manager_endpoint()
    assert configured == "https://management.azure.com"
    monkeypatch.delattr(arm.config, "resource_manager")
    fallback = arm.module._get_resource_manager_endpoint()
    assert fallback == "https://fallback.private.example/arm"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "test_support.cosmos_network_guard"]))
