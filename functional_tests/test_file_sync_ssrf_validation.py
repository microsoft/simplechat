# test_file_sync_ssrf_validation.py
"""
Functional tests for File Sync SSRF endpoint and path boundaries.
Version: 0.261.312
Implemented in: 0.261.312

Azure Files must reject unapproved origins before token-credential/client
construction. OneDrive browse paths must remain under the configured Graph
origin. These tests execute production functions using the existing isolated
function loader, without importing Azure/Cosmos bootstrap or making network calls.
They do not establish live Azure connectivity or repair SDK authentication.
"""

import sys
import types
from unittest.mock import Mock
from urllib.parse import urlparse

import pytest
import requests

from test_file_sync_azure_blob_storage import load_functions
from functions_azure_endpoint_validation import (
    AZURE_STORAGE_ENDPOINT_SUFFIXES,
    validate_azure_file_endpoint,
)
from test_support.versioning import assert_app_version_at_least


HOSTILE_FILE_URLS = (
    "https://attacker.example",
    "https://localhost",
    "https://127.0.0.1",
    "https://169.254.169.254",
    "https://[::1]",
    "https://[fd00::1]",
    "http://account.file.core.windows.net",
    "https://account.file.core.windows.net@attacker.example",
    "https://user:password@account.file.core.windows.net",
    "https://account.file.core.windows.net:443",
    "https://account.file.core.windows.net:8443",
    "https://account.file.core.windows.net:invalid",
    "https://account.file.core.windows.net:99999",
    "https://account.file.core.windows.net.evil.example",
    "https://account.file.core.windows.net.",
    "https://account.privatelink.file.core.windows.net",
    "https://account.blob.core.windows.net",
    "https://account.queue.core.windows.net",
    "https://account.file.custom.example",
    "https://ab.file.core.windows.net",
    f"https://{'a' * 25}.file.core.windows.net",
    "https://bad-account.file.core.windows.net",
    "https://bad_account.file.core.windows.net",
    "https://extra.account.file.core.windows.net",
    "https://account.file.core.windows.net?x=1",
    "https://account.file.core.windows.net#fragment",
    "https://account.file.core.windows.net/share;parameter",
    "https://account.file.core.windows.net\\@attacker.example",
    "https://[invalid",
)


def file_functions(additional_globals=None):
    """Reuse the isolated loader; real validators run with mocked external I/O."""
    namespace = {
        "validate_azure_file_endpoint": validate_azure_file_endpoint,
    }
    namespace.update(additional_globals or {})
    return load_functions(
        "functions_file_sync.py",
        {
            "_normalize_text",
            "parse_file_sync_list",
            "_normalize_azure_file_url",
            "_normalize_azure_share_name",
            "_normalize_azure_directory_path",
            "_normalize_selected_path",
            "_normalize_selected_paths",
            "_build_azure_files_url",
            "_normalize_azure_files_connection",
            "_get_azure_files_service_client",
        },
        namespace,
    )


def test_implementation_version():
    assert_app_version_at_least("0.261.312")


@pytest.mark.parametrize("suffix", AZURE_STORAGE_ENDPOINT_SUFFIXES)
@pytest.mark.parametrize("scheme", ("https://", ""))
def test_azure_files_canonical_service_and_share_urls(suffix, scheme):
    functions = file_functions()
    host = f"account.file.{suffix}"
    service_url = f"https://{host}"
    normalized = functions["_normalize_azure_file_url"](f"{scheme}{host.upper()}/")
    assert normalized == (service_url, [])

    connection = functions["_normalize_azure_files_connection"]({
        "share_url": f"{scheme}{host.upper()}/documents/Quarterly%20reports/Team",
        "selected_paths": ["one.txt", "folder\\two.txt"],
    })
    assert connection == {
        "account_url": service_url,
        "share_name": "documents",
        "directory_path": "Quarterly reports/Team",
        "share_url": f"{service_url}/documents/Quarterly%20reports/Team",
        "selected_paths": ["one.txt", "folder/two.txt"],
    }
    retained = functions["_normalize_azure_files_connection"]({}, connection)
    assert retained == connection


