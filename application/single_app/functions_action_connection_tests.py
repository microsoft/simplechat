# functions_action_connection_tests.py
"""Connection tests for configurable SimpleChat action (plugin) types.

Each public tester takes an already hydrated action manifest, authenticates with the
configured credentials, and performs one lightweight read against the configured
resource. Testers never raise; they return a normalized result dictionary so the
calling route can jsonify it directly.

Secrets are never echoed back to the browser. Every failure message is passed through
``sanitize_connection_error`` before it leaves this module.
"""

import asyncio
import base64
import logging
import re
from datetime import timedelta
from typing import Any, Dict, List, Optional

import requests

from functions_appinsights import log_event
from functions_azure_endpoint_validation import validate_azure_maps_endpoint
from functions_azure_maps import (
    AZURE_MAPS_DEFAULT_ENDPOINT,
    AZURE_MAPS_DEFAULT_LANGUAGE,
    AZURE_MAPS_DEFAULT_TILESET_ID,
    AZURE_MAPS_DEFAULT_VIEW,
    AZURE_MAPS_TILE_API_VERSION,
)
from functions_mcp_operations import MCP_CUSTOM_HEADERS_FIELD
from functions_outbound_http import OutboundHttpPolicyError, request_public_https

ACTION_CONNECTION_TEST_MAX_TIMEOUT_SECONDS = 20
ACTION_CONNECTION_TEST_MIN_TIMEOUT_SECONDS = 1
ACTION_CONNECTION_TEST_DEFAULT_TIMEOUT_SECONDS = 15

REDACTED_PLACEHOLDER = "[redacted]"

_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|pwd|passphrase|private[_\s-]*key|secret|token|api[_\s-]*key|accountkey|sharedaccesssignature|sig)\b\s*[=:]\s*[^\s,;&'\"]+"
)
_AUTHORIZATION_HEADER_PATTERN = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")

_MISSING_PACKAGE_MESSAGES = {
    "snowflake": "The Snowflake Connector for Python is not installed in this container image. Rebuild the image with snowflake-connector-python to test Snowflake actions.",
    "tableau": "The tableauserverclient package is not installed in this container image. Rebuild the image with tableauserverclient to test Tableau actions.",
    "log_analytics": "The azure-monitor-query package is not installed in this container image. Rebuild the image with azure-monitor-query to test Log Analytics actions.",
}


def resolve_test_timeout(raw_timeout: Any, default_timeout: int = ACTION_CONNECTION_TEST_DEFAULT_TIMEOUT_SECONDS) -> int:
    """Clamp a caller-supplied timeout into the allowed action connection test range."""
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError):
        timeout = default_timeout
    if timeout < ACTION_CONNECTION_TEST_MIN_TIMEOUT_SECONDS:
        timeout = ACTION_CONNECTION_TEST_MIN_TIMEOUT_SECONDS
    return min(timeout, ACTION_CONNECTION_TEST_MAX_TIMEOUT_SECONDS)


def collect_manifest_secret_values(manifest: Optional[Dict[str, Any]]) -> List[str]:
    """Collect every literal secret value stored in a manifest so it can be redacted."""
    if not isinstance(manifest, dict):
        return []

    secret_values: List[str] = []

    auth = manifest.get("auth") if isinstance(manifest.get("auth"), dict) else {}
    for auth_field in ("key", "identity", "tenantId"):
        auth_value = auth.get(auth_field)
        if isinstance(auth_value, str) and len(auth_value.strip()) >= 4:
            secret_values.append(auth_value.strip())

    additional_fields = manifest.get("additionalFields") if isinstance(manifest.get("additionalFields"), dict) else {}
    passphrase = additional_fields.get("private_key_passphrase")
    if isinstance(passphrase, str) and len(passphrase.strip()) >= 4:
        secret_values.append(passphrase.strip())

    custom_headers = additional_fields.get(MCP_CUSTOM_HEADERS_FIELD)
    if isinstance(custom_headers, dict):
        for header_value in custom_headers.values():
            if isinstance(header_value, str) and len(header_value.strip()) >= 4:
                secret_values.append(header_value.strip())

    # Redact the longest values first so overlapping secrets do not leave fragments behind.
    return sorted(set(secret_values), key=len, reverse=True)


