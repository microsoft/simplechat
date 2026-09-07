#!/usr/bin/env python3
# test_action_app_identity_endpoint_hardening.py
"""
Functional test for action app-identity endpoint hardening.
Version: 0.260.006
Implemented in: 0.260.006

Actions can be configured with a caller-supplied endpoint while authenticating with the
application's own workload identity. This test ensures such endpoints are constrained to
canonical Azure service origins at save time and again at plugin construction, that the
per-type allowedAuthTypes contract is enforced server-side, and that Log Analytics custom
clouds cannot select an arbitrary token authority or OAuth resource.
"""

import ast
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _install_config_stub():
    """Stub config.py, which builds live Azure clients at import time.

    Names are harvested from the real module so `from config import *` consumers still
    resolve every symbol they expect.
    """
    if isinstance(sys.modules.get("config"), types.ModuleType) and hasattr(sys.modules["config"], "_is_test_stub"):
        return

    config_stub = types.ModuleType("config")
    config_stub._is_test_stub = True
    config_tree = ast.parse((APP_ROOT / "config.py").read_text(encoding="utf-8"))
    for node in ast.walk(config_tree):
        names = []
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [(alias.asname or alias.name).split(".")[0] for alias in node.names if alias.name != "*"]
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names = [node.name]
        for name in names:
            if hasattr(config_stub, name):
                continue
            try:
                setattr(config_stub, name, __import__(name))
            except Exception:
                setattr(config_stub, name, MagicMock(name=f"config.{name}"))
    sys.modules["config"] = config_stub


