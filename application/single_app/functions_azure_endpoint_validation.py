# functions_azure_endpoint_validation.py
"""Shared Azure endpoint origin validation for actions that use the application identity.

Actions can be configured with a caller-supplied endpoint while authenticating with the
application's own workload identity. Without an origin check, a caller who can save an
action is able to direct an application-identity token to a destination they control.
Each validator here rejects endpoints that are not canonical Azure service hostnames for
a supported Azure cloud and returns a rebuilt origin, so only the validated destination
ever reaches an SDK client.

This module is intentionally dependency-light so manifest validation, plugin construction,
and File Sync can all import it without creating import cycles.
"""

import ipaddress
import re
from typing import Any, Iterable, Tuple
from urllib.parse import ParseResult, quote, unquote, urlparse

# Azure Storage service suffixes for the public, US Government, China, and Germany clouds.
AZURE_STORAGE_ENDPOINT_SUFFIXES = (
    "core.windows.net",
    "core.usgovcloudapi.net",
    "core.chinacloudapi.cn",
    "core.cloudapi.de",
)
AZURE_COSMOS_ENDPOINT_SUFFIXES = (
    "documents.azure.com",
    "documents.azure.us",
    "documents.azure.cn",
    "documents.microsoftazure.de",
)
AZURE_DATABRICKS_ENDPOINT_SUFFIXES = (
    "azuredatabricks.net",
    "databricks.azure.us",
    "databricks.azure.cn",
)
AZURE_MONITOR_QUERY_HOSTS = (
    "api.loganalytics.io",
    "api.loganalytics.us",
    "api.loganalytics.azure.cn",
)
# Mirrors azure.identity.AzureAuthorityHosts so a caller cannot select a token authority.
AZURE_ENTRA_AUTHORITY_HOSTS = (
    "login.microsoftonline.com",
    "login.microsoftonline.us",
    "login.chinacloudapi.cn",
    "login.microsoftonline.de",
)
AZURE_FOUNDRY_ENDPOINT_SUFFIXES = (
    "services.ai.azure.com",
    "services.ai.azure.us",
    "services.ai.azure.cn",
    "services.ai.azure.de",
)
AZURE_MAPS_ENDPOINT_HOSTS = (
    "atlas.microsoft.com",
    "atlas.azure.us",
    "atlas.azure.cn",
)

AZURE_BLOB_SERVICE_LABEL = "blob"
AZURE_QUEUE_SERVICE_LABEL = "queue"
AZURE_FILE_SERVICE_LABEL = "file"

MAX_ENDPOINT_LENGTH = 2048
STORAGE_ACCOUNT_LABEL_PATTERN = re.compile(r"^[a-z0-9]{3,24}$")
DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
DNS_NAME_PATTERN = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
KEY_VAULT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,22}[a-z0-9]$")
FOUNDRY_PROJECT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$")

AZURE_BLOB_ENDPOINT_ERROR = (
    "Blob Storage actions require an HTTPS Azure Blob service endpoint such as "
    "https://account.blob.core.windows.net"
)
AZURE_QUEUE_ENDPOINT_ERROR = (
    "Queue Storage actions require an HTTPS Azure Queue service endpoint such as "
    "https://account.queue.core.windows.net"
)
AZURE_COSMOS_ENDPOINT_ERROR = (
    "Cosmos actions require an HTTPS Azure Cosmos DB endpoint such as "
    "https://account.documents.azure.com"
)
AZURE_DATABRICKS_ENDPOINT_ERROR = (
    "Databricks actions require an HTTPS Azure Databricks workspace endpoint such as "
    "https://adb-0000000000000000.0.azuredatabricks.net"
)
AZURE_MONITOR_QUERY_ENDPOINT_ERROR = (
    "Log Analytics actions require a supported Azure Monitor query endpoint such as "
    "https://api.loganalytics.io"
)
AZURE_AUTHORITY_HOST_ERROR = (
    "Log Analytics actions require a supported Microsoft Entra authority host such as "
    "login.microsoftonline.com"
)
AZURE_FILE_ENDPOINT_ERROR = (
    "Azure Files requires an HTTPS Azure File service endpoint such as "
    "https://account.file.core.windows.net"
)
AZURE_FOUNDRY_ENDPOINT_ERROR = (
    "Foundry requires an HTTPS Azure AI Foundry endpoint such as "
    "https://resource.services.ai.azure.com"
)
AZURE_MAPS_ENDPOINT_ERROR = (
    "Azure Maps requires a supported HTTPS endpoint such as https://atlas.microsoft.com"
)
AZURE_KEY_VAULT_NAME_ERROR = (
    "Key Vault names must be 3-24 lowercase letters, numbers, or hyphens, start with a letter, "
    "and end with a letter or number"
)


