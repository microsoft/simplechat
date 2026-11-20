# functions_cosmos_container_provisioning.py
"""Create missing Cosmos DB containers through Azure Resource Manager.

Cosmos DB rejects container creation on its data-plane endpoint when the caller
authenticates with an Entra token (403, substatus 5300), whatever data-plane
role it holds. Under managed identity the app therefore cannot rely on
``create_container_if_not_exists`` alone to add containers that a new release
introduces. This module creates them through ARM instead, which works when the
identity holds an Azure role with
``Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/write`` on the
account (the deployers grant Contributor; ``deployers/Grant-CosmosContainerCreatePermission.ps1``
grants a narrower custom role).

This module must not import ``config``: ``config`` calls it while it is still
initializing.
"""

import logging
import os
import re
import time
from urllib.parse import quote, urlparse

import requests
from azure.identity import DefaultAzureCredential

from functions_appinsights import log_event


COSMOS_CONTAINER_ARM_API_VERSION = "2023-04-15"
ARM_REQUEST_TIMEOUT_SECONDS = 30
ARM_OPERATION_TIMEOUT_SECONDS = 180
ARM_POLL_INTERVAL_SECONDS = 2
SUPPORTED_CONTAINER_OPTIONS = {"id", "partition_key", "default_ttl", "indexing_policy"}
GUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
GRANT_SCRIPT_HINT = (
    "Grant the app's managed identity an Azure role with "
    "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/write on the Cosmos account "
    "(run deployers/Grant-CosmosContainerCreatePermission.ps1), or run 'azd provision' so Bicep creates the container."
)


class CosmosContainerProvisioningError(Exception):
    """Raised when a container cannot be created through ARM."""


def is_data_plane_container_create_forbidden(exc):
    """Return True when a Cosmos SDK error is the data-plane refusal of an Entra-authenticated create."""
    return getattr(exc, "status_code", None) == 403


def parse_cosmos_account_name(endpoint):
    """Extract the Cosmos account name from its document endpoint."""
    if not endpoint:
        return ""
    hostname = urlparse(endpoint).hostname or str(endpoint).split("/")[0]
    return hostname.split(".")[0].strip() if hostname else ""


def detect_app_service_location(environ):
    """Return the App Service's own (subscription, resource group) from platform variables.

    App Service sets WEBSITE_OWNER_NAME to "<subscription>+<resource group>-<region>webspace"
    and WEBSITE_RESOURCE_GROUP on every worker, so a deployment that never set
    AZURE_SUBSCRIPTION_ID or AZURE_RESOURCE_GROUP can still be located.
    """
    owner = (environ.get("WEBSITE_OWNER_NAME") or "").strip()
    subscription = owner.split("+", 1)[0].strip() if "+" in owner else ""
    if not GUID_PATTERN.fullmatch(subscription):
        subscription = ""
    group = (environ.get("WEBSITE_RESOURCE_GROUP") or "").strip()
    if not group and "+" in owner:
        # The owner name ends in "-<region>webspace" (optionally "-Linux"); the region never contains "-".
        group = re.sub(r"-[A-Za-z0-9]+webspace(-Linux)?\Z", "", owner.split("+", 1)[1], flags=re.I)
    return subscription, group


def resolve_cosmos_arm_target(database_name, environ=None):
    """Resolve the subscription, resource group and account the app's Cosmos client points at.

    Explicit AZURE_SUBSCRIPTION_ID / AZURE_RESOURCE_GROUP settings win. Without them the
    app's own App Service subscription and resource group are used, which is where every
    SimpleChat deployer places the Cosmos account.
    """
    environ = os.environ if environ is None else environ
    platform_subscription, platform_group = detect_app_service_location(environ)
    target = {
        "subscription_id": (environ.get("AZURE_SUBSCRIPTION_ID") or "").strip() or platform_subscription,
        "resource_group": (environ.get("AZURE_RESOURCE_GROUP") or "").strip() or platform_group,
        "account_name": (
            (environ.get("AZURE_COSMOS_ACCOUNT_NAME") or "").strip()
            or parse_cosmos_account_name(environ.get("AZURE_COSMOS_ENDPOINT", ""))
        ),
        "database_name": (database_name or "").strip(),
    }
    missing = [key for key, value in target.items() if not value]
    if missing:
        raise CosmosContainerProvisioningError(
            "Cannot create the Cosmos container through ARM because these settings are missing: "
            f"{', '.join(missing)}. Set AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP and "
            "AZURE_COSMOS_ACCOUNT_NAME on the app service."
        )
    return target


def _quote_segment(value):
    segment = str(value or "").strip()
    if not segment or segment in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._()-]+", segment):
        raise CosmosContainerProvisioningError("Invalid Cosmos ARM resource name.")
    return quote(segment, safe="")


def build_container_resource_path(target, container_id):
    """Build the ARM path of a Cosmos SQL container."""
    return (
        f"/subscriptions/{_quote_segment(target['subscription_id'])}"
        f"/resourceGroups/{_quote_segment(target['resource_group'])}"
        f"/providers/Microsoft.DocumentDB/databaseAccounts/{_quote_segment(target['account_name'])}"
        f"/sqlDatabases/{_quote_segment(target['database_name'])}"
        f"/containers/{_quote_segment(container_id)}"
    )


def _partition_key_paths(partition_key):
    if isinstance(partition_key, str):
        return [partition_key]
    if hasattr(partition_key, "get"):
        paths = partition_key.get("paths")
        if paths:
            return list(paths)
    path = getattr(partition_key, "path", None)
    if path:
        return [path] if isinstance(path, str) else list(path)
    raise CosmosContainerProvisioningError("A partition key path is required to create a container.")