def sanitize_connection_error(error: Any, manifest: Optional[Dict[str, Any]] = None, max_length: int = 400) -> str:
    """Return an error message safe to show in the browser, with credentials removed."""
    message = str(error or "").strip()
    if not message:
        return "The connection test failed for an unknown reason."

    for secret_value in collect_manifest_secret_values(manifest):
        message = message.replace(secret_value, REDACTED_PLACEHOLDER)
        encoded_secret = base64.b64encode(secret_value.encode("utf-8", errors="ignore")).decode("ascii")
        if len(encoded_secret) >= 8:
            message = message.replace(encoded_secret, REDACTED_PLACEHOLDER)

    message = _SENSITIVE_ASSIGNMENT_PATTERN.sub(lambda match: f"{match.group(1)}={REDACTED_PLACEHOLDER}", message)
    message = _AUTHORIZATION_HEADER_PATTERN.sub(lambda match: f"{match.group(1)} {REDACTED_PLACEHOLDER}", message)
    message = re.sub(r"\s+", " ", message).strip()

    if len(message) > max_length:
        message = f"{message[:max_length].rstrip()}..."
    return message


def build_success_result(message: str, **details: Any) -> Dict[str, Any]:
    """Build a normalized successful action connection test result."""
    return {
        "success": True,
        "message": message,
        "status": 200,
        "details": {key: value for key, value in details.items() if value not in (None, "")},
    }


def build_failure_result(error: str, status: int = 400, **details: Any) -> Dict[str, Any]:
    """Build a normalized failed action connection test result."""
    return {
        "success": False,
        "error": error,
        "status": status,
        "details": {key: value for key, value in details.items() if value not in (None, "")},
    }


def _missing_package_result(package_key: str) -> Dict[str, Any]:
    """Build a friendly failure result for an uninstalled optional dependency."""
    return build_failure_result(_MISSING_PACKAGE_MESSAGES[package_key], status=501)


