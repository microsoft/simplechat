#!/usr/bin/env python3
# test_file_sync_azure_blob_storage.py
"""
Functional test for Azure Blob Storage File Sync.
Version: 0.250.070
Implemented in: 0.250.067
Security hardening in: 0.250.068
Container SAS support in: 0.250.069
Non-Key-Vault and List/Read validation fix in: 0.250.070

This test ensures Azure Blob Storage is wired into the shared File Sync
pipeline for every supported workspace scope without requiring live Azure
Storage or Cosmos DB access.
"""

import ast
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, quote, unquote, urlparse


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
        "FileSyncPublicValidationError": ValueError,
        "List": List,
        "Optional": Optional,
        "Tuple": Tuple,
        "datetime": datetime,
        "hashlib": hashlib,
        "json": json,
        "os": os,
        "parse_qsl": parse_qsl,
        "quote": quote,
        "re": re,
        "tempfile": tempfile,
        "timedelta": timedelta,
        "timezone": timezone,
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

    assert 'VERSION = "0.250.071"' in config_text
    assert "azure-storage-blob==12.24.1" in requirements_text


def test_file_sync_backend_azure_blob_wiring():
    """Validate Azure Blob connector helpers and shared dispatch exist."""
    file_sync_text = read_text("application/single_app/functions_file_sync.py")
    names = function_names(parse_app("functions_file_sync.py"))

    expected_functions = {
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
    assert "Azure Blob Storage secret credentials must be stored in Azure Key Vault" not in file_sync_text


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
    ]:
        assert marker in file_sync_text
    connection_test_block = file_sync_text.split("def _test_azure_blob_connection", 1)[1].split(
        "def _azure_blob_error_diagnostics", 1
    )[0]
    assert "get_container_properties" not in connection_test_block


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
            "_parse_azure_blob_sas_parameters",
            "_parse_azure_blob_sas_datetime",
            "_azure_blob_permission_labels",
            "_azure_blob_sas_metadata",
            "_parse_azure_blob_connection_string",
            "_parse_azure_blob_sas_url",
            "_parse_azure_blob_credential",
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
        "https://contoso-data.blob.core.windows.net",
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
            "_normalize_azure_container_name",
            "_now",
            "_parse_azure_blob_sas_parameters",
            "_parse_azure_blob_sas_datetime",
            "_azure_blob_permission_labels",
            "_azure_blob_sas_metadata",
            "_parse_azure_blob_connection_string",
            "_parse_azure_blob_sas_url",
            "_parse_azure_blob_credential",
            "_validate_azure_blob_connection_string",
            "_validate_azure_blob_sas_for_container",
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