def _normalize_endpoint_text(value: Any) -> str:
    return str(value or "").strip()[:MAX_ENDPOINT_LENGTH]


def _reject_unsafe_host(hostname: str, error_message: str) -> None:
    """Reject local hostnames and IP literals, which are never Azure service endpoints."""
    normalized_host = hostname.strip("[]")
    if (
        normalized_host in {"localhost", "localhost.localdomain"}
        or normalized_host.endswith(".localhost")
    ):
        raise ValueError(error_message)

    try:
        ipaddress.ip_address(normalized_host)
    except ValueError:
        return
    raise ValueError(error_message)


def parse_azure_https_endpoint(
    value: Any,
    error_message: str,
    allow_default_port: bool = False,
) -> Tuple[ParseResult, str]:
    """Structurally validate an HTTPS endpoint and return its parsed form and hostname.

    Rejects non-HTTPS schemes, embedded credentials, explicit ports, query strings,
    parameters, fragments, local hostnames, and IP literals. A bare hostname is accepted
    and treated as HTTPS so stored values without a scheme still validate.
    """
    raw_url = _normalize_endpoint_text(value)
    if not raw_url:
        raise ValueError(error_message)
    if "://" not in raw_url:
        raw_url = f"https://{raw_url}"

    parsed_url = urlparse(raw_url)
    try:
        parsed_port = parsed_url.port
    except ValueError as error:
        raise ValueError(error_message) from error

    if parsed_port is not None and not (allow_default_port and parsed_port == 443):
        raise ValueError(error_message)

    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.params
    ):
        raise ValueError(error_message)

    hostname = parsed_url.hostname.lower()
    _reject_unsafe_host(hostname, error_message)
    return parsed_url, hostname


def _match_endpoint_suffix(
    hostname: str,
    service_label: str,
    endpoint_suffixes: Iterable[str],
    error_message: str,
) -> Tuple[str, str]:
    """Return the resource label and matched Azure cloud suffix for a hostname."""
    for endpoint_suffix in endpoint_suffixes:
        host_suffix = f".{service_label}.{endpoint_suffix}" if service_label else f".{endpoint_suffix}"
        if not hostname.endswith(host_suffix):
            continue
        resource_label = hostname[: -len(host_suffix)]
        if resource_label:
            return resource_label, endpoint_suffix
    raise ValueError(error_message)


def azure_storage_endpoint_suffix_for_hostname(
    hostname: Any,
    service_label: str = AZURE_BLOB_SERVICE_LABEL,
    error_message: str = AZURE_BLOB_ENDPOINT_ERROR,
) -> Tuple[str, str]:
    """Return the storage account name and Azure cloud suffix for a service hostname."""
    normalized_hostname = str(hostname or "").strip().lower()
    account_name, endpoint_suffix = _match_endpoint_suffix(
        normalized_hostname,
        service_label,
        AZURE_STORAGE_ENDPOINT_SUFFIXES,
        error_message,
    )
    if not STORAGE_ACCOUNT_LABEL_PATTERN.match(account_name):
        raise ValueError(error_message)
    return account_name, endpoint_suffix


def _validate_storage_endpoint(value: Any, service_label: str, error_message: str) -> str:
    _, hostname = parse_azure_https_endpoint(value, error_message)
    account_name, endpoint_suffix = azure_storage_endpoint_suffix_for_hostname(
        hostname,
        service_label,
        error_message,
    )
    return f"https://{account_name}.{service_label}.{endpoint_suffix}"


def validate_azure_blob_endpoint(value: Any) -> str:
    """Return a canonical Azure Blob service origin, or raise ValueError."""
    return _validate_storage_endpoint(value, AZURE_BLOB_SERVICE_LABEL, AZURE_BLOB_ENDPOINT_ERROR)


def validate_azure_queue_endpoint(value: Any) -> str:
    """Return a canonical Azure Queue service origin, or raise ValueError."""
    return _validate_storage_endpoint(value, AZURE_QUEUE_SERVICE_LABEL, AZURE_QUEUE_ENDPOINT_ERROR)


def validate_azure_file_endpoint(value: Any) -> str:
    """Return a canonical Azure Files service origin, or raise ValueError."""
    return _validate_storage_endpoint(value, AZURE_FILE_SERVICE_LABEL, AZURE_FILE_ENDPOINT_ERROR)


def validate_azure_cosmos_endpoint(value: Any) -> str:
    """Return a canonical Azure Cosmos DB origin, or raise ValueError."""
    _, hostname = parse_azure_https_endpoint(
        value,
        AZURE_COSMOS_ENDPOINT_ERROR,
        allow_default_port=True,
    )
    account_name, endpoint_suffix = _match_endpoint_suffix(
        hostname,
        "",
        AZURE_COSMOS_ENDPOINT_SUFFIXES,
        AZURE_COSMOS_ENDPOINT_ERROR,
    )
    if not DNS_LABEL_PATTERN.match(account_name):
        raise ValueError(AZURE_COSMOS_ENDPOINT_ERROR)
    return f"https://{account_name}.{endpoint_suffix}"


