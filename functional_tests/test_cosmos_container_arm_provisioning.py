#!/usr/bin/env python3
# test_cosmos_container_arm_provisioning.py
"""
Functional test for Cosmos container creation under managed identity.
Version: 0.261.474
Implemented in: 0.261.474

This test ensures that every Cosmos container the app creates is declared in the
Bicep and Terraform deployers, that the app falls back to Azure Resource Manager
when Cosmos refuses data-plane container creation under managed identity, and
that the admin grant script exists with the permissions the fallback needs.
"""

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(APP_ROOT))

from functions_cosmos_container_provisioning import (  # noqa: E402
    CosmosContainerProvisioningError,
    build_container_arm_body,
    create_cosmos_container_via_arm,
    is_data_plane_container_create_forbidden,
    resolve_cosmos_arm_target,
)

# Containers created through a generic helper rather than a fixed name.
DYNAMIC_CONTAINER_CALLS = {"container_name", "kwargs.get('id')"}

ENVIRON = {
    "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
    "AZURE_RESOURCE_GROUP": "simplechat-rg",
    "AZURE_COSMOS_ACCOUNT_NAME": "simplechat-cosmos",
}
RESOURCE_MANAGER = "https://management.azure.com"
EXPECTED_URL = (
    "https://management.azure.com/subscriptions/00000000-0000-0000-0000-000000000000"
    "/resourceGroups/simplechat-rg/providers/Microsoft.DocumentDB/databaseAccounts/simplechat-cosmos"
    "/sqlDatabases/SimpleChat/containers/support_exports?api-version=2023-04-15"
)


class FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class FakeSession:
    def __init__(self, get_statuses, put_status=201):
        self.get_statuses = list(get_statuses)
        self.put_status = put_status
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None))
        return FakeResponse(self.get_statuses.pop(0))

    def put(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("PUT", url, json))
        return FakeResponse(self.put_status)


class FakeToken:
    token = "fake-token"


class FakeCredential:
    def __init__(self):
        self.scopes = []

    def get_token(self, scope):
        self.scopes.append(scope)
        return FakeToken()


class FakeCosmosError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def _support_exports_options():
    return {"id": "support_exports", "partition_key": {"paths": ["/partition_key"], "kind": "Hash"}, "default_ttl": -1}


def _create(session, options=None, environ=None):
    credential = FakeCredential()
    created = create_cosmos_container_via_arm(
        options or _support_exports_options(),
        database_name="SimpleChat",
        resource_manager_endpoint=RESOURCE_MANAGER,
        credential=credential,
        environ=ENVIRON if environ is None else environ,
        session=session,
        sleep=lambda _seconds: None,
    )
    return created, credential


def _app_containers():
    names = {}
    calls = {}
    for path in APP_ROOT.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^(\w+)\s*=\s*[\"']([\w-]+)[\"']", source, re.M):
            names[match.group(1)] = match.group(2)
        for match in re.finditer(r"create_container_if_not_exists\((.*?)\n\s*\)", source, re.S):
            body = match.group(1)
            id_match = re.search(r"id\s*=\s*([^,\n]+)", body)
            path_match = re.search(r"path\s*=\s*[\"']([^\"']+)", body)
            if not id_match or not path_match:
                continue
            calls[id_match.group(1).strip().rstrip(",")] = path_match.group(1)

    containers = {}
    for raw_id, partition_key in calls.items():
        if raw_id in DYNAMIC_CONTAINER_CALLS:
            continue
        name = raw_id.strip("\"'") if raw_id[0] in "\"'" else names.get(raw_id)
        assert name, f"Could not resolve container name for {raw_id}"
        containers[name] = partition_key
    return containers