def test_azure_blob_container_sas_scope_permissions_and_expiry():
    """Validate container SAS connection strings and safe metadata extraction."""
    functions = load_functions(
        "functions_file_sync.py",
        {
            "_normalize_text",
            "_azure_blob_endpoint_suffix_for_hostname",
            "_normalize_azure_blob_url",
            "_normalize_azure_container_name",
            "_now",
            "_parse_azure_blob_sas_parameters",
            "_parse_azure_blob_sas_datetime",
            "_azure_blob_permission_labels",
            "_azure_blob_sas_metadata",
            "_parse_azure_blob_connection_string",
            "_parse_azure_blob_sas_url",
            "_parse_azure_blob_credential",
            "_validate_azure_blob_connection_string",
            "_validate_azure_blob_sas_for_container",
        },
        {
            "AZURE_STORAGE_ENDPOINT_SUFFIXES": ("core.windows.net",),
            "AZURE_BLOB_SAS_PERMISSION_LABELS": {
                "r": "Read",
                "l": "List",
                "w": "Write",
                "d": "Delete",
            },
        },
    )
    parse_connection_string = functions["_parse_azure_blob_connection_string"]
    parse_credential = functions["_parse_azure_blob_credential"]
    validate_for_container = functions["_validate_azure_blob_sas_for_container"]

    container_sas = (
        "BlobEndpoint=https://contosodata.blob.core.windows.net/documents;"
        "SharedAccessSignature=sv=2022-11-02&spr=https&"
        "st=2026-07-28T00%3A00%3A00Z&se=2030-07-28T00%3A00%3A00Z&"
        "sr=c&sp=rl&sig=fake-container-signature"
    )
    parsed_container_sas = parse_connection_string(container_sas)
    validate_for_container(parsed_container_sas, "documents")
    assert parsed_container_sas["account_url"] == "https://contosodata.blob.core.windows.net"
    assert parsed_container_sas["endpoint_container_name"] == "documents"
    assert parsed_container_sas["sas_token"].endswith("sig=fake-container-signature")
    assert parsed_container_sas["sas_metadata"] == {
        "credential_type": "sas",
        "sas_scope": "container",
        "permissions": "rl",
        "starts_at": "2026-07-28T00:00:00+00:00",
        "expires_at": "2030-07-28T00:00:00+00:00",
        "https_only": True,
        "stored_access_policy": False,
        "signed_version": "2022-11-02",
        "ip_range": "",
        "services": "",
        "resource_types": "",
        "warnings": [],
    }
    assert "sig" not in parsed_container_sas["sas_metadata"]
    assert "signature" not in str(parsed_container_sas["sas_metadata"]).lower()

    container_sas_url = (
        "https://contosodata.blob.core.windows.net/documents?"
        "sv=2022-11-02&spr=https&sr=c&sp=rl&"
        "se=2030-07-28T00%3A00%3A00Z&sig=fake-container-signature"
    )
    parsed_sas_url = parse_credential(container_sas_url)
    validate_for_container(parsed_sas_url, "documents", "https://contosodata.blob.core.windows.net")
    assert parsed_sas_url["endpoint_container_name"] == "documents"
    assert parsed_sas_url["sas_metadata"]["permissions"] == "rl"

    standalone_sas_token = (
        "?sv=2022-11-02&spr=https&sr=c&sp=rl&"
        "se=2030-07-28T00%3A00%3A00Z&sig=fake-container-signature"
    )
    parsed_sas_token = parse_credential(
        standalone_sas_token,
        account_url="https://contosodata.blob.core.windows.net",
        container_name="documents",
    )
    validate_for_container(parsed_sas_token, "documents", "https://contosodata.blob.core.windows.net")
    assert parsed_sas_token["account_url"] == "https://contosodata.blob.core.windows.net"
    assert parsed_sas_token["endpoint_container_name"] == "documents"

    read_only_sas_url = container_sas_url.replace("sp=rl", "sp=r")
    try:
        validate_for_container(parse_credential(read_only_sas_url), "documents")
        raise AssertionError("Container SAS without List was accepted")
    except ValueError as exc:
        assert "Read and List" in str(exc)

    try:
        validate_for_container(parsed_container_sas, "other-container")
        raise AssertionError("Container SAS must match the selected container")
    except ValueError as exc:
        assert "selected container" in str(exc)

    extra_permission_container_sas = container_sas.replace("sr=c&sp=rl", "sr=c&sp=rlwd")
    parsed_extra_permission_sas = parse_connection_string(extra_permission_container_sas)
    validate_for_container(parsed_extra_permission_sas, "documents")
    assert any(
        "Write, Delete" in warning and "Read and List are sufficient" in warning
        for warning in parsed_extra_permission_sas["sas_metadata"]["warnings"]
    )

    account_sas = (
        "BlobEndpoint=https://contosodata.blob.core.windows.net;"
        "SharedAccessSignature=sv=2022-11-02&spr=https&ss=b&srt=co&"
        "sp=rlwd&se=2030-07-28T00%3A00%3A00Z&sig=fake-account-signature"
    )
    parsed_account_sas = parse_connection_string(account_sas)
    validate_for_container(parsed_account_sas, "documents")
    assert parsed_account_sas["sas_metadata"]["sas_scope"] == "account"
    assert any("more access than this single-container source needs" in warning for warning in parsed_account_sas["sas_metadata"]["warnings"])
    assert any("Write, Delete" in warning for warning in parsed_account_sas["sas_metadata"]["warnings"])

    blocked_sas_values = [
        (
            "BlobEndpoint=https://contosodata.blob.core.windows.net/documents/report.pdf;"
            "SharedAccessSignature=sv=2022-11-02&spr=https&sr=b&sp=r&"
            "se=2030-07-28T00%3A00%3A00Z&sig=fake-blob-signature"
        ),
        (
            "BlobEndpoint=https://contosodata.blob.core.windows.net/documents;"
            "SharedAccessSignature=sv=2022-11-02&spr=https&sr=c&sp=r&"
            "se=2030-07-28T00%3A00%3A00Z&sig=missing-list"
        ),
        (
            "BlobEndpoint=https://contosodata.blob.core.windows.net/documents;"
            "SharedAccessSignature=sv=2022-11-02&spr=https&sr=c&sp=rl&"
            "se=2020-07-28T00%3A00%3A00Z&sig=expired"
        ),
        (
            "BlobEndpoint=https://contosodata.blob.core.windows.net/documents;"
            "SharedAccessSignature=sv=2022-11-02&spr=https&sr=c&sp=rl&"
            "se=2030-07-28T00%3A00%3A00Z"
        ),
        (
            "BlobEndpoint=https://contosodata.blob.core.windows.net/documents;"
            "SharedAccessSignature=spr=https&sr=c&sp=rl&"
            "se=2030-07-28T00%3A00%3A00Z&sig=missing-version"
        ),
    ]
    for blocked_sas in blocked_sas_values:
        try:
            validate_for_container(parse_connection_string(blocked_sas), "documents")
            raise AssertionError("Unsuitable SAS credential was accepted")
        except ValueError as exc:
            assert any(
                expected_text in str(exc)
                for expected_text in ("blob/object SAS", "Read and List", "expired", "incomplete")
            )