def validate_azure_databricks_endpoint(value: Any) -> str:
    """Return a canonical Azure Databricks workspace origin, or raise ValueError."""
    _, hostname = parse_azure_https_endpoint(value, AZURE_DATABRICKS_ENDPOINT_ERROR)
    workspace_label, endpoint_suffix = _match_endpoint_suffix(
        hostname,
        "",
        AZURE_DATABRICKS_ENDPOINT_SUFFIXES,
        AZURE_DATABRICKS_ENDPOINT_ERROR,
    )
    if not DNS_NAME_PATTERN.match(workspace_label):
        raise ValueError(AZURE_DATABRICKS_ENDPOINT_ERROR)
    return f"https://{workspace_label}.{endpoint_suffix}"


def validate_azure_monitor_query_endpoint(value: Any) -> str:
    """Return a supported Azure Monitor query endpoint origin, or raise ValueError."""
    _, hostname = parse_azure_https_endpoint(value, AZURE_MONITOR_QUERY_ENDPOINT_ERROR)
    if hostname not in AZURE_MONITOR_QUERY_HOSTS:
        raise ValueError(AZURE_MONITOR_QUERY_ENDPOINT_ERROR)
    return f"https://{hostname}"


def validate_azure_entra_authority_host(value: Any) -> str:
    """Return a supported Microsoft Entra authority hostname, or raise ValueError."""
    _, hostname = parse_azure_https_endpoint(value, AZURE_AUTHORITY_HOST_ERROR)
    if hostname not in AZURE_ENTRA_AUTHORITY_HOSTS:
        raise ValueError(AZURE_AUTHORITY_HOST_ERROR)
    return hostname


def validate_azure_foundry_endpoint(value: Any, allow_project_path: bool = False) -> str:
    """Return a canonical Azure AI Foundry origin or project endpoint."""
    parsed_url, hostname = parse_azure_https_endpoint(value, AZURE_FOUNDRY_ENDPOINT_ERROR)
    resource_name, endpoint_suffix = _match_endpoint_suffix(
        hostname,
        "",
        AZURE_FOUNDRY_ENDPOINT_SUFFIXES,
        AZURE_FOUNDRY_ENDPOINT_ERROR,
    )
    if not DNS_LABEL_PATTERN.match(resource_name):
        raise ValueError(AZURE_FOUNDRY_ENDPOINT_ERROR)

    origin = f"https://{resource_name}.{endpoint_suffix}"
    path = parsed_url.path.rstrip("/")
    if not path:
        return origin
    if not allow_project_path:
        raise ValueError(AZURE_FOUNDRY_ENDPOINT_ERROR)

    path_parts = [unquote(part) for part in path.split("/") if part]
    if (
        len(path_parts) != 3
        or path_parts[:2] != ["api", "projects"]
        or not FOUNDRY_PROJECT_NAME_PATTERN.match(path_parts[2])
    ):
        raise ValueError(AZURE_FOUNDRY_ENDPOINT_ERROR)
    project_name = quote(path_parts[2], safe="-._~")
    return f"{origin}/api/projects/{project_name}"


def validate_azure_content_understanding_endpoint(value: Any) -> str:
    """Return a canonical Azure AI Foundry origin for Content Understanding."""
    return validate_azure_foundry_endpoint(value, allow_project_path=False)


def validate_azure_maps_endpoint(value: Any) -> str:
    """Return a supported Azure Maps origin, or raise ValueError."""
    _, hostname = parse_azure_https_endpoint(value, AZURE_MAPS_ENDPOINT_ERROR)
    if hostname not in AZURE_MAPS_ENDPOINT_HOSTS:
        raise ValueError(AZURE_MAPS_ENDPOINT_ERROR)
    return f"https://{hostname}"


def build_azure_key_vault_endpoint(vault_name: Any, endpoint_suffix: Any) -> str:
    """Build a canonical Key Vault origin from a validated name and trusted cloud suffix."""
    normalized_name = str(vault_name or "").strip().lower()
    if not KEY_VAULT_NAME_PATTERN.match(normalized_name):
        raise ValueError(AZURE_KEY_VAULT_NAME_ERROR)

    normalized_suffix = str(endpoint_suffix or "").strip().lower()
    if not normalized_suffix.startswith(".") or not DNS_NAME_PATTERN.match(normalized_suffix[1:]):
        raise ValueError("The configured Key Vault endpoint suffix is invalid")
    return f"https://{normalized_name}{normalized_suffix}"