def test_deployers_declare_every_app_container():
    """Every container the app creates is declared, with the same partition key, in Bicep and Terraform."""
    print("Testing deployer container coverage...")
    app_containers = _app_containers()
    assert len(app_containers) >= 70, f"Expected the full container list, found {len(app_containers)}"

    bicep = (REPO_ROOT / "deployers" / "bicep" / "modules" / "cosmosDb.bicep").read_text(encoding="utf-8")
    bicep_containers = dict(re.findall(r"name: '(\w+)'\s*\n\s*partitionKeyPath: '([^']+)'", bicep))
    terraform = (REPO_ROOT / "deployers" / "terraform" / "main.tf").read_text(encoding="utf-8")
    terraform_containers = dict(re.findall(r"^\s*(\w+)\s*=\s*\{ partition_key_path = \"([^\"]+)\"", terraform, re.M))
    compiled = (REPO_ROOT / "deployers" / "bicep" / "main.json").read_text(encoding="utf-8")

    for name, partition_key in sorted(app_containers.items()):
        assert bicep_containers.get(name) == partition_key, f"cosmosDb.bicep is missing or mismatches {name}"
        assert terraform_containers.get(name) == partition_key, f"terraform main.tf is missing or mismatches {name}"
        assert f'"name": "{name}"' in compiled, f"main.json was not rebuilt with {name}"
    print("Test passed!")


def test_existing_container_is_left_alone():
    """When ARM already has the container nothing is written."""
    session = FakeSession([200])
    created, credential = _create(session)
    assert created is False
    assert [call[0] for call in session.calls] == ["GET"]
    assert session.calls[0][1] == EXPECTED_URL
    assert credential.scopes == ["https://management.azure.com/.default"]


def test_missing_container_is_created_with_its_definition():
    """A missing container is created with the partition key, TTL and indexing policy the app asked for."""
    indexing_policy = {"compositeIndexes": [[{"path": "/created_at", "order": "descending"}]]}
    options = dict(_support_exports_options(), indexing_policy=indexing_policy)
    session = FakeSession([404, 200], put_status=201)
    created, _credential = _create(session, options)

    assert created is True
    method, url, body = session.calls[2]
    assert (method, url) == ("PUT", EXPECTED_URL)
    resource = body["properties"]["resource"]
    assert resource["id"] == "support_exports"
    assert resource["partitionKey"] == {"paths": ["/partition_key"], "kind": "Hash"}
    assert resource["defaultTtl"] == -1
    assert resource["indexingPolicy"] == indexing_policy


def test_accepted_create_waits_for_the_container():
    """A 202 create polls the container resource until ARM reports it."""
    session = FakeSession([404, 200, 404, 200], put_status=202)
    created, _credential = _create(session)
    assert created is True
    assert [call[0] for call in session.calls] == ["GET", "GET", "PUT", "GET", "GET"]


def test_forbidden_create_points_to_the_grant_script():
    """A 403 from ARM explains how to grant the permission."""
    session = FakeSession([404, 200], put_status=403)
    try:
        _create(session)
    except CosmosContainerProvisioningError as exc:
        assert "Grant-CosmosContainerCreatePermission.ps1" in str(exc)
    else:
        raise AssertionError("Expected a provisioning error for HTTP 403")


def test_missing_settings_and_unsupported_options_fail_clearly():
    """Missing resource settings and options ARM cannot express raise instead of guessing."""
    try:
        _create(FakeSession([]), environ={})
    except CosmosContainerProvisioningError as exc:
        assert "AZURE_SUBSCRIPTION_ID" in str(exc)
    else:
        raise AssertionError("Expected an error for missing settings")

    try:
        build_container_arm_body(dict(_support_exports_options(), offer_throughput=400))
    except CosmosContainerProvisioningError as exc:
        assert "offer_throughput" in str(exc)
    else:
        raise AssertionError("Expected an error for an unsupported option")


def test_only_forbidden_errors_trigger_the_fallback():
    """The data-plane check matches 403 and nothing else."""
    assert is_data_plane_container_create_forbidden(FakeCosmosError(403))
    assert not is_data_plane_container_create_forbidden(FakeCosmosError(404))
    assert not is_data_plane_container_create_forbidden(FakeCosmosError(500))


