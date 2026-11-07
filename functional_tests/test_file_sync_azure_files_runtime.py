# test_file_sync_azure_files_runtime.py
"""
Functional tests for the Azure Files token-authenticated SDK boundary.
Version: 0.261.359
Implemented in: 0.261.358

Execute production connector functions with the real pinned SDK and an offline
HTTP transport. Credentials, workspace storage, and network access are isolated;
the SDK constructor, pagination, metadata, and download pipeline remain real.
"""

import ast
from contextlib import contextmanager
import hashlib
import logging
from pathlib import Path
import socket
import subprocess
import sys
import time
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

from azure.core.credentials import AccessToken
from azure.core import exceptions as azure_exceptions
from azure.core.exceptions import ResourceNotFoundError
from azure.core.pipeline.transport import HttpResponse, HttpTransport
from azure.storage import fileshare
import pytest
from requests.structures import CaseInsensitiveDict

from test_file_sync_azure_blob_storage import load_functions, parse_app
from test_support.versioning import assert_app_version_at_least
from functions_azure_endpoint_validation import validate_azure_file_endpoint


class OfflineCredential:
    def __init__(self, **kwargs):
        self.options = kwargs

    def get_token(self, *scopes, **kwargs):
        return AccessToken("offline-placeholder", int(time.time()) + 3600)


class OfflineResponse(HttpResponse):
    def __init__(self, request, body=b"", headers=None):
        super().__init__(request, None)
        self.status_code = 200
        self.reason = "OK"
        self.headers = CaseInsensitiveDict(headers or {})
        self.content_type = self.headers.get("Content-Type")
        self._body = body

    def body(self):
        return self._body

    def stream_download(self, pipeline, **kwargs):
        class Stream(list):
            pass

        return Stream([self._body])


class OfflineTransport(HttpTransport):
    content = b"# Policy\nImport only approved documents.\n"

    def __init__(self):
        self.requests = []

    def open(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def send(self, request, **kwargs):
        self.requests.append(request)
        query = parse_qs(urlparse(request.url).query)
        if query.get("comp") == ["list"]:
            marker = "" if "marker" in query else "page-two"
            entry = "" if "marker" in query else (
                "<File><Name>policy.md</Name><Properties>"
                f"<Content-Length>{len(self.content)}</Content-Length>"
                "</Properties></File>"
            )
            xml = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<EnumerationResults ServiceEndpoint="https://account.file.core.windows.net/"'
                ' ShareName="documents" DirectoryPath="team">'
                f"<Entries>{entry}</Entries><NextMarker>{marker}</NextMarker>"
                "</EnumerationResults>"
            )
            return OfflineResponse(request, xml.encode(), {"Content-Type": "application/xml"})
        headers = {
            "Content-Length": str(len(self.content)),
            "Content-Type": "application/octet-stream",
            "ETag": '"offline-etag"',
            "Last-Modified": "Tue, 20 Oct 2026 02:00:00 GMT",
            "x-ms-type": "file",
            "x-ms-file-type": "file",
        }
        if request.method == "GET":
            headers["Content-Range"] = f"bytes 0-{len(self.content) - 1}/{len(self.content)}"
        return OfflineResponse(request, self.content if request.method == "GET" else b"", headers)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Azure Files regression attempted real network access")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


def connector_functions(**overrides):
    namespace = {
        "contextmanager": contextmanager,
        "logging": logging,
        "azure_exceptions": azure_exceptions,
        "AzureResourceNotFoundError": ResourceNotFoundError,
        "validate_azure_file_endpoint": validate_azure_file_endpoint,
        "_get_identity_auth_for_source": lambda source: None,
        "_resolved_auth_secret": lambda auth: auth.get("secret", ""),
        "DefaultAzureCredential": OfflineCredential,
        "ClientSecretCredential": OfflineCredential,
        "TENANT_ID": "offline-tenant",
        "log_event": Mock(),
    }
    classes = ast.Module(body=[
        node for node in parse_app("functions_file_sync.py").body
        if isinstance(node, ast.ClassDef) and node.name == "FileSyncPublicValidationError"
    ], type_ignores=[])
    exec(compile(classes, "functions_file_sync.py", "exec"), namespace)
    namespace.update(overrides)
    functions = load_functions("functions_file_sync.py", {
        "_normalize_text", "_normalize_azure_file_url", "_get_azure_files_service_client",
        "_get_azure_files_share_client", "_test_azure_files_connection",
        "_browse_azure_files_path", "_list_azure_files", "_stage_azure_files_file",
        "_azure_files_item_is_directory", "_azure_files_item_name", "_azure_files_item_size",
        "_azure_files_item_modified_at", "_azure_files_item_change_token",
        "_format_smb_modified_at",
        "_join_azure_file_path", "_relative_azure_file_path", "_join_selected_azure_file_path",
        "_build_azure_files_url", "_azure_files_operation", "_azure_files_error_details",
        "_normalize_azure_storage_error_code",
    }, namespace)
    functions.update(overrides)
    return functions


@pytest.fixture
def sdk_boundary(monkeypatch):
    transport = OfflineTransport()
    real_client = fileshare.ShareServiceClient

    class OfflineServiceClient(real_client):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, transport=transport, retry_total=0)

    monkeypatch.setattr(fileshare, "ShareServiceClient", OfflineServiceClient)
    return transport