def test_azure_blob_container_sas_uses_container_client_without_token_disclosure():
    """Validate container SAS credentials construct only the selected container client."""
    class FakeContainerClient:
        calls = []

        def __init__(self, account_url, container_name, credential):
            self.calls.append((account_url, container_name, credential))

    class FakeBlobServiceClient:
        calls = []

        @classmethod
        def from_connection_string(cls, connection_string):
            cls.calls.append(connection_string)
            raise AssertionError("Container SAS must not use BlobServiceClient.from_connection_string")

    connection_string = (
        "BlobEndpoint=https://contosodata.blob.core.windows.net/documents;"
        "SharedAccessSignature=sv=2022-11-02&spr=https&sr=c&sp=rl&"
        "se=2030-07-28T00%3A00%3A00Z&sig=fake-container-signature"
    )
    functions = load_functions(
        "functions_file_sync.py",
        {
            "_normalize_text",
            "_azure_blob_endpoint_suffix_for_hostname",
            "_normalize_azure_blob_url",
            "_normalize_azure_container_name",
            "_now",
            "_parse_azure_blob_sas_parameters",
            "_parse_azure_blob_sas_datetime",
            "_azure_blob_sas_metadata",
            "_parse_azure_blob_connection_string",
            "_parse_azure_blob_sas_url",
            "_parse_azure_blob_credential",
            "_validate_azure_blob_connection_string",
            "_validate_azure_blob_sas_for_container",
            "_get_azure_blob_service_client",
            "_get_azure_blob_container_client",
        },
        {
            "AZURE_STORAGE_ENDPOINT_SUFFIXES": ("core.windows.net",),
            "ContainerClient": FakeContainerClient,
            "BlobServiceClient": FakeBlobServiceClient,
            "_get_identity_auth_for_source": lambda source: None,
            "_resolved_auth_secret": lambda auth: str(auth.get("secret") or ""),
        },
    )
    source = {
        "connection": {
            "account_url": "https://contosodata.blob.core.windows.net",
            "container_name": "documents",
        },
        "auth": {"auth_type": "connection_string", "secret": connection_string},
    }
    functions["_get_azure_blob_container_client"](source)

    assert FakeContainerClient.calls == [
        (
            "https://contosodata.blob.core.windows.net",
            "documents",
            "sv=2022-11-02&spr=https&sr=c&sp=rl&se=2030-07-28T00%3A00%3A00Z&sig=fake-container-signature",
        )
    ]
    assert FakeBlobServiceClient.calls == []