def _log_connection_test(plugin_type: str, result: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> None:
    """Emit low-sensitivity telemetry for an action connection test outcome."""
    context = {"plugin_type": plugin_type, "succeeded": bool(result.get("success"))}
    context.update(extra or {})
    if result.get("success"):
        log_event(f"[ACTION_TEST] {plugin_type} connection test succeeded", extra=context, level=logging.INFO)
        return
    context["status"] = result.get("status")
    log_event(f"[ACTION_TEST] {plugin_type} connection test failed", extra=context, level=logging.WARNING)


def _http_status_failure(status_code: int, auth_hint: str, not_found_hint: str, fallback_hint: str) -> Dict[str, Any]:
    """Map an upstream HTTP status onto an actionable failure result."""
    if status_code in (401, 403):
        return build_failure_result(auth_hint, status=403, http_status=status_code)
    if status_code == 404:
        return build_failure_result(not_found_hint, status=404, http_status=status_code)
    return build_failure_result(f"{fallback_hint} (HTTP {status_code}).", status=400, http_status=status_code)


def _build_openapi_probe_request(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Build headers, query params, and basic auth for the OpenAPI base URL probe."""
    from semantic_kernel_plugins.openapi_plugin_factory import OpenApiPluginFactory

    normalized_auth = OpenApiPluginFactory._extract_auth_config(manifest) or {}
    additional_fields = manifest.get("additionalFields") if isinstance(manifest.get("additionalFields"), dict) else {}
    auth_type = str(normalized_auth.get("type") or "none").strip().lower()

    headers: Dict[str, str] = {"Accept": "*/*"}
    params: Dict[str, str] = {}
    basic_auth = None

    if auth_type == "bearer":
        token = str(normalized_auth.get("token") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "basic":
        username = str(normalized_auth.get("username") or "")
        password = str(normalized_auth.get("password") or "")
        if username or password:
            basic_auth = (username, password)
    elif auth_type in ("key", "api_key"):
        key_value = str(normalized_auth.get("key") or normalized_auth.get("value") or "").strip()
        key_name = str(
            additional_fields.get("api_key_name")
            or normalized_auth.get("name")
            or "X-API-Key"
        ).strip() or "X-API-Key"
        key_location = str(
            additional_fields.get("api_key_location")
            or normalized_auth.get("location")
            or "header"
        ).strip().lower()
        if key_value:
            if key_location == "query":
                params[key_name] = key_value
            else:
                headers[key_name] = key_value

    return {"headers": headers, "params": params, "basic_auth": basic_auth, "auth_type": auth_type}


def test_openapi_connection(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an OpenAPI action by parsing its spec and probing the authenticated base URL."""
    from semantic_kernel_plugins.openapi_plugin_factory import OpenApiPluginFactory

    additional_fields = manifest.get("additionalFields") if isinstance(manifest.get("additionalFields"), dict) else {}
    base_url = str(manifest.get("endpoint") or additional_fields.get("base_url") or "").strip().rstrip("/")
    timeout = resolve_test_timeout(additional_fields.get("timeout"))

    if not base_url:
        return build_failure_result("A base URL is required before testing an OpenAPI action.")

    try:
        plugin = OpenApiPluginFactory.create_from_config(
            {
                "base_url": base_url,
                "endpoint": base_url,
                "auth": manifest.get("auth") or {},
                "additionalFields": additional_fields,
                "openapi_spec_content": additional_fields.get("openapi_spec_content"),
                "openapi_source_type": additional_fields.get("openapi_source_type"),
                "openapi_file_id": additional_fields.get("openapi_file_id"),
                "openapi_spec_path": additional_fields.get("openapi_spec_path"),
            }
        )
        operations = plugin.get_available_operations() or []
    except Exception as exc:
        result = build_failure_result(
            f"The OpenAPI specification could not be loaded: {sanitize_connection_error(exc, manifest)}"
        )
        _log_connection_test("openapi", result, {"stage": "spec_parse"})
        return result

    probe = _build_openapi_probe_request(manifest)
    try:
        response = request_public_https(
            "GET",
            base_url,
            headers=probe["headers"],
            params=probe["params"] or None,
            auth=probe["basic_auth"],
            timeout=timeout,
        )
    except (requests.RequestException, OutboundHttpPolicyError) as exc:
        result = build_failure_result(
            f"The API base URL could not be reached: {sanitize_connection_error(exc, manifest)}",
            status=502,
        )
        _log_connection_test("openapi", result, {"stage": "base_url_probe"})
        return result

    operation_count = len(operations)
    if response.status_code in (401, 403):
        result = build_failure_result(
            f"The API base URL responded with HTTP {response.status_code}. The specification parsed correctly, "
            "so verify the configured authentication credentials.",
            status=403,
            http_status=response.status_code,
            operation_count=operation_count,
        )
        _log_connection_test("openapi", result, {"stage": "base_url_probe", "http_status": response.status_code})
        return result

    result = build_success_result(
        f"Specification parsed with {operation_count} operation{'' if operation_count == 1 else 's'}. "
        f"The base URL responded with HTTP {response.status_code}.",
        operation_count=operation_count,
        http_status=response.status_code,
        auth_type=probe["auth_type"],
    )
    _log_connection_test("openapi", result, {"operation_count": operation_count, "http_status": response.status_code})
    return result


def test_azure_maps_connection(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an Azure Maps action by fetching a single base road tile."""
    auth = manifest.get("auth") if isinstance(manifest.get("auth"), dict) else {}
    subscription_key = str(auth.get("key") or "").strip()
    raw_endpoint = str(manifest.get("endpoint") or AZURE_MAPS_DEFAULT_ENDPOINT).strip()

    if not subscription_key:
        return build_failure_result("An Azure Maps subscription key is required before testing this action.")
    try:
        endpoint = validate_azure_maps_endpoint(raw_endpoint)
    except ValueError as exc:
        return build_failure_result(str(exc))

    try:
        # codeql[py/partial-ssrf]
        response = requests.get(
            f"{endpoint}/map/tile",
            params={
                "api-version": AZURE_MAPS_TILE_API_VERSION,
                "tilesetId": AZURE_MAPS_DEFAULT_TILESET_ID,
                "zoom": 0,
                "x": 0,
                "y": 0,
                "tileSize": "256",
                "language": AZURE_MAPS_DEFAULT_LANGUAGE,
                "view": AZURE_MAPS_DEFAULT_VIEW,
                "subscription-key": subscription_key,
            },
            timeout=ACTION_CONNECTION_TEST_DEFAULT_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        result = build_failure_result(
            f"Azure Maps could not be reached: {sanitize_connection_error(exc, manifest)}",
            status=502,
        )
        _log_connection_test("azure_maps_openlayers", result)
        return result

    if response.status_code == 200:
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if not content_type.startswith("image/"):
            result = build_failure_result(
                "Azure Maps returned a non-image response for the test tile. Confirm the endpoint is an Azure Maps account URL."
            )
            _log_connection_test("azure_maps_openlayers", result)
            return result

        result = build_success_result(
            f"Successfully retrieved an Azure Maps {AZURE_MAPS_DEFAULT_TILESET_ID} tile with the configured subscription key.",
            tileset_id=AZURE_MAPS_DEFAULT_TILESET_ID,
            http_status=response.status_code,
        )
        _log_connection_test("azure_maps_openlayers", result)
        return result

    result = _http_status_failure(
        response.status_code,
        "Azure Maps rejected the subscription key. Verify the key and confirm it belongs to the target Azure Maps account.",
        "Azure Maps could not find the tile endpoint. Verify the configured Azure Maps endpoint URL.",
        "The Azure Maps tile request failed",
    )
    _log_connection_test("azure_maps_openlayers", result, {"http_status": response.status_code})
    return result


def test_blob_storage_connection(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a Blob Storage action by reading container properties and listing one blob."""
    from azure.core.exceptions import ClientAuthenticationError, ResourceNotFoundError
    from semantic_kernel_plugins.blob_storage_plugin import BlobStoragePlugin

    try:
        plugin = BlobStoragePlugin(manifest)
    except ValueError as exc:
        result = build_failure_result(sanitize_connection_error(exc, manifest))
        _log_connection_test("blob_storage", result, {"stage": "configuration"})
        return result
    except Exception as exc:
        result = build_failure_result(
            f"The Blob Storage client could not be created: {sanitize_connection_error(exc, manifest)}"
        )
        _log_connection_test("blob_storage", result, {"stage": "client"})
        return result

    try:
        container_properties = plugin.container_client.get_container_properties()
    except ResourceNotFoundError:
        result = build_failure_result(
            f"Container '{plugin.container_name}' was not found in the configured storage account.",
            status=404,
        )
        _log_connection_test("blob_storage", result, {"stage": "container_read"})
        return result
    except ClientAuthenticationError as exc:
        result = build_failure_result(
            f"Storage authentication failed: {sanitize_connection_error(exc, manifest)}",
            status=403,
        )
        _log_connection_test("blob_storage", result, {"stage": "container_read"})
        return result
    except Exception as exc:
        result = build_failure_result(
            f"The Blob Storage container could not be read: {sanitize_connection_error(exc, manifest)}"
        )
        _log_connection_test("blob_storage", result, {"stage": "container_read"})
        return result

    try:
        blob_pages = plugin.container_client.list_blobs(
            name_starts_with=plugin.blob_prefix or None,
            results_per_page=1,
        ).by_page()
        listed_blobs = list(next(blob_pages, []))
    except Exception as exc:
        result = build_failure_result(
            f"The Blob Storage container could not be listed: {sanitize_connection_error(exc, manifest)}",
            status=403,
        )
        _log_connection_test("blob_storage", result, {"stage": "container_list"})
        return result

    prefix_label = f" under prefix '{plugin.blob_prefix}'" if plugin.blob_prefix else ""
    blob_label = "at least one blob" if listed_blobs else "no blobs yet"
    result = build_success_result(
        f"Connected to container '{plugin.container_name}' and found {blob_label}{prefix_label}.",
        container_name=plugin.container_name,
        blob_prefix=plugin.blob_prefix,
        last_modified=str(getattr(container_properties, "last_modified", "") or ""),
    )
    _log_connection_test("blob_storage", result)
    return result


def test_databricks_connection(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a Databricks action by reading the configured SQL warehouse."""
    from semantic_kernel_plugins.databricks_plugin_factory import DatabricksPluginFactory

    try:
        plugin = DatabricksPluginFactory.create_from_config(manifest)
    except ValueError as exc:
        result = build_failure_result(sanitize_connection_error(exc, manifest))
        _log_connection_test("databricks", result, {"stage": "configuration"})
        return result
    except Exception as exc:
        result = build_failure_result(
            f"The Databricks action configuration is invalid: {sanitize_connection_error(exc, manifest)}"
        )
        _log_connection_test("databricks", result, {"stage": "configuration"})
        return result

    timeout = resolve_test_timeout(plugin.timeout)
    try:
        headers = plugin._headers()
    except Exception as exc:
        result = build_failure_result(
            f"A Databricks access token could not be acquired: {sanitize_connection_error(exc, manifest)}",
            status=403,
        )
        _log_connection_test("databricks", result, {"stage": "token"})
        return result

    try:
        response = requests.get(
            f"{plugin.endpoint}/api/2.0/sql/warehouses/{plugin.warehouse_id}",
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        result = build_failure_result(
            f"The Databricks workspace could not be reached: {sanitize_connection_error(exc, manifest)}",
            status=502,
        )
        _log_connection_test("databricks", result, {"stage": "warehouse_read"})
        return result

    if response.status_code != 200:
        result = _http_status_failure(
            response.status_code,
            "Databricks rejected the configured credentials. Verify the token, service principal, or managed identity access to this workspace.",
            f"SQL warehouse '{plugin.warehouse_id}' was not found in this Databricks workspace.",
            "The Databricks warehouse lookup failed",
        )
        _log_connection_test("databricks", result, {"stage": "warehouse_read", "http_status": response.status_code})
        return result

    try:
        warehouse = response.json() or {}
    except ValueError:
        warehouse = {}

    warehouse_name = str(warehouse.get("name") or plugin.warehouse_id)
    warehouse_state = str(warehouse.get("state") or "UNKNOWN")
    result = build_success_result(
        f"Connected to Databricks SQL warehouse '{warehouse_name}' (state: {warehouse_state}).",
        warehouse_id=plugin.warehouse_id,
        warehouse_name=warehouse_name,
        warehouse_state=warehouse_state,
    )
    _log_connection_test("databricks", result, {"warehouse_state": warehouse_state})
    return result


def test_log_analytics_connection(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a Log Analytics action by running a trivial KQL query against the workspace."""
    try:
        from azure.monitor.query import LogsQueryStatus
    except ImportError:
        return _missing_package_result("log_analytics")

    from semantic_kernel_plugins.log_analytics_plugin import LogAnalyticsPlugin

    additional_fields = manifest.get("additionalFields") if isinstance(manifest.get("additionalFields"), dict) else {}
    workspace_id = str(additional_fields.get("workspaceId") or "").strip()
    if not workspace_id:
        return build_failure_result("A Log Analytics workspace ID is required before testing this action.")

    try:
        plugin = LogAnalyticsPlugin(manifest)
    except Exception as exc:
        result = build_failure_result(
            f"The Log Analytics client could not be created: {sanitize_connection_error(exc, manifest)}"
        )
        _log_connection_test("log_analytics", result, {"stage": "client"})
        return result

    if not plugin._client:
        result = build_failure_result(
            "A Log Analytics query client could not be created. Verify the workspace ID, cloud, and authentication settings."
        )
        _log_connection_test("log_analytics", result, {"stage": "client"})
        return result

    try:
        response = plugin._client.query_workspace(
            workspace_id=workspace_id,
            query="print TestConnection = 1",
            timespan=timedelta(minutes=5),
        )
    except Exception as exc:
        result = build_failure_result(
            f"The Log Analytics workspace query failed: {sanitize_connection_error(exc, manifest)}"
        )
        _log_connection_test("log_analytics", result, {"stage": "query"})
        return result

    query_status = getattr(response, "status", None)
    if query_status == LogsQueryStatus.FAILURE:
        partial_error = getattr(response, "partial_error", None)
        result = build_failure_result(
            f"The Log Analytics workspace rejected the test query: {sanitize_connection_error(partial_error or 'Unknown query failure.', manifest)}"
        )
        _log_connection_test("log_analytics", result, {"stage": "query"})
        return result

    cloud = str(additional_fields.get("cloud") or "public")
    result = build_success_result(
        f"Successfully queried Log Analytics workspace {workspace_id} in the {cloud} cloud.",
        workspace_id=workspace_id,
        cloud=cloud,
        query_status=str(query_status or "SUCCESS"),
    )
    _log_connection_test("log_analytics", result, {"cloud": cloud})
    return result


def test_mcp_connection(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an MCP action by initializing a session and listing the server's tools."""
    from semantic_kernel_plugins.mcp_plugin_factory import McpPluginFactory

    try:
        probe_result = asyncio.run(McpPluginFactory.probe_server_from_config(manifest))
    except Exception as exc:
        result = build_failure_result(
            f"The MCP server connection failed: {sanitize_connection_error(exc, manifest)}",
            status=502,
        )
        _log_connection_test("mcp", result)
        return result

    if not isinstance(probe_result, dict):
        result = build_failure_result("The MCP server returned an unexpected probe response.")
        _log_connection_test("mcp", result)
        return result

    tools = probe_result.get("tools") or []
    transport = str(probe_result.get("transport") or "")
    auth_method = str(probe_result.get("auth_method") or "")
    warnings = [str(warning) for warning in (probe_result.get("warnings") or []) if str(warning).strip()]

    message = (
        f"Connected over {transport or 'the configured transport'} and listed "
        f"{len(tools)} tool{'' if len(tools) == 1 else 's'}."
    )
    if warnings:
        message = f"{message} {' '.join(warnings)}"

    result = build_success_result(
        message,
        transport=transport,
        auth_method=auth_method,
        tool_count=len(tools),
    )
    result["warnings"] = warnings
    _log_connection_test("mcp", result, {"transport": transport, "tool_count": len(tools)})
    return result


def test_snowflake_connection(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a Snowflake action by opening a session and reading the account version."""
    from semantic_kernel_plugins.snowflake_plugin_factory import SnowflakePluginFactory

    try:
        plugin = SnowflakePluginFactory.create_from_config(manifest)
    except ValueError as exc:
        result = build_failure_result(sanitize_connection_error(exc, manifest))
        _log_connection_test("snowflake", result, {"stage": "configuration"})
        return result
    except Exception as exc:
        result = build_failure_result(
            f"The Snowflake action configuration is invalid: {sanitize_connection_error(exc, manifest)}"
        )
        _log_connection_test("snowflake", result, {"stage": "configuration"})
        return result

    connection = None
    cursor = None
    try:
        connection = plugin._connect()
        cursor = connection.cursor()
        cursor.execute("SELECT CURRENT_VERSION()")
        row = cursor.fetchone()
        snowflake_version = str(row[0]) if row else "unknown"
    except ImportError:
        result = _missing_package_result("snowflake")
        _log_connection_test("snowflake", result, {"stage": "driver"})
        return result
    except Exception as exc:
        result = build_failure_result(
            f"The Snowflake connection failed: {sanitize_connection_error(exc, manifest)}"
        )
        _log_connection_test("snowflake", result, {"stage": "connect"})
        return result
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                log_event(
                    "[ACTION_TEST] Snowflake test cursor could not be closed cleanly.",
                    level=logging.DEBUG,
                    debug_only=True,
                )
        if connection is not None:
            try:
                connection.close()
            except Exception:
                log_event(
                    "[ACTION_TEST] Snowflake test connection could not be closed cleanly.",
                    level=logging.DEBUG,
                    debug_only=True,
                )

    result = build_success_result(
        f"Connected to Snowflake account '{plugin.account}' using warehouse '{plugin.warehouse}' (version {snowflake_version}).",
        account=plugin.account,
        warehouse=plugin.warehouse,
        snowflake_version=snowflake_version,
    )
    _log_connection_test("snowflake", result)
    return result


def test_tableau_connection(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a Tableau action by signing in to the configured server and site."""
    from semantic_kernel_plugins.tableau_plugin_factory import TableauPluginFactory

    try:
        plugin = TableauPluginFactory.create_from_config(manifest)
    except ValueError as exc:
        result = build_failure_result(sanitize_connection_error(exc, manifest))
        _log_connection_test("tableau", result, {"stage": "configuration"})
        return result
    except Exception as exc:
        result = build_failure_result(
            f"The Tableau action configuration is invalid: {sanitize_connection_error(exc, manifest)}"
        )
        _log_connection_test("tableau", result, {"stage": "configuration"})
        return result

    try:
        plugin._require_tsc()
    except RuntimeError:
        result = _missing_package_result("tableau")
        _log_connection_test("tableau", result, {"stage": "driver"})
        return result

    try:
        server = plugin._create_server()
        tableau_auth = plugin._get_tableau_auth()
        with server.auth.sign_in(tableau_auth):
            server_version = str(getattr(server, "version", "") or "unknown")
            site_id = str(getattr(server, "site_id", "") or "")
    except Exception as exc:
        result = build_failure_result(
            f"The Tableau sign-in failed: {sanitize_connection_error(exc, manifest)}",
            status=403,
        )
        _log_connection_test("tableau", result, {"stage": "sign_in"})
        return result

    site_label = plugin.site_content_url or "the default site"
    result = build_success_result(
        f"Signed in to Tableau at {plugin.endpoint} on {site_label} (API version {server_version}).",
        server_version=server_version,
        site_content_url=plugin.site_content_url,
        site_id_present=bool(site_id),
    )
    _log_connection_test("tableau", result)
    return result