def read_text(relative_path):
    """Read a repository file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


# Endpoints that must never receive credentials minted from the application identity.
HOSTILE_ENDPOINTS = (
    "https://attacker.invalid",
    "https://evil.example.com",
    "https://169.254.169.254",
    "https://127.0.0.1",
    "https://localhost",
    "http://account.blob.core.windows.net",
    "https://user:pass@account.blob.core.windows.net",
    "https://account.blob.core.windows.net:8443",
    "https://account.blob.core.windows.net.evil.com",
    "https://account.blob.core.windows.net?x=1",
    "https://account.blob.core.windows.net#frag",
)


def test_version_and_definition_contract():
    """Validate the version bump and the blob storage auth type declaration."""
    import json

    assert_app_version_at_least("0.260.006")

    definition = json.loads(read_text("application/single_app/static/json/schemas/blob_storage.definition.json"))
    allowed = definition["allowedAuthTypes"]
    assert set(allowed) == {"connection_string", "identity", "key"}, allowed


def test_blob_and_queue_endpoint_allowlist():
    """Blob and queue endpoints must be canonical Azure Storage origins."""
    from functions_azure_endpoint_validation import (
        validate_azure_blob_endpoint,
        validate_azure_queue_endpoint,
    )

    assert validate_azure_blob_endpoint("https://acct.blob.core.windows.net") == "https://acct.blob.core.windows.net"
    assert validate_azure_blob_endpoint("https://acct.blob.core.usgovcloudapi.net/") == "https://acct.blob.core.usgovcloudapi.net"
    assert validate_azure_blob_endpoint("https://acct.blob.core.chinacloudapi.cn") == "https://acct.blob.core.chinacloudapi.cn"
    assert validate_azure_queue_endpoint("https://acct.queue.core.windows.net") == "https://acct.queue.core.windows.net"

    for hostile_endpoint in HOSTILE_ENDPOINTS:
        try:
            validate_azure_blob_endpoint(hostile_endpoint)
        except ValueError:
            continue
        raise AssertionError(f"Blob endpoint should have been rejected: {hostile_endpoint}")

    # A queue action must not be able to point at the blob service and vice versa.
    for mismatched_endpoint, validator in (
        ("https://acct.queue.core.windows.net", validate_azure_blob_endpoint),
        ("https://acct.blob.core.windows.net", validate_azure_queue_endpoint),
    ):
        try:
            validator(mismatched_endpoint)
        except ValueError:
            continue
        raise AssertionError(f"Cross-service endpoint should have been rejected: {mismatched_endpoint}")


def test_cosmos_databricks_and_monitor_endpoint_allowlist():
    """Cosmos, Databricks, Azure Monitor, and Entra authority values must be Azure origins."""
    from functions_azure_endpoint_validation import (
        validate_azure_cosmos_endpoint,
        validate_azure_databricks_endpoint,
        validate_azure_entra_authority_host,
        validate_azure_monitor_query_endpoint,
    )

    assert validate_azure_cosmos_endpoint("https://acct.documents.azure.com") == "https://acct.documents.azure.com"
    # Cosmos endpoints are commonly pasted with the default HTTPS port.
    assert validate_azure_cosmos_endpoint("https://acct.documents.azure.com:443/") == "https://acct.documents.azure.com"
    assert validate_azure_databricks_endpoint(
        "https://adb-1234567890123456.7.azuredatabricks.net"
    ) == "https://adb-1234567890123456.7.azuredatabricks.net"
    assert validate_azure_monitor_query_endpoint("https://api.loganalytics.io") == "https://api.loganalytics.io"
    assert validate_azure_entra_authority_host("https://login.microsoftonline.us") == "login.microsoftonline.us"

    rejections = (
        (validate_azure_cosmos_endpoint, "https://evil.example.com"),
        (validate_azure_cosmos_endpoint, "https://acct.documents.azure.com.evil.com"),
        (validate_azure_databricks_endpoint, "https://evil.example.com"),
        (validate_azure_databricks_endpoint, "https://adb-1.azuredatabricks.net.evil.com"),
        # Azure Resource Manager is the pivot target described in the report.
        (validate_azure_monitor_query_endpoint, "https://management.azure.com"),
        (validate_azure_monitor_query_endpoint, "https://evil.example.com"),
        (validate_azure_entra_authority_host, "https://evil.example.com"),
        (validate_azure_entra_authority_host, "https://login.microsoftonline.com.evil.com"),
    )
    for validator, hostile_value in rejections:
        try:
            validator(hostile_value)
        except ValueError:
            continue
        raise AssertionError(f"{validator.__name__} should have rejected {hostile_value}")


def test_allowed_auth_types_are_enforced_server_side():
    """A caller must not be able to declare an auth type its action type does not support."""
    from json_schema_validation import (
        get_allowed_auth_types_for_plugin_type,
        validate_plugin_auth_type_allowed,
    )

    assert get_allowed_auth_types_for_plugin_type("blob_storage") == {"connection_string", "identity", "key"}
    assert get_allowed_auth_types_for_plugin_type("openapi") == {"key"}
    # Unknown types fall back to the shared enum so they keep working.
    assert "identity" in get_allowed_auth_types_for_plugin_type("some_unknown_action_type")

    # The reported application boundary: an app-identity auth type on a type that never declared it.
    assert validate_plugin_auth_type_allowed({"type": "openapi", "auth": {"type": "identity"}})
    assert validate_plugin_auth_type_allowed({"type": "msgraph", "auth": {"type": "identity"}})

    # Legitimate configurations must keep working.
    for allowed_manifest in (
        {"type": "blob_storage", "auth": {"type": "connection_string", "key": "x"}},
        {"type": "blob_storage", "auth": {"type": "identity"}},
        {"type": "openapi", "auth": {"type": "key", "key": "x"}},
        {"type": "sql_query", "auth": {"type": "user"}},
        {"type": "sql_query", "auth": {"type": "servicePrincipal"}},
        {"type": "cosmos_query", "auth": {"type": "identity"}},
        # Legacy Databricks type resolves to the current type's contract.
        {"type": "databricks_table", "auth": {"type": "identity"}},
        # Identity-bound actions resolve auth server-side, so hydration output is exempt.
        {"type": "openapi", "auth": {"type": "username_password"}, "identity_id": "abc"},
    ):
        error = validate_plugin_auth_type_allowed(allowed_manifest)
        assert error is None, f"{allowed_manifest} unexpectedly rejected: {error}"


def test_manifest_validation_rejects_hostile_endpoints():
    """Save-time manifest validation must reject non-Azure endpoints for app-identity actions."""
    _install_config_stub()
    from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker

    def is_valid(manifest, plugin_type):
        valid, _ = PluginHealthChecker.validate_plugin_manifest(manifest, plugin_type)
        return valid

    blob_manifest = {"name": "b", "type": "blob_storage", "additionalFields": {"container_name": "c"}}
    assert not is_valid({**blob_manifest, "endpoint": "https://attacker.invalid", "auth": {"type": "identity"}}, "blob_storage")
    assert is_valid({**blob_manifest, "endpoint": "https://acct.blob.core.windows.net", "auth": {"type": "identity"}}, "blob_storage")

    # An endpoint derived from a stored connection string is validated too.
    hostile_connection_string = (
        "DefaultEndpointsProtocol=https;AccountName=a;AccountKey=k;BlobEndpoint=https://attacker.invalid"
    )
    assert not is_valid(
        {**blob_manifest, "auth": {"type": "connection_string", "key": hostile_connection_string}},
        "blob_storage",
    )

    queue_manifest = {"name": "q", "type": "queue_storage", "auth": {"type": "identity"}}
    assert not is_valid({**queue_manifest, "endpoint": "https://attacker.invalid"}, "queue_storage")
    assert is_valid({**queue_manifest, "endpoint": "https://acct.queue.core.windows.net"}, "queue_storage")

    cosmos_manifest = {
        "name": "c",
        "type": "cosmos_query",
        "auth": {"type": "identity"},
        "additionalFields": {"database_name": "d", "container_name": "c", "partition_key_path": "/id"},
    }
    assert not is_valid({**cosmos_manifest, "endpoint": "https://attacker.invalid"}, "cosmos_query")
    assert is_valid({**cosmos_manifest, "endpoint": "https://acct.documents.azure.com"}, "cosmos_query")

    databricks_manifest = {
        "name": "d",
        "type": "databricks",
        "auth": {"type": "identity", "identity": "managed_identity"},
        "additionalFields": {"cloud": "azure_commercial", "warehouse_id": "w"},
    }
    assert not is_valid({**databricks_manifest, "endpoint": "https://attacker.invalid"}, "databricks")
    assert is_valid(
        {**databricks_manifest, "endpoint": "https://adb-1234567890123456.7.azuredatabricks.net"},
        "databricks",
    )


def test_log_analytics_custom_cloud_is_constrained():
    """A custom Log Analytics cloud must not select the token authority or OAuth resource."""
    _install_config_stub()
    from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker

    def is_valid(additional_fields):
        valid, _ = PluginHealthChecker.validate_plugin_manifest(
            {"name": "l", "type": "log_analytics", "additionalFields": additional_fields},
            "log_analytics",
        )
        return valid

    assert not is_valid({
        "workspaceId": "w",
        "cloud": "custom",
        "authorityHost": "https://evil.example.com",
        "endpointOverride": "https://api.loganalytics.io",
    })
    # endpointOverride becomes the delegated-token scope, so ARM must be rejected.
    assert not is_valid({
        "workspaceId": "w",
        "cloud": "custom",
        "authorityHost": "https://login.microsoftonline.com",
        "endpointOverride": "https://management.azure.com",
    })
    assert is_valid({
        "workspaceId": "w",
        "cloud": "custom",
        "authorityHost": "https://login.microsoftonline.us",
        "endpointOverride": "https://api.loganalytics.us",
    })
    assert is_valid({"workspaceId": "w", "cloud": "public"})


def test_stored_hostile_actions_are_rejected_at_runtime():
    """Actions stored before this hardening must fail at plugin construction."""
    _install_config_stub()
    from semantic_kernel_plugins.blob_storage_plugin import BlobStoragePlugin
    from semantic_kernel_plugins.queue_storage_plugin import QueueStoragePlugin

    stored_hostile_blob = {
        "name": "stored",
        "type": "blob_storage",
        "endpoint": "https://attacker.invalid",
        "auth": {"type": "identity"},
        "additionalFields": {"container_name": "proof"},
    }
    try:
        BlobStoragePlugin(stored_hostile_blob)
    except ValueError:
        pass
    else:
        raise AssertionError("A stored hostile blob endpoint must not reach the Blob SDK client.")

    # The equivalent valid action must still construct.
    BlobStoragePlugin({**stored_hostile_blob, "endpoint": "https://acct.blob.core.windows.net"})

    stored_hostile_queue = {
        "name": "stored",
        "type": "queue_storage",
        "endpoint": "https://attacker.invalid",
        "auth": {"type": "identity"},
        "additional_settings": {"queue_name": "q1"},
    }
    try:
        QueueStoragePlugin(stored_hostile_queue)
    except ValueError:
        pass
    else:
        raise AssertionError("A stored hostile queue endpoint must not reach the Queue SDK client.")

    QueueStoragePlugin({**stored_hostile_queue, "endpoint": "https://acct.queue.core.windows.net"})


def test_runtime_validation_is_wired_into_credentialed_clients():
    """Each app-identity client construction site must revalidate its endpoint."""
    blob_source = read_text("application/single_app/semantic_kernel_plugins/blob_storage_plugin.py")
    queue_source = read_text("application/single_app/semantic_kernel_plugins/queue_storage_plugin.py")
    cosmos_source = read_text("application/single_app/semantic_kernel_plugins/cosmos_query_plugin.py")
    databricks_source = read_text("application/single_app/semantic_kernel_plugins/databricks_plugin.py")
    log_analytics_source = read_text("application/single_app/semantic_kernel_plugins/log_analytics_plugin.py")
    plugin_routes_source = read_text("application/single_app/route_backend_plugins.py")

    assert "validate_azure_blob_endpoint" in blob_source
    assert "account_url=self.endpoint" not in blob_source
    assert "validate_azure_queue_endpoint" in queue_source
    assert "account_url=self.endpoint" not in queue_source
    assert "validate_azure_cosmos_endpoint" in cosmos_source
    assert "validate_azure_databricks_endpoint" in databricks_source
    assert "validate_azure_entra_authority_host" in log_analytics_source
    assert "validate_azure_monitor_query_endpoint" in log_analytics_source
    # The raw caller-supplied authority must no longer flow straight into the credential.
    assert "authority_host = self.authority_host" not in log_analytics_source
    # The Cosmos test-connection route builds its own client and must validate independently.
    assert "validate_azure_cosmos_endpoint" in plugin_routes_source


def test_blob_storage_modal_exposes_identity_and_key():
    """The blob modal must offer the auth types the backend now accepts."""
    modal_source = read_text("application/single_app/templates/_plugin_modal.html")
    stepper_source = read_text("application/single_app/static/js/plugin_modal_stepper.js")

    for element_id in (
        "blob-storage-auth-type",
        "blob-storage-endpoint",
        "blob-storage-account-key",
        "blob-storage-connection-string-group",
        "blob-storage-endpoint-group",
        "blob-storage-account-key-group",
    ):
        assert element_id in modal_source, element_id

    assert "handleBlobStorageAuthTypeChange" in stepper_source
    assert "isAzureBlobEndpoint" in stepper_source
    assert "AZURE_STORAGE_ENDPOINT_SUFFIXES" in stepper_source
    # Visibility must use Bootstrap classes rather than inline display styles.
    toggle_body = stepper_source.split("handleBlobStorageAuthTypeChange() {", 1)[1][:600]
    assert "classList.toggle('d-none'" in toggle_body
    assert "style.display" not in toggle_body


def test_file_sync_reuses_the_shared_allowlist():
    """File Sync must source its Azure Storage allowlist from the shared module."""
    file_sync_source = read_text("application/single_app/functions_file_sync.py")

    assert "from functions_azure_endpoint_validation import" in file_sync_source
    assert "azure_storage_endpoint_suffix_for_hostname" in file_sync_source
    # The duplicated literal suffix tuple must be gone.
    assert 'AZURE_STORAGE_ENDPOINT_SUFFIXES = (' not in file_sync_source


if __name__ == "__main__":
    tests = [
        test_version_and_definition_contract,
        test_blob_and_queue_endpoint_allowlist,
        test_cosmos_databricks_and_monitor_endpoint_allowlist,
        test_allowed_auth_types_are_enforced_server_side,
        test_manifest_validation_rejects_hostile_endpoints,
        test_log_analytics_custom_cloud_is_constrained,
        test_stored_hostile_actions_are_rejected_at_runtime,
        test_runtime_validation_is_wired_into_credentialed_clients,
        test_blob_storage_modal_exposes_identity_and_key,
        test_file_sync_reuses_the_shared_allowlist,
    ]

    results = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as error:
            print(f"FAIL {test.__name__}: {error}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
