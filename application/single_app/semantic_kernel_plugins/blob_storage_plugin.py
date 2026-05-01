# blob_storage_plugin.py
"""Semantic Kernel plugin for container-scoped Azure Blob Storage operations."""

import logging
from typing import Any, Dict, List, Optional

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from semantic_kernel.functions import kernel_function

from functions_appinsights import log_event
from functions_blob_storage_operations import (
    BLOB_STORAGE_CAPABILITY_DEFINITIONS,
    BLOB_STORAGE_PLUGIN_TYPE,
    detect_blob_storage_file_type,
    derive_blob_endpoint_from_connection_string,
    get_blob_storage_content_type,
    get_blob_storage_enabled_function_names,
    get_enabled_blob_storage_read_file_types,
    get_enabled_blob_storage_upload_file_types,
    is_blob_storage_file_type_enabled,
    normalize_blob_prefix,
    normalize_blob_storage_capabilities,
    normalize_blob_storage_read_file_types,
    normalize_blob_storage_upload_file_types,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class BlobStoragePlugin(BasePlugin):
    """Container-scoped Azure Blob Storage plugin with capability-gated operations."""

    DEFAULT_ENDPOINT = "https://blob.core.windows.net"
    MAX_LIST_RESULTS = 200
    MAX_READ_BYTES = 1024 * 1024

    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}
        self._metadata = self.manifest.get("metadata", {}) or {}
        self._additional_fields = self.manifest.get("additionalFields", {}) or {}
        self._auth = self.manifest.get("auth", {}) or {}
        self.auth_type = str(self._auth.get("type") or "connection_string").strip().lower()
        self.connection_string = str(self._auth.get("key") or "").strip() if self.auth_type == "connection_string" else ""
        self.auth_key = str(self._auth.get("key") or "").strip() if self.auth_type == "key" else ""
        self.auth_identity = str(self._auth.get("identity") or "managed_identity").strip() or "managed_identity"
        self.endpoint = str(
            self.manifest.get("endpoint")
            or derive_blob_endpoint_from_connection_string(self.connection_string)
            or self.DEFAULT_ENDPOINT
        ).strip().rstrip("/")
        self.container_name = str(
            self.manifest.get("container_name")
            or self._additional_fields.get("container_name")
            or ""
        ).strip()
        self.blob_prefix = normalize_blob_prefix(self._additional_fields.get("blob_prefix") or self.manifest.get("blob_prefix"))
        self._capabilities = normalize_blob_storage_capabilities(
            self.manifest.get("blob_storage_capabilities")
            or self._additional_fields.get("blob_storage_capabilities")
        )
        self._read_file_types = normalize_blob_storage_read_file_types(
            self.manifest.get("blob_storage_read_file_types")
            or self._additional_fields.get("blob_storage_read_file_types")
        )
        self._upload_file_types = normalize_blob_storage_upload_file_types(
            self.manifest.get("blob_storage_upload_file_types")
            or self._additional_fields.get("blob_storage_upload_file_types")
        )
        self._enabled_function_names = set(
            self.manifest.get("enabled_functions")
            or get_blob_storage_enabled_function_names(self._capabilities)
        )

        self._validate_configuration()
        self.service_client = self._build_service_client()
        self.container_client = self.service_client.get_container_client(self.container_name)

    @property
    def display_name(self) -> str:
        return "Blob Storage"

    @property
    def metadata(self) -> Dict[str, Any]:
        enabled_methods = set(self.get_functions())
        supported_read_types = get_enabled_blob_storage_read_file_types(self._read_file_types)
        supported_upload_types = get_enabled_blob_storage_upload_file_types(self._upload_file_types)
        read_type_text = ", ".join(supported_read_types) if supported_read_types else "none"
        upload_type_text = ", ".join(supported_upload_types) if supported_upload_types else "none"

        method_specs = {
            "list_container_contents": {
                "name": "list_container_contents",
                "description": "List blobs in the configured container and optional prefix.",
                "parameters": [
                    {
                        "name": "prefix",
                        "type": "str",
                        "description": "Optional prefix below the configured default prefix.",
                        "required": False,
                    },
                    {
                        "name": "max_results",
                        "type": "int",
                        "description": f"Maximum number of blobs to return, capped at {self.MAX_LIST_RESULTS}.",
                        "required": False,
                    },
                ],
                "returns": {"type": "dict", "description": "Blob listing results and support flags."},
            },
            "read_file_content": {
                "name": "read_file_content",
                "description": f"Read supported file content from the configured container. Enabled read file types: {read_type_text}.",
                "parameters": [
                    {
                        "name": "blob_name",
                        "type": "str",
                        "description": "Blob name or relative path within the configured container.",
                        "required": True,
                    }
                ],
                "returns": {"type": "dict", "description": "Blob content and related metadata."},
            },
            "upload_file_to_container": {
                "name": "upload_file_to_container",
                "description": f"Upload supported file content into the configured container. Enabled upload file types: {upload_type_text}.",
                "parameters": [
                    {
                        "name": "blob_name",
                        "type": "str",
                        "description": "Blob name or relative path within the configured container.",
                        "required": True,
                    },
                    {
                        "name": "content",
                        "type": "str",
                        "description": "UTF-8 text content to upload.",
                        "required": True,
                    },
                    {
                        "name": "overwrite",
                        "type": "bool",
                        "description": "If true, overwrite an existing blob with the same name.",
                        "required": False,
                    },
                ],
                "returns": {"type": "dict", "description": "Upload result details."},
            },
        }

        return {
            "name": self.manifest.get("name", "blob_storage_plugin"),
            "type": BLOB_STORAGE_PLUGIN_TYPE,
            "description": (
                "Container-scoped Azure Blob Storage action for listing blobs, reading supported text files, "
                "and uploading supported text files using the configured container and optional prefix."
            ),
            "methods": [
                method_specs[definition["function_name"]]
                for definition in BLOB_STORAGE_CAPABILITY_DEFINITIONS
                if definition["function_name"] in enabled_methods
            ],
        }

    def get_functions(self) -> List[str]:
        return [
            definition["function_name"]
            for definition in BLOB_STORAGE_CAPABILITY_DEFINITIONS
            if definition["function_name"] in self._enabled_function_names
        ]

    def _validate_configuration(self):
        if not self.container_name:
            raise ValueError("BlobStoragePlugin requires additionalFields.container_name in the manifest.")

        if self.auth_type == "connection_string":
            if not self.connection_string:
                raise ValueError("BlobStoragePlugin requires auth.key when using connection string authentication.")
            return

        if self.auth_type == "identity":
            if not self.endpoint:
                raise ValueError("BlobStoragePlugin requires 'endpoint' when using managed identity authentication.")
            return

        if self.auth_type == "key":
            if not self.endpoint:
                raise ValueError("BlobStoragePlugin requires 'endpoint' when using account-key authentication.")
            if not self.auth_key:
                raise ValueError("BlobStoragePlugin requires auth.key when using account-key authentication.")
            return

        raise ValueError(f"Unsupported auth.type for BlobStoragePlugin: {self.auth_type}")

    def _build_service_client(self) -> BlobServiceClient:
        if self.auth_type == "connection_string":
            return BlobServiceClient.from_connection_string(self.connection_string)
        if self.auth_type == "identity":
            return BlobServiceClient(account_url=self.endpoint, credential=DefaultAzureCredential())
        return BlobServiceClient(account_url=self.endpoint, credential=self.auth_key)

    def _resolve_effective_prefix(self, prefix: str = "") -> str:
        default_prefix = self.blob_prefix
        requested_prefix = normalize_blob_prefix(prefix)
        if default_prefix and requested_prefix:
            if requested_prefix.startswith(f"{default_prefix}/") or requested_prefix == default_prefix:
                return requested_prefix
            return f"{default_prefix}/{requested_prefix}".strip("/")
        return default_prefix or requested_prefix

    def _resolve_blob_name(self, blob_name: str) -> str:
        normalized_blob_name = str(blob_name or "").strip().strip("/")
        if not normalized_blob_name:
            raise ValueError("A blob name is required.")

        effective_prefix = self._resolve_effective_prefix()
        if effective_prefix and not normalized_blob_name.startswith(f"{effective_prefix}/") and normalized_blob_name != effective_prefix:
            return f"{effective_prefix}/{normalized_blob_name}".strip("/")
        return normalized_blob_name

    def _get_relative_blob_name(self, blob_name: str) -> str:
        effective_prefix = self._resolve_effective_prefix()
        normalized_blob_name = str(blob_name or "").strip().strip("/")
        if effective_prefix and normalized_blob_name.startswith(f"{effective_prefix}/"):
            return normalized_blob_name[len(effective_prefix) + 1:]
        return normalized_blob_name

    def _is_read_supported(self, blob_name: str) -> bool:
        if "read_file_content" not in self._enabled_function_names:
            return False
        return is_blob_storage_file_type_enabled(blob_name, self._read_file_types)

    def _is_upload_supported(self, blob_name: str) -> bool:
        if "upload_file_to_container" not in self._enabled_function_names:
            return False
        return is_blob_storage_file_type_enabled(blob_name, self._upload_file_types)

    def _build_list_item(self, blob) -> Dict[str, Any]:
        blob_name = getattr(blob, "name", "")
        file_type = detect_blob_storage_file_type(blob_name)
        return {
            "blob_name": blob_name,
            "relative_path": self._get_relative_blob_name(blob_name),
            "size": getattr(blob, "size", None),
            "file_type": file_type or "unsupported",
            "supported_for_read": self._is_read_supported(blob_name),
            "supported_for_upload": self._is_upload_supported(blob_name),
        }

    def _error_response(self, message: str, error_type: str = "validation", **extra: Any) -> Dict[str, Any]:
        payload = {
            "success": False,
            "error": message,
            "error_type": error_type,
        }
        payload.update(extra)
        return payload

    @plugin_function_logger("BlobStoragePlugin")
    @kernel_function(description="List blobs in the configured Azure Blob Storage container and optional prefix.")
    def list_container_contents(self, prefix: str = "", max_results: int = 50) -> Dict[str, Any]:
        try:
            requested_max_results = int(max_results or 50)
        except (TypeError, ValueError):
            requested_max_results = 50

        effective_max_results = min(max(requested_max_results, 1), self.MAX_LIST_RESULTS)
        effective_prefix = self._resolve_effective_prefix(prefix)
        blobs = []
        has_more = False

        try:
            iterator = self.container_client.list_blobs(name_starts_with=effective_prefix or None)
            for index, blob in enumerate(iterator):
                if index >= effective_max_results:
                    has_more = True
                    break
                blobs.append(self._build_list_item(blob))

            return {
                "success": True,
                "container_name": self.container_name,
                "blob_prefix": effective_prefix,
                "items": blobs,
                "item_count": len(blobs),
                "has_more": has_more,
            }
        except ResourceNotFoundError:
            return self._error_response(
                f"Blob container '{self.container_name}' was not found.",
                error_type="not_found",
            )
        except AzureError as exc:
            log_event(
                f"[BlobStoragePlugin] Failed to list container contents: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return self._error_response("Failed to list container contents.", error_type="unexpected", details=str(exc))

    @plugin_function_logger("BlobStoragePlugin")
    @kernel_function(description="Read supported file content from the configured Azure Blob Storage container.")
    def read_file_content(self, blob_name: str) -> Dict[str, Any]:
        try:
            effective_blob_name = self._resolve_blob_name(blob_name)
        except ValueError as exc:
            return self._error_response(str(exc))

        if not self._is_read_supported(effective_blob_name):
            return self._error_response(
                "The requested blob is not enabled for read operations. Only supported read file types can be opened.",
                blob_name=effective_blob_name,
            )

        try:
            blob_client = self.container_client.get_blob_client(effective_blob_name)
            data = blob_client.download_blob().readall()
            if len(data) > self.MAX_READ_BYTES:
                return self._error_response(
                    f"The requested blob exceeds the {self.MAX_READ_BYTES} byte read limit.",
                    blob_name=effective_blob_name,
                )

            try:
                content = data.decode("utf-8")
            except UnicodeDecodeError:
                return self._error_response(
                    "The requested blob could not be decoded as UTF-8 text.",
                    blob_name=effective_blob_name,
                    error_type="decode",
                )

            return {
                "success": True,
                "container_name": self.container_name,
                "blob_name": effective_blob_name,
                "relative_path": self._get_relative_blob_name(effective_blob_name),
                "file_type": detect_blob_storage_file_type(effective_blob_name) or "unknown",
                "content": content,
                "content_length": len(content),
            }
        except ResourceNotFoundError:
            return self._error_response(
                f"Blob '{effective_blob_name}' was not found in container '{self.container_name}'.",
                error_type="not_found",
            )
        except AzureError as exc:
            log_event(
                f"[BlobStoragePlugin] Failed to read blob content: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return self._error_response("Failed to read blob content.", error_type="unexpected", details=str(exc))

    @plugin_function_logger("BlobStoragePlugin")
    @kernel_function(description="Upload supported file content to the configured Azure Blob Storage container.")
    def upload_file_to_container(self, blob_name: str, content: str, overwrite: bool = False) -> Dict[str, Any]:
        try:
            effective_blob_name = self._resolve_blob_name(blob_name)
        except ValueError as exc:
            return self._error_response(str(exc))

        if not self._is_upload_supported(effective_blob_name):
            return self._error_response(
                "The requested blob path is not enabled for upload operations. Only supported upload file types can be written.",
                blob_name=effective_blob_name,
            )

        file_type = detect_blob_storage_file_type(effective_blob_name)
        if file_type != "markdown":
            return self._error_response(
                "Only Markdown uploads are supported in this version.",
                blob_name=effective_blob_name,
            )

        try:
            blob_client = self.container_client.get_blob_client(effective_blob_name)
            blob_client.upload_blob(
                content.encode("utf-8"),
                overwrite=bool(overwrite),
                content_settings=ContentSettings(content_type=get_blob_storage_content_type(file_type)),
            )
            return {
                "success": True,
                "container_name": self.container_name,
                "blob_name": effective_blob_name,
                "relative_path": self._get_relative_blob_name(effective_blob_name),
                "file_type": file_type,
                "overwrite": bool(overwrite),
                "content_length": len(content),
            }
        except ResourceNotFoundError:
            return self._error_response(
                f"Blob container '{self.container_name}' was not found.",
                error_type="not_found",
            )
        except AzureError as exc:
            log_event(
                f"[BlobStoragePlugin] Failed to upload blob content: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return self._error_response("Failed to upload blob content.", error_type="unexpected", details=str(exc))