def build_container_arm_body(container_options):
    """Translate create_container_if_not_exists keyword arguments into an ARM request body."""
    unsupported = sorted(set(container_options) - SUPPORTED_CONTAINER_OPTIONS)
    if unsupported:
        raise CosmosContainerProvisioningError(
            f"ARM container creation does not support these options: {', '.join(unsupported)}."
        )

    container_id = container_options.get("id")
    if not container_id:
        raise CosmosContainerProvisioningError("A container id is required.")

    resource = {
        "id": container_id,
        "partitionKey": {
            "paths": _partition_key_paths(container_options.get("partition_key")),
            "kind": "Hash",
        },
    }
    if container_options.get("default_ttl") is not None:
        resource["defaultTtl"] = int(container_options["default_ttl"])
    if container_options.get("indexing_policy"):
        resource["indexingPolicy"] = dict(container_options["indexing_policy"])

    return {"properties": {"resource": resource, "options": {}}}


def _wait_for_container(url, headers, session, sleep, clock):
    """Poll the container resource itself until ARM reports it.

    Cosmos's async-operation status URL sits at subscription scope, so an
    identity whose role is scoped to the account cannot read it. The container
    resource only needs containers/read.
    """
    deadline = clock() + ARM_OPERATION_TIMEOUT_SECONDS
    while clock() < deadline:
        sleep(ARM_POLL_INTERVAL_SECONDS)
        poll = session.get(url, headers=headers, timeout=ARM_REQUEST_TIMEOUT_SECONDS)
        if poll.status_code == 200:
            return
        if poll.status_code != 404:
            raise CosmosContainerProvisioningError(
                f"ARM container status check failed with HTTP {poll.status_code}."
            )

    raise CosmosContainerProvisioningError(
        f"The Cosmos container was not ready within {ARM_OPERATION_TIMEOUT_SECONDS} seconds."
    )


def create_cosmos_container_via_arm(
    container_options,
    *,
    database_name,
    resource_manager_endpoint,
    authority=None,
    credential=None,
    environ=None,
    session=None,
    sleep=time.sleep,
    clock=time.monotonic,
):
    """Create a Cosmos SQL container through ARM unless it already exists.

    Returns True when this call created the container and False when ARM already
    had it (another instance may have created it first).
    """
    body = build_container_arm_body(container_options)
    container_id = body["properties"]["resource"]["id"]
    target = resolve_cosmos_arm_target(database_name, environ=environ)
    resource_manager_endpoint = (resource_manager_endpoint or "").rstrip("/")
    if not resource_manager_endpoint.startswith("https://"):
        raise CosmosContainerProvisioningError("The resource manager endpoint must be an https URL.")

    url = (
        f"{resource_manager_endpoint}{build_container_resource_path(target, container_id)}"
        f"?api-version={COSMOS_CONTAINER_ARM_API_VERSION}"
    )

    if credential is None:
        credential = DefaultAzureCredential(authority=authority) if authority else DefaultAzureCredential()
    token = credential.get_token(f"{resource_manager_endpoint}/.default").token
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    session = session or requests

    existing = session.get(url, headers=headers, timeout=ARM_REQUEST_TIMEOUT_SECONDS)
    if existing.status_code == 200:
        return False
    if existing.status_code in (401, 403):
        raise CosmosContainerProvisioningError(
            f"The app identity is not allowed to read Cosmos containers through ARM (HTTP {existing.status_code}). "
            + GRANT_SCRIPT_HINT
        )
    if existing.status_code != 404:
        raise CosmosContainerProvisioningError(
            f"ARM container lookup failed with HTTP {existing.status_code}."
        )
    database_url = url.split("/containers/", 1)[0] + f"?api-version={COSMOS_CONTAINER_ARM_API_VERSION}"
    database = session.get(database_url, headers=headers, timeout=ARM_REQUEST_TIMEOUT_SECONDS)
    if database.status_code == 404:
        raise CosmosContainerProvisioningError(
            f"Cosmos database '{target['database_name']}' on account '{target['account_name']}' was not found "
            f"in resource group '{target['resource_group']}'. If the account lives in another resource group "
            "or subscription, set AZURE_RESOURCE_GROUP and AZURE_SUBSCRIPTION_ID on the app service."
        )
    if database.status_code != 200:
        raise CosmosContainerProvisioningError(
            f"ARM database lookup failed with HTTP {database.status_code}."
        )

    log_event(
        "[CosmosContainers] Creating Cosmos container through ARM.",
        extra={"container_name": container_id},
        level=logging.INFO,
    )
    response = session.put(url, headers=headers, json=body, timeout=ARM_REQUEST_TIMEOUT_SECONDS)
    if response.status_code in (401, 403):
        raise CosmosContainerProvisioningError(
            f"The app identity is not allowed to create Cosmos containers through ARM (HTTP {response.status_code}). "
            + GRANT_SCRIPT_HINT
        )
    if response.status_code not in (200, 201, 202):
        raise CosmosContainerProvisioningError(
            f"ARM container creation failed with HTTP {response.status_code}."
        )
    if response.status_code == 202:
        _wait_for_container(url, headers, session, sleep, clock)

    log_event(
        "[CosmosContainers] Created Cosmos container through ARM.",
        extra={"container_name": container_id},
        level=logging.INFO,
    )
    return True
