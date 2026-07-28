#!/usr/bin/env python3
# test_file_sync_azure_blob_storage.py
"""
Functional test for Azure Blob Storage File Sync.
Version: 0.250.068
Implemented in: 0.250.067
Security hardening in: 0.250.068

This test ensures Azure Blob Storage is wired into the shared File Sync
pipeline for every supported workspace scope without requiring live Azure
Storage or Cosmos DB access.
"""

import ast
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    """Read a repository file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def parse_app(relative_path):
    """Parse an application module with AST."""
    return ast.parse(read_text(f"application/single_app/{relative_path}"))


def function_names(parsed):
    """Return function names from a parsed module."""
    return {node.name for node in ast.walk(parsed) if isinstance(node, ast.FunctionDef)}


def load_functions(relative_path, names, additional_globals=None):
    """Load selected top-level functions without importing application config."""
    parsed = parse_app(relative_path)
    selected_nodes = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Tuple": Tuple,
        "hashlib": hashlib,
        "json": json,
        "os": os,
        "quote": quote,
        "re": re,
        "tempfile": tempfile,
        "unquote": unquote,
        "urlparse": urlparse,
    }
    namespace.update(additional_globals or {})
    exec(compile(module, relative_path, "exec"), namespace)
    return namespace


def test_version_and_dependency_pin():
    """Validate the app version and existing Azure Blob SDK dependency pin."""
    config_text = read_text("application/single_app/config.py")
    requirements_text = read_text("application/single_app/requirements.txt")

    assert 'VERSION = "0.250.068"' in config_text
    assert "azure-storage-blob==12.24.1" in requirements_text


def test_file_sync_backend_azure_blob_wiring():
    """Validate Azure Blob connector helpers and shared dispatch exist."""
    file_sync_text = read_text("application/single_app/functions_file_sync.py")
    names = function_names(parse_app("functions_file_sync.py"))

    expected_functions = {
        "_assert_azure_blob_auth_storage",
        "_normalize_azure_blob_connection",
        "_test_azure_blob_connection",
        "_get_azure_blob_service_client",
        "_get_azure_blob_container_client",
        "_browse_azure_blob_path",
        "_list_azure_blobs",
        "_stage_azure_blob_file",
        "_list_remote_files",
        "_stage_remote_file",
    }
    assert expected_functions.issubset(names)
    assert 'FILE_SYNC_SOURCE_TYPE_AZURE_BLOB = "azure_blob"' in file_sync_text
    assert 'FILE_SYNC_SOURCE_TYPE_AZURE_BLOB: {"managed_identity", "client_secret", "connection_string"}' in file_sync_text
    assert "BlobServiceClient.from_connection_string" in file_sync_text
    assert "DefaultAzureCredential(managed_identity_client_id=" in file_sync_text
    assert "ClientSecretCredential(" in file_sync_text
    assert '"remote_change_token":' in file_sync_text
    assert '"azure_blob_name":' in file_sync_text
    assert "downloader.chunks()" in file_sync_text
    assert "Azure Blob Storage secret credentials must be stored in Azure Key Vault" in file_sync_text


def test_azure_blob_connection_contract():
    """Validate storage account, container, and prefix fields are represented."""
    file_sync_text = read_text("application/single_app/functions_file_sync.py")

    for marker in [
        '"account_url": account_url',
        '"container_name": container_name',
        '"blob_prefix": blob_prefix',
        '"selected_paths": _normalize_selected_paths',
        "list_blobs(name_starts_with=",
        "walk_blobs(name_starts_with=",
        "get_container_properties()",
    ]:
        assert marker in file_sync_text


def test_azure_blob_connection_normalization_behavior():
    """Validate account names, URLs, containers, prefixes, and selected paths."""
    names = {
        "parse_file_sync_list",
        "_normalize_text",
        "_normalize_selected_path",
        "_normalize_selected_paths",
        "_azure_blob_endpoint_suffix_for_hostname",
        "_normalize_azure_blob_url",
        "_normalize_azure_container_name",
        "_normalize_azure_blob_connection",
    }
    functions = load_functions(
        "functions_file_sync.py",
        names,
        {"AZURE_STORAGE_ENDPOINT_SUFFIXES": ("core.windows.net",)},
    )
    normalize_connection = functions["_normalize_azure_blob_connection"]

    normalized = normalize_connection({
        "account_name": "contosodata",
        "container_name": "documents",
        "blob_prefix": "incoming/reports/",
        "selected_paths": ["2025", "2025", "2026/q1"],
    })
    assert normalized == {
        "account_url": "https://contosodata.blob.core.windows.net",
        "container_name": "documents",
        "blob_prefix": "incoming/reports",
        "selected_paths": ["2025", "2026/q1"],
    }

    url_normalized = normalize_connection({
        "account_url": "https://contosodata.blob.core.windows.net/archive/exports",
    })
    assert url_normalized["container_name"] == "archive"
    assert url_normalized["blob_prefix"] == "exports"

    root_normalized = normalize_connection({
        "account_name": "contosodata",
        "container_name": "$root",
    })
    assert root_normalized["container_name"] == "$root"

    try:
        normalize_connection({"account_name": "contosodata", "container_name": "Invalid_Name"})
        raise AssertionError("Invalid container names must be rejected")
    except ValueError as exc:
        assert "container name" in str(exc)


def test_azure_blob_endpoints_block_server_side_request_forgery():
    """Validate Blob URLs and connection strings stay on Azure-owned endpoints."""
    endpoint_suffixes = (
        "core.windows.net",
        "core.usgovcloudapi.net",
        "core.chinacloudapi.cn",
        "core.cloudapi.de",
    )
    functions = load_functions(
        "functions_file_sync.py",
        {
            "_normalize_text",
            "_azure_blob_endpoint_suffix_for_hostname",
            "_normalize_azure_blob_url",
            "_validate_azure_blob_connection_string",
        },
        {"AZURE_STORAGE_ENDPOINT_SUFFIXES": endpoint_suffixes},
    )
    normalize_url = functions["_normalize_azure_blob_url"]
    validate_connection_string = functions["_validate_azure_blob_connection_string"]

    allowed_urls = [
        "https://contosodata.blob.core.windows.net",
        "https://contosodata.blob.core.usgovcloudapi.net",
        "https://contosodata.blob.core.chinacloudapi.cn",
        "https://contosodata.blob.core.cloudapi.de",
    ]
    for allowed_url in allowed_urls:
        normalized_url, path_parts = normalize_url(allowed_url)
        assert normalized_url == allowed_url
        assert path_parts == []

    blocked_urls = [
        "https://127.0.0.1",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost",
        "https://internal.example.com",
        "https://contosodata.blob.core.windows.net.evil.example",
        "https://user:password@contosodata.blob.core.windows.net",
        "https://contosodata.blob.core.windows.net:444",
        "https://contosodata.blob.core.windows.net?sig=secret",
        "https://contosodata.blob.core.windows.net#fragment",
    ]
    for blocked_url in blocked_urls:
        try:
            normalize_url(blocked_url)
            raise AssertionError(f"Unsafe Blob URL was accepted: {blocked_url}")
        except ValueError as exc:
            assert "Azure Blob Storage" in str(exc)

    validate_connection_string(
        "DefaultEndpointsProtocol=https;AccountName=contosodata;"
        "AccountKey=ZmFrZQ==;EndpointSuffix=core.windows.net"
    )
    validate_connection_string(
        "BlobEndpoint=https://contosodata.blob.core.windows.net;"
        "SharedAccessSignature=sv=fake&sig=secret"
    )
    blocked_connection_strings = [
        "UseDevelopmentStorage=true",
        "DefaultEndpointsProtocol=http;AccountName=contosodata;AccountKey=ZmFrZQ==;EndpointSuffix=core.windows.net",
        "DefaultEndpointsProtocol=https;AccountName=contosodata;AccountKey=ZmFrZQ==;EndpointSuffix=example.com",
        "BlobEndpoint=https://127.0.0.1;SharedAccessSignature=sv=fake&sig=secret",
        "BlobEndpoint=https://internal.example.com;SharedAccessSignature=sv=fake&sig=secret",
    ]
    for connection_string in blocked_connection_strings:
        try:
            validate_connection_string(connection_string)
            raise AssertionError("Unsafe Blob connection string was accepted")
        except ValueError as exc:
            assert "Azure Blob Storage" in str(exc)


def test_azure_blob_service_client_revalidates_endpoints_before_sdk_use():
    """Validate stored endpoint values cannot bypass checks at the SDK boundary."""
    endpoint_suffixes = ("core.windows.net",)

    class FakeBlobServiceClient:
        constructor_calls = []
        connection_string_calls = []

        def __init__(self, account_url, credential):
            self.constructor_calls.append((account_url, credential))

        @classmethod
        def from_connection_string(cls, connection_string):
            cls.connection_string_calls.append(connection_string)
            return cls("from-connection-string", None)

    functions = load_functions(
        "functions_file_sync.py",
        {
            "_normalize_text",
            "_azure_blob_endpoint_suffix_for_hostname",
            "_normalize_azure_blob_url",
            "_validate_azure_blob_connection_string",
            "_get_azure_blob_service_client",
        },
        {
            "AZURE_STORAGE_ENDPOINT_SUFFIXES": endpoint_suffixes,
            "BlobServiceClient": FakeBlobServiceClient,
            "DefaultAzureCredential": lambda managed_identity_client_id=None: {
                "managed_identity_client_id": managed_identity_client_id,
            },
            "ClientSecretCredential": lambda **kwargs: kwargs,
            "TENANT_ID": "tenant",
            "_get_identity_auth_for_source": lambda source: None,
            "_resolved_auth_secret": lambda auth: str(auth.get("secret") or ""),
        },
    )
    get_service_client = functions["_get_azure_blob_service_client"]

    safe_source = {
        "connection": {"account_url": "https://contosodata.blob.core.windows.net"},
        "auth": {"auth_type": "managed_identity"},
    }
    get_service_client(safe_source)
    assert FakeBlobServiceClient.constructor_calls == [
        ("https://contosodata.blob.core.windows.net", {"managed_identity_client_id": None})
    ]

    unsafe_sources = [
        {
            "connection": {"account_url": "https://169.254.169.254/latest/meta-data"},
            "auth": {"auth_type": "managed_identity"},
        },
        {
            "connection": {"account_url": "https://internal.example.com"},
            "auth": {"auth_type": "managed_identity"},
        },
        {
            "connection": {},
            "auth": {
                "auth_type": "connection_string",
                "secret": "BlobEndpoint=https://127.0.0.1;SharedAccessSignature=sv=fake&sig=secret",
            },
        },
    ]
    for unsafe_source in unsafe_sources:
        try:
            get_service_client(unsafe_source)
            raise AssertionError("Unsafe endpoint reached BlobServiceClient")
        except ValueError as exc:
            assert "Azure Blob Storage" in str(exc)

    assert len(FakeBlobServiceClient.constructor_calls) == 1
    assert FakeBlobServiceClient.connection_string_calls == []


def test_file_sync_routes_do_not_disclose_exception_details():
    """Validate detailed backend exceptions are logged but never returned."""
    route_text = read_text("application/single_app/route_backend_file_sync.py")

    assert "from functions_appinsights import log_event" in route_text
    assert '"[FileSync] Request failed."' in route_text
    assert '"error": str(error)' in route_text
    assert "return _error(str(error)" not in route_text
    for public_message in [
        "You do not have permission to perform this File Sync operation.",
        "The requested File Sync resource was not found.",
        "The File Sync request could not be completed. Verify the source configuration and try again.",
        "An unexpected error occurred while processing the File Sync request.",
    ]:
        assert public_message in route_text


def test_file_sync_run_and_item_errors_are_client_safe():
    """Validate persisted and serialized failure messages do not expose SDK details."""
    public_run_error = "File Sync run failed. Contact an administrator if the problem continues."
    public_item_error = "File Sync could not process this item. Contact an administrator if the problem continues."
    functions = load_functions(
        "functions_file_sync.py",
        {"sanitize_file_sync_run"},
        {"FILE_SYNC_PUBLIC_RUN_ERROR_MESSAGE": public_run_error},
    )
    sanitized_run = functions["sanitize_file_sync_run"]({
        "id": "run-1",
        "status": "failed",
        "error_message": "Request to https://internal.example?sig=secret failed",
    })

    assert sanitized_run["error_message"] == public_run_error
    assert "internal.example" not in sanitized_run["error_message"]
    assert "secret" not in sanitized_run["error_message"]

    file_sync_text = read_text("application/single_app/functions_file_sync.py")
    assert f'FILE_SYNC_PUBLIC_RUN_ERROR_MESSAGE = "{public_run_error}"' in file_sync_text
    assert f'FILE_SYNC_PUBLIC_ITEM_ERROR_MESSAGE = "{public_item_error}"' in file_sync_text
    assert '"error_message": str(error)[:1000]' not in file_sync_text
    assert 'item["error_message"] = str(delete_error)[:1000]' not in file_sync_text
    assert '"run_failed", {"run_id": run["id"], "error": error_message}' not in file_sync_text


def test_azure_blob_secret_credentials_require_key_vault_references():
    """Validate saved Blob secrets cannot remain inline in Cosmos records."""
    functions = load_functions(
        "functions_file_sync.py",
        {"_normalize_text", "_assert_azure_blob_auth_storage"},
    )
    assert_auth_storage = functions["_assert_azure_blob_auth_storage"]

    assert_auth_storage({"auth_type": "managed_identity"})
    assert_auth_storage({"auth_type": "client_secret", "secret_secret_name": "https://vault/secrets/client"})
    assert_auth_storage({"auth_type": "connection_string", "secret_secret_name": "https://vault/secrets/connection"})

    for auth in [
        {"auth_type": "client_secret", "secret": "raw-secret"},
        {"auth_type": "connection_string", "secret": "raw-connection-string"},
    ]:
        try:
            assert_auth_storage(auth)
            raise AssertionError("Inline Azure Blob secrets must be rejected")
        except ValueError as exc:
            assert "Azure Key Vault" in str(exc)


def test_azure_blob_list_browse_and_stage_behavior():
    """Validate virtual paths, recursive filtering, metadata, and streamed staging."""
    names = {
        "_azure_blob_item_value",
        "_azure_blob_item_name",
        "_azure_blob_item_is_folder",
        "_azure_blob_item_size",
        "_azure_blob_item_modified_at",
        "_azure_blob_item_change_token",
        "_join_azure_blob_path",
        "_relative_azure_blob_path",
        "_build_azure_blob_url",
        "_browse_azure_blob_path",
        "_list_azure_blobs",
        "_stage_azure_blob_file",
    }

    class BlobPrefix:
        def __init__(self, name):
            self.name = name

    class FakeDownloader:
        def chunks(self):
            return [b"blob ", b"content"]

    class FakeBlobClient:
        def download_blob(self):
            return FakeDownloader()

    class FakeContainerClient:
        def __init__(self):
            self.last_browse_prefix = None
            self.last_blob_name = None

        def walk_blobs(self, name_starts_with=None, delimiter=None):
            self.last_browse_prefix = name_starts_with
            assert delimiter == "/"
            return [
                BlobPrefix("incoming/reports/2025/"),
                {
                    "name": "incoming/reports/summary.pdf",
                    "size": 12,
                    "last_modified": "2026-07-28T12:00:00+00:00",
                    "etag": "etag-summary",
                },
            ]

        def list_blobs(self, name_starts_with=None):
            assert name_starts_with == "incoming/reports"
            return [
                {
                    "name": "incoming/reports/summary.pdf",
                    "size": 12,
                    "last_modified": "2026-07-28T12:00:00+00:00",
                    "etag": "etag-summary",
                },
                {
                    "name": "incoming/reports/2025/detail.docx",
                    "size": 34,
                    "last_modified": "2026-07-28T12:01:00+00:00",
                    "etag": "etag-detail",
                },
                {"name": "incoming/reports/empty/", "size": 0},
                {
                    "name": "incoming/reports/hns-directory",
                    "size": 0,
                    "metadata": {"hdi_isfolder": "true"},
                },
            ]

        def get_blob_client(self, blob_name):
            self.last_blob_name = blob_name
            return FakeBlobClient()

    container_client = FakeContainerClient()
    functions = load_functions(
        "functions_file_sync.py",
        names,
        {
            "_format_smb_modified_at": lambda value: value,
            "_get_azure_blob_container_client": lambda source: container_client,
        },
    )
    source = {
        "source_type": "azure_blob",
        "recursive": True,
        "connection": {
            "account_url": "https://contosodata.blob.core.windows.net",
            "container_name": "documents",
            "blob_prefix": "incoming/reports",
            "selected_paths": [],
        },
    }
    config = {
        "file_sync_allow_recursive_sources": True,
        "file_sync_max_files_per_run": 100,
    }

    browse_entries = functions["_browse_azure_blob_path"](source, "")
    assert container_client.last_browse_prefix == "incoming/reports/"
    assert browse_entries == [
        {"name": "2025", "path": "2025", "type": "folder", "size": 0, "modified_at": None},
        {
            "name": "summary.pdf",
            "path": "summary.pdf",
            "type": "file",
            "size": 12,
            "modified_at": "2026-07-28T12:00:00+00:00",
        },
    ]

    remote_files = functions["_list_azure_blobs"](source, config)
    assert [item["relative_path"] for item in remote_files] == ["summary.pdf", "2025/detail.docx"]
    assert remote_files[0]["remote_change_token"] == "etag-summary"
    assert remote_files[0]["remote_path"] == "https://contosodata.blob.core.windows.net/documents/incoming/reports/summary.pdf"

    non_recursive_source = {**source, "recursive": False}
    non_recursive_files = functions["_list_azure_blobs"](non_recursive_source, config)
    assert [item["relative_path"] for item in non_recursive_files] == ["summary.pdf"]

    staged_path, content_hash = functions["_stage_azure_blob_file"](source, remote_files[0])
    try:
        assert Path(staged_path).read_bytes() == b"blob content"
        assert content_hash == hashlib.sha256(b"blob content").hexdigest()
        assert container_client.last_blob_name == "incoming/reports/summary.pdf"
    finally:
        Path(staged_path).unlink(missing_ok=True)


def test_workspace_identity_catalog_supports_azure_blob():
    """Validate reusable identities can be scoped to Azure Blob File Sync."""
    identity_text = read_text("application/single_app/functions_workspace_identities.py")
    identities_js = read_text("application/single_app/static/js/workspace/workspace-identities.js")

    assert '"file_sync": ["smb", "azure_files", "azure_blob",' in identity_text
    assert "sourceTypes: ['smb', 'azure_files', 'azure_blob'," in identities_js


def test_frontend_source_workflow_supports_azure_blob():
    """Validate admins can enable Blob sources and all workspaces can configure them."""
    file_sync_js = read_text("application/single_app/static/js/workspace/workspace-file-sync.js")
    admin_template = read_text("application/single_app/templates/admin_settings.html")
    workspace_templates = {
        "personal": read_text("application/single_app/templates/workspace.html"),
        "group": read_text("application/single_app/templates/group_workspaces.html"),
        "public": read_text("application/single_app/templates/manage_public_workspace.html"),
    }

    for marker in [
        "value: 'azure_blob'",
        "label: 'Azure Blob Storage'",
        "azure_blob: ['managed_identity', 'client_secret', 'connection_string']",
        "Blob service URL or account name",
        "Container name",
        "Blob prefix",
        "Managed identity is recommended. Client secret and connection string authentication require Azure Key Vault secret storage.",
        "container_name: containerNameField.input.value.trim()",
        "blob_prefix: blobPrefixField.input.value.trim()",
    ]:
        assert marker in file_sync_js

    assert 'name="file_sync_visible_source_types" value="azure_blob"' in admin_template
    assert "Azure Blob Storage" in admin_template
    for scope_type, template_text in workspace_templates.items():
        assert f'data-scope="{scope_type}"' in template_text
        assert "data-visible-source-types=" in template_text
        assert "settings.file_sync_visible_source_types" in template_text


def test_synced_document_badges_include_azure_blob():
    """Validate synced-document source badges identify Azure Blob Storage."""
    workspace_utils = read_text("application/single_app/static/js/workspace/workspace-utils.js")
    group_template = read_text("application/single_app/templates/group_workspaces.html")
    public_js = read_text("application/single_app/static/js/public/public_workspace.js")

    for frontend_text in [workspace_utils, group_template, public_js]:
        assert "azure_blob" in frontend_text
        assert "Managed by File Sync from Azure Blob Storage" in frontend_text


def run_tests():
    """Run all tests in this file."""
    tests = [
        test_version_and_dependency_pin,
        test_file_sync_backend_azure_blob_wiring,
        test_azure_blob_connection_contract,
        test_azure_blob_connection_normalization_behavior,
        test_azure_blob_endpoints_block_server_side_request_forgery,
        test_azure_blob_service_client_revalidates_endpoints_before_sdk_use,
        test_file_sync_routes_do_not_disclose_exception_details,
        test_file_sync_run_and_item_errors_are_client_safe,
        test_azure_blob_secret_credentials_require_key_vault_references,
        test_azure_blob_list_browse_and_stage_behavior,
        test_workspace_identity_catalog_supports_azure_blob,
        test_frontend_source_workflow_supports_azure_blob,
        test_synced_document_badges_include_azure_blob,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            results.append(False)
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)