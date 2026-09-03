# deployment_cosmos.py
"""Deployment-time Cosmos authentication and non-mutating reachability checks."""

import json
import os
import shutil
import subprocess

import azure.cosmos as azure_cosmos
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.identity import AzureCliCredential
from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError


def run_cli(arguments):
    executable = shutil.which("az") or shutil.which("az.cmd")
    if not executable:
        raise RuntimeError("Azure CLI is required for post-provision configuration.")
    result = subprocess.run(
        [executable, *arguments, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Azure CLI operation failed. Check deployment identity and subscription access.")
    return json.loads(result.stdout)


def create_deployment_cosmos_client(environment=None):
    environment = os.environ if environment is None else environment
    subscription = environment.get("AZURE_SUBSCRIPTION_ID") or environment.get("var_subscriptionId")
    group = environment.get("var_rgName")
    account_name = environment.get("var_cosmosDb_accountName")
    mode = environment.get("var_authenticationType", "").strip().lower()
    if not all((subscription, group, account_name)) or mode not in {"managed_identity", "key"}:
        raise ValueError("Cosmos subscription, resource group, account and authentication type are required.")

    account = run_cli([
        "cosmosdb", "show", "--subscription", subscription,
        "--resource-group", group, "--name", account_name,
    ])
    if account.get("publicNetworkAccess") == "Disabled":
        print("Cosmos public access is disabled; this runner must reach a private endpoint.")
    endpoint = account["documentEndpoint"]
    if mode == "managed_identity":
        tenant = environment.get("AZURE_TENANT_ID")
        credential = AzureCliCredential(**({"tenant_id": tenant} if tenant else {}))
    else:
        if account.get("disableLocalAuth"):
            raise RuntimeError("Cosmos key authentication is disabled. Select managed_identity authentication.")
        credential = run_cli([
            "cosmosdb", "keys", "list", "--subscription", subscription,
            "--resource-group", group, "--name", account_name,
        ])["primaryMasterKey"]

    client = None
    try:
        client = azure_cosmos.CosmosClient(endpoint, credential=credential, connection_timeout=15, read_timeout=30)
        next(client.list_databases(), None)
        return client
    except CosmosHttpResponseError as error:
        if client is not None:
            client.close()
        message = str(error).lower()
        if "firewall" in message or "public internet" in message:
            detail = "Cosmos network access is blocked. Use a network-connected runner or an approved firewall rule."
        elif error.status_code in (401, 403):
            detail = "Cosmos authentication or data-plane RBAC failed. Check the selected credential and Cosmos data role."
        else:
            detail = "Cosmos data-plane check failed. Check service availability and deployment diagnostics."
        raise RuntimeError(detail + " No firewall rules were changed.") from None
    except ClientAuthenticationError:
        if client is not None:
            client.close()
        raise RuntimeError("Azure CLI authentication failed. Sign in to the deployment tenant and retry.") from None
    except ServiceRequestError:
        if client is not None:
            client.close()
        raise RuntimeError("Cosmos endpoint could not be reached. Check DNS and runner network connectivity.") from None


if __name__ == "__main__":
    with create_deployment_cosmos_client() as cosmos_client:
        print("Cosmos data-plane access verified; firewall settings were not changed.")