def test_config_falls_back_only_under_managed_identity():
    """config.py routes a forbidden create to ARM only for managed identity."""
    source = (APP_ROOT / "config.py").read_text(encoding="utf-8")
    wrapper = source.split("def _create_container_if_not_exists_with_conflict_recovery", 1)[1].split("\ncosmos_database.create_container_if_not_exists =", 1)[0]
    assert 'cosmos_authentication_type != "managed_identity"' in wrapper
    assert "is_data_plane_container_create_forbidden(exc)" in wrapper
    assert "create_cosmos_container_via_arm(" in wrapper
    assert "resource_manager_endpoint=resource_manager" in wrapper


def test_grant_script_grants_container_write():
    """The admin script grants the ARM action the fallback needs."""
    script = (REPO_ROOT / "deployers" / "Grant-CosmosContainerCreatePermission.ps1").read_text(encoding="utf-8")
    assert "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/write" in script
    assert "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/read" in script
    assert "SupportsShouldProcess" in script


def test_app_service_platform_variables_locate_the_account():
    """Without explicit settings the app's own App Service subscription and resource group are used."""
    environ = {
        "WEBSITE_OWNER_NAME": "00000000-0000-0000-0000-000000000000+simplechat-rg-EastUSwebspace-Linux",
        "AZURE_COSMOS_ENDPOINT": "https://simplechat-cosmos.documents.azure.com:443/",
    }
    target = resolve_cosmos_arm_target("SimpleChat", environ=environ)
    assert target["subscription_id"] == "00000000-0000-0000-0000-000000000000"
    assert target["resource_group"] == "simplechat-rg"
    assert target["account_name"] == "simplechat-cosmos"

    environ["WEBSITE_RESOURCE_GROUP"] = "platform-rg"
    assert resolve_cosmos_arm_target("SimpleChat", environ=environ)["resource_group"] == "platform-rg"

    environ.update(AZURE_SUBSCRIPTION_ID="11111111-1111-1111-1111-111111111111", AZURE_RESOURCE_GROUP="cosmos-rg")
    target = resolve_cosmos_arm_target("SimpleChat", environ=environ)
    assert target["subscription_id"] == "11111111-1111-1111-1111-111111111111"
    assert target["resource_group"] == "cosmos-rg"


def test_account_in_another_resource_group_explains_the_settings():
    """A missing database (wrong resource group) asks for explicit settings instead of creating anything."""
    session = FakeSession([404, 404])
    try:
        _create(session)
    except CosmosContainerProvisioningError as exc:
        assert "AZURE_RESOURCE_GROUP" in str(exc)
    else:
        raise AssertionError("Expected an error when the database is not found")
    assert [call[0] for call in session.calls] == ["GET", "GET"]


def test_all_deployers_set_the_cosmos_location_settings():
    """Bicep, Terraform and the Azure CLI deployer give the app its Cosmos subscription, group and account."""
    bicep = (REPO_ROOT / "deployers" / "bicep" / "modules" / "appService.bicep").read_text(encoding="utf-8")
    terraform = (REPO_ROOT / "deployers" / "terraform" / "main.tf").read_text(encoding="utf-8")
    cli = (REPO_ROOT / "deployers" / "azurecli" / "deploy-simplechat.ps1").read_text(encoding="utf-8")
    for setting in ("AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP", "AZURE_COSMOS_ACCOUNT_NAME"):
        assert f"name: '{setting}'" in bicep, f"appService.bicep does not set {setting}"
        assert f'"{setting}"' in terraform, f"terraform main.tf does not set {setting}"
        assert f'"{setting}=' in cli, f"deploy-simplechat.ps1 does not set {setting}"


if __name__ == "__main__":
    tests = [
        test_deployers_declare_every_app_container,
        test_existing_container_is_left_alone,
        test_missing_container_is_created_with_its_definition,
        test_accepted_create_waits_for_the_container,
        test_forbidden_create_points_to_the_grant_script,
        test_missing_settings_and_unsupported_options_fail_clearly,
        test_only_forbidden_errors_trigger_the_fallback,
        test_config_falls_back_only_under_managed_identity,
        test_grant_script_grants_container_write,
        test_app_service_platform_variables_locate_the_account,
        test_account_in_another_resource_group_explains_the_settings,
        test_all_deployers_set_the_cosmos_location_settings,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    sys.exit(1 if failed else 0)
