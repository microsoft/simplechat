# test_deployment_cosmos_access.py
"""Cosmos deployment authentication regression tests.

Version: 0.261.028
Implemented in: 0.261.028
Validate credential choice and that failed probes never mutate firewalls.
"""

import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError


SOURCE = Path(__file__).resolve().parents[1] / "deployers" / "bicep" / "deployment_cosmos.py"
SPEC = importlib.util.spec_from_file_location("deployment_cosmos", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def inputs():
    return {
        "AZURE_SUBSCRIPTION_ID": "subscription",
        "AZURE_TENANT_ID": "tenant",
        "var_rgName": "group",
        "var_cosmosDb_accountName": "account",
        "var_authenticationType": "managed_identity",
        "var_cosmosDb_key": "stale-key-must-not-win",
    }


def test_entra_works_with_local_auth_disabled(inputs):
    account = {"documentEndpoint": "https://account.documents.azure.com", "disableLocalAuth": True}
    client = Mock()
    client.list_databases.return_value = iter([])
    with patch.object(MODULE, "run_cli", return_value=account) as cli, patch.object(
        MODULE, "AzureCliCredential"
    ) as credential, patch.object(MODULE.azure_cosmos, "CosmosClient", return_value=client) as factory:
        result = MODULE.create_deployment_cosmos_client(inputs)
    assert result is client
    credential.assert_called_once_with(tenant_id="tenant")
    assert factory.call_args.kwargs["credential"] is credential.return_value
    assert cli.call_count == 1


def test_key_mode_checks_local_auth_before_list_keys(inputs):
    inputs["var_authenticationType"] = "key"
    account = {"documentEndpoint": "https://account.documents.azure.com", "disableLocalAuth": True}
    with patch.object(MODULE, "run_cli", return_value=account) as cli:
        with pytest.raises(RuntimeError, match="key authentication is disabled"):
            MODULE.create_deployment_cosmos_client(inputs)
    assert cli.call_count == 1


@pytest.mark.parametrize("message,expected", [
    ("Forbidden by firewall", "network access is blocked"),
    ("Insufficient data-plane permissions", "data-plane RBAC failed"),
])
def test_failed_probe_does_not_change_network(inputs, message, expected):
    account = {"documentEndpoint": "https://account.documents.azure.com", "ipRules": []}
    failure = CosmosHttpResponseError(status_code=403, message=message)
    with patch.object(MODULE, "run_cli", return_value=account) as cli, patch.object(
        MODULE, "AzureCliCredential"
    ), patch.object(MODULE.azure_cosmos, "CosmosClient", side_effect=failure):
        with pytest.raises(RuntimeError, match=expected):
            MODULE.create_deployment_cosmos_client(inputs)
    assert cli.call_count == 1
    assert cli.call_args.args[0][:2] == ["cosmosdb", "show"]
    assert account["ipRules"] == []


def test_private_endpoint_runner_can_succeed(inputs):
    account = {"documentEndpoint": "https://account.documents.azure.com", "publicNetworkAccess": "Disabled"}
    client = Mock()
    client.list_databases.return_value = iter([])
    with patch.object(MODULE, "run_cli", return_value=account), patch.object(
        MODULE, "AzureCliCredential"
    ), patch.object(MODULE.azure_cosmos, "CosmosClient", return_value=client):
        result = MODULE.create_deployment_cosmos_client(inputs)
    assert result is client


def test_key_mode_retrieves_key_only_for_target_account(inputs):
    inputs["var_authenticationType"] = "key"
    account = {"documentEndpoint": "https://account.documents.azure.com", "disableLocalAuth": False}
    client = Mock()
    client.list_databases.return_value = iter([])
    with patch.object(MODULE, "run_cli", side_effect=[account, {"primaryMasterKey": "test-key"}]) as cli, patch.object(
        MODULE.azure_cosmos, "CosmosClient", return_value=client
    ) as factory, patch.object(MODULE, "AzureCliCredential") as entra:
        result = MODULE.create_deployment_cosmos_client(inputs)
    assert result is client
    assert cli.call_count == 2
    assert cli.call_args.args[0] == [
        "cosmosdb", "keys", "list", "--subscription", "subscription",
        "--resource-group", "group", "--name", "account",
    ]
    assert factory.call_args.kwargs["credential"] == "test-key"
    entra.assert_not_called()


def test_failed_read_closes_client_and_redacts_error(inputs):
    account = {"documentEndpoint": "https://account.documents.azure.com"}
    client = Mock()
    client.list_databases.side_effect = CosmosHttpResponseError(status_code=401, message="sensitive-provider-response")
    with patch.object(MODULE, "run_cli", return_value=account), patch.object(
        MODULE, "AzureCliCredential"
    ), patch.object(MODULE.azure_cosmos, "CosmosClient", return_value=client):
        with pytest.raises(RuntimeError) as error:
            MODULE.create_deployment_cosmos_client(inputs)
    assert "sensitive-provider-response" not in str(error.value)
    client.close.assert_called_once()