@pytest.mark.parametrize("url", HOSTILE_FILE_URLS)
def test_azure_files_rejects_unsafe_submitted_urls(url):
    functions = file_functions()
    with pytest.raises(ValueError):
        validate_azure_file_endpoint(url)
    with pytest.raises(ValueError):
        functions["_normalize_azure_file_url"](url)
    with pytest.raises(ValueError):
        functions["_normalize_azure_files_connection"]({
            "account_url": url,
            "share_name": "documents",
        })


@pytest.fixture
def files_client_boundary(monkeypatch):
    sdk_module = types.ModuleType("azure.storage.fileshare")
    sdk_module.ShareServiceClient = Mock(name="ShareServiceClient")
    monkeypatch.setitem(sys.modules, "azure.storage.fileshare", sdk_module)
    managed_credential = Mock(name="DefaultAzureCredential")
    secret_credential = Mock(name="ClientSecretCredential")
    resolve_secret = Mock(return_value="test-secret")
    functions = file_functions({
        "_get_identity_auth_for_source": lambda source: source.get("auth"),
        "_resolved_auth_secret": resolve_secret,
        "DefaultAzureCredential": managed_credential,
        "ClientSecretCredential": secret_credential,
        "TENANT_ID": "test-tenant",
    })
    return functions, sdk_module.ShareServiceClient, managed_credential, secret_credential, resolve_secret


@pytest.mark.parametrize("auth_type", ("managed_identity", "client_secret"))
@pytest.mark.parametrize("url", HOSTILE_FILE_URLS + (
    "",
    "https://account.file.core.windows.net/documents",
    "https://account.file.core.windows.net/documents/folder",
))
def test_azure_files_revalidates_persisted_urls_before_credentials(files_client_boundary, auth_type, url):
    functions, client, managed_credential, secret_credential, resolve_secret = files_client_boundary
    with pytest.raises(ValueError):
        functions["_get_azure_files_service_client"]({
            "connection": {"account_url": url},
            "auth": {"auth_type": auth_type, "identity": "test-client"},
        })
    client.assert_not_called()
    managed_credential.assert_not_called()
    secret_credential.assert_not_called()
    resolve_secret.assert_not_called()


@pytest.mark.parametrize("auth_type", ("managed_identity", "client_secret"))
@pytest.mark.parametrize("suffix", AZURE_STORAGE_ENDPOINT_SUFFIXES)
def test_azure_files_sdk_receives_only_canonical_origins(files_client_boundary, auth_type, suffix):
    functions, client, managed_credential, secret_credential, resolve_secret = files_client_boundary
    result = functions["_get_azure_files_service_client"]({
        "connection": {"account_url": f"https://ACCOUNT.FILE.{suffix.upper()}/"},
        "auth": {
            "auth_type": auth_type,
            "identity": "test-client",
            "tenant_id": "test-tenant",
            "managed_identity_client_id": "test-managed-client",
        },
    })
    credential_factory = managed_credential if auth_type == "managed_identity" else secret_credential
    assert result is client.return_value
    client.assert_called_once_with(
        account_url=f"https://account.file.{suffix}",
        credential=credential_factory.return_value,
    )
    if auth_type == "managed_identity":
        managed_credential.assert_called_once_with(managed_identity_client_id="test-managed-client")
        secret_credential.assert_not_called()
        resolve_secret.assert_not_called()
    else:
        secret_credential.assert_called_once_with(
            tenant_id="test-tenant", client_id="test-client", client_secret="test-secret",
        )
        managed_credential.assert_not_called()


def test_azure_files_connection_string_dispatch_is_unchanged(files_client_boundary):
    functions, client, managed_credential, secret_credential, resolve_secret = files_client_boundary
    result = functions["_get_azure_files_service_client"]({
        "connection": {},
        "auth": {"auth_type": "connection_string"},
    })
    assert result is client.from_connection_string.return_value
    client.from_connection_string.assert_called_once_with("test-secret")
    client.assert_not_called()
    managed_credential.assert_not_called()
    secret_credential.assert_not_called()
    resolve_secret.assert_called_once()