def test_azure_blob_sas_url_hydrates_safe_connection_fields():
    """Validate pasted SAS URLs derive account/container without persisting the token in connection data."""
    functions = load_functions(
        "functions_file_sync.py",
        {
            "_normalize_text",
            "_get_file_sync_secret_value",
            "_azure_blob_endpoint_suffix_for_hostname",
            "_parse_azure_blob_sas_parameters",
            "_parse_azure_blob_sas_datetime",
            "_azure_blob_sas_metadata",
            "_parse_azure_blob_sas_url",
            "_parse_azure_blob_connection_string",
            "_normalize_azure_blob_url",
            "_normalize_azure_container_name",
            "_parse_azure_blob_credential",
            "_hydrate_azure_blob_connection_from_credential",
        },
        {
            "AZURE_STORAGE_ENDPOINT_SUFFIXES": ("core.windows.net",),
            "ui_trigger_word": "__stored__",
        },
    )
    sas_url = (
        "https://contosodata.blob.core.windows.net/documents?"
        "sv=2022-11-02&spr=https&sr=c&sp=rl&"
        "se=2030-07-28T00%3A00%3A00Z&sig=fake-container-signature"
    )
    connection, credentials = functions["_hydrate_azure_blob_connection_from_credential"](
        {"account_url": sas_url},
        {},
        {},
    )

    assert connection == {
        "account_url": "https://contosodata.blob.core.windows.net",
        "container_name": "documents",
    }
    assert credentials["connection_string"] == sas_url
    assert "sig=" not in json.dumps(connection)

    client_secret_connection, client_secret_credentials = functions["_hydrate_azure_blob_connection_from_credential"](
        {
            "account_url": "https://contosodata.blob.core.windows.net",
            "container_name": "documents",
        },
        {},
        {"auth_type": "client_secret", "secret": "not-a-sas-token"},
    )
    assert client_secret_connection["container_name"] == "documents"
    assert client_secret_credentials["secret"] == "not-a-sas-token"

    standalone_connection, standalone_credentials = functions["_hydrate_azure_blob_connection_from_credential"](
        {
            "account_url": "https://contosodata.blob.core.windows.net",
            "container_name": "documents",
        },
        {},
        {
            "auth_type": "connection_string",
            "secret": "?sv=2022-11-02&spr=https&sr=c&sp=rl&se=2030-07-28T00%3A00%3A00Z&sig=fake",
        },
    )
    assert standalone_connection["container_name"] == "documents"
    assert standalone_credentials["auth_type"] == "connection_string"


def test_azure_blob_new_credentials_are_validated_before_secret_storage():
    """Validate rejected Blob credentials cannot write a new Key Vault secret version."""
    file_sync_text = read_text("application/single_app/functions_file_sync.py")
    normalize_source_text = file_sync_text.split("def _normalize_source_payload", 1)[1].split(
        "def create_file_sync_source", 1
    )[0]

    assert "def _prevalidate_new_azure_blob_credential" in file_sync_text
    assert normalize_source_text.index("_prevalidate_new_azure_blob_credential(") < normalize_source_text.index(
        "_prepare_auth_payload("
    )
    assert "and not identity_id" in normalize_source_text