def source(auth_type="managed_identity", scope="personal", saved=False):
    return {
        "source_type": "azure_files",
        "scope_type": scope,
        {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}[scope]: "owner",
        "identity_id": "saved-identity" if saved else "",
        "recursive": False,
        "connection": {
            "account_url": "https://account.file.core.windows.net",
            "share_name": "documents", "directory_path": "team",
        },
        "auth": {
            "auth_type": auth_type, "identity": "offline-client",
            "tenant_id": "offline-tenant", "secret": "offline-secret",
        },
    }


@pytest.mark.parametrize("auth_type", ["managed_identity", "client_secret"])
@pytest.mark.parametrize("scope", ["personal", "group", "public"])
@pytest.mark.parametrize("saved", [False, True])
def test_real_sdk_accepts_token_credentials(sdk_boundary, auth_type, scope, saved):
    item = source(auth_type, scope, saved)
    identity_auth = item["auth"]
    if saved:
        item["auth"] = {}
    resolve_identity = Mock(return_value=identity_auth if saved else None)
    functions = connector_functions(_get_identity_auth_for_source=resolve_identity)
    client = functions["_get_azure_files_share_client"](item)
    assert client.file_request_intent == "backup"
    assert isinstance(client.credential, OfflineCredential)
    if auth_type == "client_secret":
        assert client.credential.options == {
            "tenant_id": "offline-tenant", "client_id": "offline-client",
            "client_secret": "offline-secret",
        }
    assert sdk_boundary.requests == []
    resolve_identity.assert_called_once_with(item)
    client.close()


@pytest.mark.parametrize("client_id", ["", "user-assigned-client"])
def test_managed_identity_selection_is_preserved(sdk_boundary, client_id):
    item = source()
    item["auth"]["managed_identity_client_id"] = client_id
    client = connector_functions()["_get_azure_files_service_client"](item)
    assert client.credential.options == {"managed_identity_client_id": client_id or None}
    client.close()


@pytest.mark.parametrize("auth_type", ["managed_identity", "client_secret"])
@pytest.mark.parametrize("operation", ["test", "browse", "list", "stage"])
def test_connector_operations_send_backup_intent(sdk_boundary, auth_type, operation):
    functions = connector_functions()
    item = source(auth_type)
    if operation == "test":
        result = functions["_test_azure_files_connection"](item)
        assert result["success"] and result["files_seen"] == 1
    elif operation == "browse":
        result = functions["_browse_azure_files_path"](item, "")
        assert result[0]["path"] == "policy.md"
    elif operation == "list":
        result = functions["_list_azure_files"](item, {"file_sync_max_files_per_run": 10})
        assert result[0]["azure_file_path"] == "team/policy.md"
        assert result[0]["size"] == len(sdk_boundary.content)
    else:
        path, digest = functions["_stage_azure_files_file"](item, {
            "azure_file_path": "team/policy.md", "file_name": "policy.md",
        })
        try:
            assert Path(path).read_bytes() == sdk_boundary.content
            assert digest == hashlib.sha256(sdk_boundary.content).hexdigest()
        finally:
            Path(path).unlink()
    assert sdk_boundary.requests
    assert all(request.headers["x-ms-file-request-intent"] == "backup" for request in sdk_boundary.requests)
    if operation != "stage":
        listings = [request for request in sdk_boundary.requests if "comp=list" in request.url]
        assert len(listings) == 2
        assert "marker=page-two" in listings[1].url


def test_connection_string_does_not_require_token_intent(sdk_boundary):
    item = source("connection_string")
    item["auth"]["secret"] = (
        "DefaultEndpointsProtocol=https;AccountName=account;"
        "AccountKey=b2ZmbGluZQ==;EndpointSuffix=core.windows.net"
    )
    client = connector_functions()["_get_azure_files_service_client"](item)
    assert client.file_request_intent is None
    assert client.account_name == "account"
    client.close()


def test_implementation_version():
    assert_app_version_at_least("0.261.358")


@pytest.mark.parametrize("optimized", [False, True])
def test_required_sdk_operations_survive_optimized_python(optimized):
    probe = r'''
import socket
from pathlib import Path
from unittest.mock import patch
from test_file_sync_azure_files_runtime import connector_functions, source, OfflineTransport
from azure.storage import fileshare
def blocked(*args, **kwargs):
    raise RuntimeError("Network access forbidden")
transport = OfflineTransport()
real_client = fileshare.ShareServiceClient
class Client(real_client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, transport=transport, retry_total=0)
with patch.object(socket.socket, "connect", blocked), patch.object(socket, "getaddrinfo", blocked), patch.object(fileshare, "ShareServiceClient", Client):
    functions = connector_functions()
    item = source()
    connected = functions["_test_azure_files_connection"](item)
    entries = functions["_browse_azure_files_path"](item, "")
    files = functions["_list_azure_files"](item, {"file_sync_max_files_per_run": 10})
    path, digest = functions["_stage_azure_files_file"](item, {"file_name": "policy.md"})
    try:
        if not connected["success"] or len(entries) != 1 or len(files) != 1:
            raise RuntimeError("Required listing operations did not complete")
        if Path(path).read_bytes() != transport.content or not digest:
            raise RuntimeError("Required download did not complete")
        if not transport.requests or any(r.headers.get("x-ms-file-request-intent") != "backup" for r in transport.requests):
            raise RuntimeError("Required intent missing")
    finally:
        Path(path).unlink()
print("offline-sdk-probe-passed")
'''
    command = [sys.executable, *(["-O"] if optimized else []), "-c", probe]
    completed = subprocess.run(command, cwd=Path(__file__).parent, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "offline-sdk-probe-passed" in completed.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