def onedrive_functions(graph_base):
    """Execute Graph path building and the browse dispatch with a mocked HTTP sink."""
    prepared_requests = []
    response = Mock(status_code=200)
    response.json.return_value = {"value": []}

    def get(url, **kwargs):
        prepared = requests.Request(
            "GET", url, headers=kwargs.get("headers"), params=kwargs.get("params"),
        ).prepare()
        prepared_requests.append(prepared)
        return response

    graph_functions = load_functions(
        "functions_authentication.py",
        {"get_graph_endpoint"},
        {"get_graph_base_url": lambda: graph_base},
    )
    source = {
        "scope_type": "personal",
        "user_id": "authenticated-user",
        "source_type": "onedrive",
    }
    functions = load_functions(
        "functions_file_sync.py",
        {
            "_normalize_text", "_normalize_selected_path",
            "_validate_scope", "_scope_field", "_source_scope_id",
            "_quote_graph_path", "_onedrive_user_path",
            "_onedrive_children_path", "_iter_onedrive_children",
            "_browse_onedrive_path", "_graph_get_json", "browse_file_sync_source_path",
        },
        {
            "requests": types.SimpleNamespace(get=Mock(side_effect=get)),
            "get_graph_endpoint": graph_functions["get_graph_endpoint"],
            "_onedrive_headers": lambda: {"Accept": "application/json"},
            "_build_connection_test_source": lambda *args, **kwargs: source,
            "FILE_SYNC_SCOPE_PERSONAL": "personal",
            "FILE_SYNC_SCOPE_GROUP": "group",
            "FILE_SYNC_SCOPE_PUBLIC": "public",
            "FILE_SYNC_SCOPES": {"personal", "group", "public"},
            "FILE_SYNC_SOURCE_TYPE_ONEDRIVE": "onedrive",
        },
    )
    return functions, prepared_requests


@pytest.mark.parametrize("graph_base", (
    "https://graph.microsoft.com/v1.0",
    "https://graph.microsoft.us/v1.0",
))
@pytest.mark.parametrize("browse_path, encoded_path", (
    ("", ""),
    ("Quarterly reports/notes.txt", "Quarterly%20reports/notes.txt"),
    ("notes?x=1#fragment", "notes%3Fx%3D1%23fragment"),
    ("%2e%2e/%2f%2fevil.example", "%252e%252e/%252f%252fevil.example"),
    ("//evil.example/folder", "evil.example/folder"),
    ("https:/evil.example/folder", "https%3A/evil.example/folder"),
    ("name:/children", "name%3A/children"),
    ("folder\\notes.txt", "folder/notes.txt"),
))
def test_onedrive_browse_paths_cannot_change_graph_origin(graph_base, browse_path, encoded_path):
    functions, prepared_requests = onedrive_functions(graph_base)
    result = functions["browse_file_sync_source_path"](
        "personal", "authenticated-user",
        {"browse_path": browse_path, "user_id": "attacker-supplied-user"},
        "authenticated-user",
    )
    assert result["success"] is True
    assert len(prepared_requests) == 1
    prepared_url = prepared_requests[0].url
    parsed = urlparse(prepared_url)
    assert parsed.scheme == "https"
    assert parsed.netloc == urlparse(graph_base).netloc
    suffix = f"/root:/{encoded_path}:/children" if encoded_path else "/root/children"
    assert prepared_url.split("?")[0] == f"{graph_base}/users/authenticated-user/drive{suffix}"
    assert not parsed.fragment


@pytest.mark.parametrize("browse_path", (
    "..", "../folder", "folder/..", "./folder", "folder/./item",
    "folder//item", "folder\\..\\item", "https://evil.example/folder",
))
def test_onedrive_invalid_browse_paths_fail_before_http(browse_path):
    functions, prepared_requests = onedrive_functions("https://graph.microsoft.com/v1.0")
    with pytest.raises(ValueError, match="inside the configured source root"):
        functions["browse_file_sync_source_path"](
            "personal", "authenticated-user", {"browse_path": browse_path}, "authenticated-user",
        )
    functions["requests"].get.assert_not_called()
    assert prepared_requests == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