def test_azure_blob_identity_and_read_fallback_guards_are_wired():
    """Validate identity rotations refresh metadata and fallback reads avoid false warnings."""
    file_sync_text = read_text("application/single_app/functions_file_sync.py")
    file_sync_js = read_text("application/single_app/static/js/workspace/workspace-file-sync.js")

    assert "resolved_identity_auth = get_workspace_identity_auth" in file_sync_text
    assert "tolerate_validation_errors=True" in file_sync_text
    assert "if not read_verified:" in file_sync_text
    assert "files_seen += 1" in file_sync_text
    assert "if (identitySelect.value)" in file_sync_js
    assert "credentials.connection_string = '';" in file_sync_js


def test_azure_blob_failure_diagnostics_are_non_secret_and_actionable():
    """Validate Azure failure logs contain useful codes but no signed URLs or tokens."""
    class FakeResponse:
        status_code = 403
        headers = {"x-ms-request-id": "request-123"}

    class FakeAzureError(Exception):
        class ErrorCode:
            value = "AuthorizationPermissionMismatch"

        error_code = ErrorCode()
        status_code = 403
        response = FakeResponse()

    functions = load_functions(
        "functions_file_sync.py",
        {
            "_normalize_text",
            "_normalize_azure_storage_error_code",
            "_sanitize_azure_blob_credential_metadata",
            "_azure_blob_error_diagnostics",
        },
    )
    diagnostics = functions["_azure_blob_error_diagnostics"](
        FakeAzureError("signed URL must not be logged"),
        {
            "id": "source-1",
            "credential_metadata": {
                "credential_type": "sas",
                "sas_scope": "container",
                "permissions": "rl",
                "expires_at": "2030-07-28T00:00:00+00:00",
                "warnings": [],
            },
        },
    )

    assert diagnostics == {
        "exception_type": "FakeAzureError",
        "error_code": "authorizationpermissionmismatch",
        "status_code": 403,
        "request_id": "request-123",
        "source_id": "source-1",
        "auth_kind": "sas",
        "scope_kind": "container",
        "permissions": "rl",
    }
    assert "signed URL" not in json.dumps(diagnostics)
    file_sync_text = read_text("application/single_app/functions_file_sync.py")
    for public_message in [
        "A container SAS must include both Read and List permissions.",
        "Check the account, container, signature, start time, and expiry.",
        "Include the app's outbound addresses or adjust the storage network policy.",
        "Azure could not find the selected Blob container",
    ]:
        assert public_message in file_sync_text
    connection_test_block = file_sync_text.split("def _test_azure_blob_connection", 1)[1].split(
        "def _azure_blob_error_diagnostics", 1
    )[0]
    assert '"error": str(error)' not in connection_test_block


def test_azure_blob_connection_test_uses_only_list_and_read_operations():
    """Validate container SAS testing avoids unneeded container-properties access."""
    class FakeBlobClient:
        def get_blob_properties(self):
            return {"etag": "etag-1"}

    class FakeContainerClient:
        def get_container_properties(self):
            raise AssertionError("Get Container Properties is not required for File Sync")

        def walk_blobs(self, name_starts_with=None, delimiter=None):
            assert name_starts_with == "reports/"
            assert delimiter == "/"
            return [{"name": "reports/example.pdf", "size": 10}]

        def list_blobs(self, name_starts_with=None):
            raise AssertionError("Fallback listing should not run after a readable top-level blob")

        def get_blob_client(self, blob_name):
            assert blob_name == "reports/example.pdf"
            return FakeBlobClient()

    functions = load_functions(
        "functions_file_sync.py",
        {
            "_normalize_text",
            "_azure_blob_item_value",
            "_azure_blob_item_name",
            "_azure_blob_item_is_folder",
            "_sanitize_azure_blob_credential_metadata",
            "_test_azure_blob_connection",
        },
        {
            "_get_azure_blob_container_client": lambda source: FakeContainerClient(),
            "FileSyncPublicValidationError": ValueError,
            "AzureResourceNotFoundError": RuntimeError,
            "log_event": lambda *args, **kwargs: None,
            "logging": logging,
        },
    )
    result = functions["_test_azure_blob_connection"]({
        "id": "source-1",
        "source_type": "azure_blob",
        "recursive": True,
        "connection": {"blob_prefix": "reports"},
        "credential_metadata": {
            "credential_type": "sas",
            "sas_scope": "container",
            "permissions": "rl",
            "warnings": [],
        },
    })

    assert result["success"] is True
    assert result["entries_checked"] == 1
    assert result["files_seen"] == 1
    assert result["read_verified"] is True
    assert result["credential_metadata"]["warnings"] == []


def test_azure_blob_sas_metadata_is_non_secret_and_frontend_visible():
    """Validate source serialization and UI expose SAS status without the token."""
    file_sync_text = read_text("application/single_app/functions_file_sync.py")
    file_sync_js = read_text("application/single_app/static/js/workspace/workspace-file-sync.js")

    for marker in [
        '"credential_metadata": credential_metadata',
        'sanitized_source["credential_metadata"]',
        'source.get("credential_metadata")',
    ]:
        assert marker in file_sync_text
    for marker in [
        "Container SAS",
        "Account SAS",
        "Blob connection string or SAS",
        "Blob connection string, SAS URL, or SAS token",
        "full container SAS URL",
        "standalone SAS token",
        "Expires",
        "Expiry is controlled by a stored access policy",
        "grant broader access",
        "Each source syncs one container",
        "Blob Sync",
    ]:
        assert marker in file_sync_js


def test_file_sync_routes_do_not_disclose_exception_details():
    """Validate detailed backend exceptions are logged but never returned."""
    route_text = read_text("application/single_app/route_backend_file_sync.py")

    assert "from functions_appinsights import log_event" in route_text
    assert "FileSyncPublicValidationError" in route_text
    assert "error.public_message" in route_text
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


def test_azure_blob_secret_credentials_support_optional_key_vault_storage():
    """Validate Blob secrets use Key Vault when enabled and source storage otherwise."""
    store_calls = []
    disabled_functions = load_functions(
        "functions_file_sync.py",
        {"_as_bool", "_store_file_sync_secret"},
        {
            "get_settings": lambda: {
                "enable_key_vault_secret_storage": False,
                "key_vault_name": "",
            },
            "store_secret_in_key_vault": lambda **kwargs: store_calls.append(kwargs),
            "_keyvault_scope": lambda scope_type: scope_type,
        },
    )
    inline_secret = disabled_functions["_store_file_sync_secret"](
        "personal", "user-1", "source-1", "secret", "sas-secret"
    )
    assert inline_secret == "sas-secret"
    assert store_calls == []

    enabled_functions = load_functions(
        "functions_file_sync.py",
        {"_as_bool", "_store_file_sync_secret"},
        {
            "get_settings": lambda: {
                "enable_key_vault_secret_storage": True,
                "key_vault_name": "vault",
            },
            "store_secret_in_key_vault": lambda **kwargs: "vault-secret-reference",
            "_keyvault_scope": lambda scope_type: scope_type,
        },
    )
    key_vault_secret = enabled_functions["_store_file_sync_secret"](
        "personal", "user-1", "source-1", "secret", "sas-secret"
    )
    assert key_vault_secret == "vault-secret-reference"


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
        "A container SAS needs Read and List only.",
        "To sync multiple containers, create one source per container.",
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
        test_azure_blob_container_sas_scope_permissions_and_expiry,
        test_azure_blob_container_sas_uses_container_client_without_token_disclosure,
        test_azure_blob_sas_url_hydrates_safe_connection_fields,
        test_azure_blob_new_credentials_are_validated_before_secret_storage,
        test_azure_blob_identity_and_read_fallback_guards_are_wired,
        test_azure_blob_failure_diagnostics_are_non_secret_and_actionable,
        test_azure_blob_connection_test_uses_only_list_and_read_operations,
        test_azure_blob_sas_metadata_is_non_secret_and_frontend_visible,
        test_file_sync_routes_do_not_disclose_exception_details,
        test_file_sync_run_and_item_errors_are_client_safe,
        test_azure_blob_secret_credentials_support_optional_key_vault_storage,
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