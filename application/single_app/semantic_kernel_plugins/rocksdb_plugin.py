# rocksdb_plugin.py
"""
RocksDB key-value store plugin for Semantic Kernel.

RocksDB is an embedded C++ library with no native network protocol, so this plugin talks to a
RocksDB-backed HTTP/JSON service using the SimpleChat RocksDB service contract documented in
``docs/explanation/features/v0.250.215/ROCKSDB_ACTION.md``. SimpleChat never opens a RocksDB
database directory itself.

Read operations are always available. Write operations are refused unless the action is
explicitly configured with ``read_only`` disabled.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import requests
from semantic_kernel.functions import kernel_function

from functions_appinsights import log_event
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


ROCKSDB_PLUGIN_TYPE = "rocksdb"

AUTH_SCHEME_NONE = "none"
AUTH_SCHEME_BEARER = "bearer"
AUTH_SCHEME_API_KEY = "api_key"
SUPPORTED_AUTH_SCHEMES = (AUTH_SCHEME_NONE, AUTH_SCHEME_BEARER, AUTH_SCHEME_API_KEY)

KEY_ENCODING_UTF8 = "utf8"
KEY_ENCODING_BASE64 = "base64"
SUPPORTED_KEY_ENCODINGS = (KEY_ENCODING_UTF8, KEY_ENCODING_BASE64)

VALUE_ENCODING_UTF8 = "utf8"
VALUE_ENCODING_BASE64 = "base64"
VALUE_ENCODING_JSON = "json"
SUPPORTED_VALUE_ENCODINGS = (VALUE_ENCODING_UTF8, VALUE_ENCODING_BASE64, VALUE_ENCODING_JSON)

DEFAULT_COLUMN_FAMILY = "default"
DEFAULT_API_KEY_HEADER = "X-API-Key"
DEFAULT_MAX_RESULTS = 100
MAX_RESULTS_CEILING = 1000
DEFAULT_MAX_VALUE_BYTES = 32768
MAX_VALUE_BYTES_CEILING = 1048576
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 300
ALLOWED_REMOTE_SCHEMES = ("http", "https")


def normalize_rocksdb_base_url(base_url: str) -> str:
    """Normalize a RocksDB service base URL and reject unsupported schemes."""
    cleaned_url = (base_url or "").strip().rstrip("/")
    if not cleaned_url:
        return ""

    parsed_url = urlparse(cleaned_url)
    if parsed_url.scheme.lower() not in ALLOWED_REMOTE_SCHEMES:
        raise ValueError("RocksDB service URLs must use the http or https scheme.")
    if not parsed_url.netloc:
        raise ValueError("RocksDB service URLs must include a host name.")
    return cleaned_url


class RocksDbResult:
    """Structured RocksDB plugin result paired with the plugin metadata."""

    def __init__(self, data: Any, metadata: Dict[str, Any]):
        self.data = data
        self.metadata = metadata

    def __str__(self) -> str:
        return str(self.data)

    def __repr__(self) -> str:
        return f"RocksDbResult(data={self.data!r}, metadata={self.metadata!r})"


class RocksDbPlugin(BasePlugin):
    """RocksDB key-value plugin backed by a RocksDB HTTP/JSON service."""

    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}
        additional_fields = self.manifest.get("additionalFields", {}) or {}
        auth = self.manifest.get("auth", {}) or {}

        self.base_url = str(
            additional_fields.get("base_url") or self.manifest.get("endpoint") or ""
        ).strip().rstrip("/")
        self.auth_scheme = self._normalize_choice(
            additional_fields.get("auth_scheme"), AUTH_SCHEME_NONE
        )
        self.api_key_header = (
            str(additional_fields.get("api_key_header") or "").strip() or DEFAULT_API_KEY_HEADER
        )
        self.verify_tls = self._coerce_bool(additional_fields.get("verify_tls"), True)

        self.column_family = (
            str(additional_fields.get("column_family") or "").strip() or DEFAULT_COLUMN_FAMILY
        )
        self.key_encoding = self._normalize_choice(
            additional_fields.get("key_encoding"), KEY_ENCODING_UTF8
        )
        self.value_encoding = self._normalize_choice(
            additional_fields.get("value_encoding"), VALUE_ENCODING_UTF8
        )
        self.key_prefix_hints = self._normalize_prefix_hints(
            additional_fields.get("key_prefix_hints")
        )
        self.read_only = self._coerce_bool(additional_fields.get("read_only"), True)
        self.max_results = self._coerce_int(
            additional_fields.get("max_results"), DEFAULT_MAX_RESULTS, "max_results"
        )
        self.max_value_bytes = self._coerce_int(
            additional_fields.get("max_value_bytes"), DEFAULT_MAX_VALUE_BYTES, "max_value_bytes"
        )
        self.timeout = self._coerce_int(additional_fields.get("timeout"), DEFAULT_TIMEOUT, "timeout")

        self.auth_type = str(auth.get("type") or "NoAuth").strip()
        self.auth_key = str(auth.get("key") or "").strip()
        self._metadata = self.manifest.get("metadata", {}) or {}
        self._http_session = None

        self._validate_configuration()

        log_event(
            "[ROCKSDB_PLUGIN] Initialized plugin",
            extra={
                "column_family": self.column_family,
                "key_encoding": self.key_encoding,
                "value_encoding": self.value_encoding,
                "read_only": self.read_only,
                "max_results": self.max_results,
                "max_value_bytes": self.max_value_bytes,
                "timeout": self.timeout,
                "auth_scheme": self.auth_scheme,
                "has_auth_key": bool(self.auth_key),
                "verify_tls": self.verify_tls,
                "prefix_hint_count": len(self.key_prefix_hints),
            },
            level=logging.INFO,
        )

    @property
    def display_name(self) -> str:
        return "RocksDB"

    @property
    def metadata(self) -> Dict[str, Any]:
        user_desc = self._metadata.get(
            "description",
            "RocksDB key-value store plugin backed by a RocksDB HTTP service.",
        )
        write_desc = (
            "Write operations are blocked because this action is configured as read-only."
            if self.read_only
            else "Write operations are enabled for this action; confirm intent before mutating data."
        )
        api_desc = (
            "This plugin reads an ordered RocksDB key-value store through a RocksDB HTTP service. "
            "Keys are byte strings sorted lexicographically, so prefix and range scans are the "
            "efficient access patterns; avoid scanning the whole keyspace. Use get_value for a "
            "single key, get_values for a batch of keys, and scan_prefix or scan_range to walk a "
            f"key range. {write_desc}"
        )
        return {
            "name": self._metadata.get("name", "rocksdb_plugin"),
            "type": ROCKSDB_PLUGIN_TYPE,
            "description": f"{user_desc}\n\n{api_desc}",
            "methods": [
                {
                    "name": "get_value",
                    "description": "Read a single value by exact key.",
                    "parameters": [
                        {"name": "key", "type": "str", "description": "Exact key to read.", "required": True},
                        {"name": "column_family", "type": "str", "description": "Optional column family override.", "required": False},
                    ],
                    "returns": {"type": "RocksDbResult", "description": "The value plus lookup metadata."},
                },
                {
                    "name": "get_values",
                    "description": "Read several values in one call using exact keys.",
                    "parameters": [
                        {"name": "keys", "type": "List[str] | str", "description": "Keys to read, as a list or JSON array string.", "required": True},
                        {"name": "column_family", "type": "str", "description": "Optional column family override.", "required": False},
                    ],
                    "returns": {"type": "RocksDbResult", "description": "One result entry per requested key."},
                },
                {
                    "name": "key_exists",
                    "description": "Check whether a key is present without returning its value.",
                    "parameters": [
                        {"name": "key", "type": "str", "description": "Exact key to test.", "required": True},
                        {"name": "column_family", "type": "str", "description": "Optional column family override.", "required": False},
                    ],
                    "returns": {"type": "RocksDbResult", "description": "Existence flag for the key."},
                },
                {
                    "name": "scan_prefix",
                    "description": "List key-value pairs whose keys start with a prefix.",
                    "parameters": [
                        {"name": "prefix", "type": "str", "description": "Key prefix to scan.", "required": True},
                        {"name": "limit", "type": "int", "description": "Optional per-call result cap.", "required": False},
                        {"name": "column_family", "type": "str", "description": "Optional column family override.", "required": False},
                    ],
                    "returns": {"type": "RocksDbResult", "description": "Matching key-value pairs and truncation state."},
                },
                {
                    "name": "scan_range",
                    "description": "List key-value pairs between an inclusive start key and an exclusive end key.",
                    "parameters": [
                        {"name": "start_key", "type": "str", "description": "Inclusive first key of the range.", "required": False},
                        {"name": "end_key", "type": "str", "description": "Exclusive last key of the range.", "required": False},
                        {"name": "limit", "type": "int", "description": "Optional per-call result cap.", "required": False},
                        {"name": "reverse", "type": "bool", "description": "Walk the range in descending key order.", "required": False},
                        {"name": "column_family", "type": "str", "description": "Optional column family override.", "required": False},
                    ],
                    "returns": {"type": "RocksDbResult", "description": "Matching key-value pairs and truncation state."},
                },
                {
                    "name": "list_column_families",
                    "description": "List the column families available in the configured database.",
                    "parameters": [],
                    "returns": {"type": "RocksDbResult", "description": "Available column family names."},
                },
                {
                    "name": "get_database_stats",
                    "description": "Report size and key-count estimates for the configured database.",
                    "parameters": [],
                    "returns": {"type": "RocksDbResult", "description": "Database statistics."},
                },
                {
                    "name": "put_value",
                    "description": "Write a single key-value pair. Requires the action to allow writes.",
                    "parameters": [
                        {"name": "key", "type": "str", "description": "Key to write.", "required": True},
                        {"name": "value", "type": "Any", "description": "Value to store.", "required": True},
                        {"name": "column_family", "type": "str", "description": "Optional column family override.", "required": False},
                    ],
                    "returns": {"type": "RocksDbResult", "description": "Write confirmation."},
                },
                {
                    "name": "delete_value",
                    "description": "Delete a single key. Requires the action to allow writes.",
                    "parameters": [
                        {"name": "key", "type": "str", "description": "Key to delete.", "required": True},
                        {"name": "column_family", "type": "str", "description": "Optional column family override.", "required": False},
                    ],
                    "returns": {"type": "RocksDbResult", "description": "Delete confirmation."},
                },
                {
                    "name": "write_batch",
                    "description": "Apply several put and delete operations atomically. Requires the action to allow writes.",
                    "parameters": [
                        {"name": "operations", "type": "List[Dict[str, Any]] | str", "description": "Operations as a list or JSON array string, each with op, key, and value.", "required": True},
                        {"name": "column_family", "type": "str", "description": "Optional column family override.", "required": False},
                    ],
                    "returns": {"type": "RocksDbResult", "description": "Batch write confirmation."},
                },
            ],
        }

    def get_functions(self) -> List[str]:
        return [
            "get_value",
            "get_values",
            "key_exists",
            "scan_prefix",
            "scan_range",
            "list_column_families",
            "get_database_stats",
            "put_value",
            "delete_value",
            "write_batch",
        ]

    def set_http_session(self, session: Any) -> None:
        """Override the HTTP session used for RocksDB service calls."""
        self._http_session = session

    def build_instruction_context(self) -> str:
        """Return agent instruction text describing the configured RocksDB store."""
        hint_lines = [f"- {prefix_hint}" for prefix_hint in self.key_prefix_hints] or [
            "- No key prefix hints were configured."
        ]
        access_line = (
            "- Access: read-only"
            if self.read_only
            else "- Access: reads and writes are enabled"
        )
        return (
            f"### RocksDB Store: {self.base_url}\n"
            f"- Column family: {self.column_family}\n"
            f"{access_line}\n"
            f"- Max results per call: {self.max_results}\n"
            f"- Key encoding: {self.key_encoding}, value encoding: {self.value_encoding}\n"
            "- Keys are byte strings sorted lexicographically; prefer prefix and range scans.\n"
            "- Configured key prefix hints:\n"
            + "\n".join(hint_lines)
        )

    @kernel_function(description="Read a single RocksDB value by its exact key. Use this when you already know the full key; use scan_prefix when you only know how the key starts.")
    @plugin_function_logger("RocksDbPlugin")
    def get_value(self, key: str, column_family: Optional[str] = None) -> RocksDbResult:
        try:
            resolved_family = self._resolve_column_family(column_family)
            payload = self._remote_request(
                "POST", "/get", {"key": key, "column_family": resolved_family}
            )
            found = bool(payload.get("found", payload.get("value") is not None))
            value, truncated, byte_length = self._normalize_value(payload.get("value"))

            return self._success(
                {
                    "key": key,
                    "column_family": resolved_family,
                    "found": found,
                    "value": value if found else None,
                    "value_bytes": byte_length,
                    "value_truncated": truncated,
                }
            )
        except Exception as exc:
            return self._failure("get_value", exc, {"key": key})

    @kernel_function(description="Read several RocksDB values in one call using their exact keys. Pass the keys as a list or a JSON array string.")
    @plugin_function_logger("RocksDbPlugin")
    def get_values(
        self,
        keys: Union[str, List[str]],
        column_family: Optional[str] = None,
    ) -> RocksDbResult:
        try:
            resolved_family = self._resolve_column_family(column_family)
            normalized_keys = self._normalize_key_list(keys)
            if not normalized_keys:
                raise ValueError("At least one key is required.")
            if len(normalized_keys) > self.max_results:
                normalized_keys = normalized_keys[: self.max_results]

            payload = self._remote_request(
                "POST",
                "/multi_get",
                {"keys": normalized_keys, "column_family": resolved_family},
            )
            remote_results = payload.get("results")
            if not isinstance(remote_results, list):
                raise RuntimeError("RocksDB service returned an unexpected multi_get payload.")

            results = []
            for entry in remote_results:
                entry_dict = entry if isinstance(entry, dict) else {}
                found = bool(entry_dict.get("found", entry_dict.get("value") is not None))
                value, truncated, byte_length = self._normalize_value(entry_dict.get("value"))
                results.append(
                    {
                        "key": entry_dict.get("key"),
                        "found": found,
                        "value": value if found else None,
                        "value_bytes": byte_length,
                        "value_truncated": truncated,
                    }
                )

            return self._success(
                {
                    "column_family": resolved_family,
                    "requested_key_count": len(normalized_keys),
                    "found_count": sum(1 for entry in results if entry.get("found")),
                    "results": results,
                }
            )
        except Exception as exc:
            return self._failure("get_values", exc, {"key_count": self._safe_length(keys)})

    @kernel_function(description="Check whether a RocksDB key exists without returning its value. Use this for cheap existence checks on large values.")
    @plugin_function_logger("RocksDbPlugin")
    def key_exists(self, key: str, column_family: Optional[str] = None) -> RocksDbResult:
        try:
            resolved_family = self._resolve_column_family(column_family)
            payload = self._remote_request(
                "POST", "/exists", {"key": key, "column_family": resolved_family}
            )
            exists = bool(payload.get("exists", payload.get("found", False)))
            return self._success(
                {"key": key, "column_family": resolved_family, "exists": exists}
            )
        except Exception as exc:
            return self._failure("key_exists", exc, {"key": key})

    @kernel_function(description="List RocksDB key-value pairs whose keys start with a prefix. This is the efficient way to explore a RocksDB store because keys are stored in sorted order.")
    @plugin_function_logger("RocksDbPlugin")
    def scan_prefix(
        self,
        prefix: str,
        limit: Optional[int] = None,
        column_family: Optional[str] = None,
    ) -> RocksDbResult:
        try:
            resolved_family = self._resolve_column_family(column_family)
            effective_limit = self._resolve_limit(limit)
            items, truncated = self._scan(
                column_family=resolved_family,
                prefix=prefix,
                start_key=None,
                end_key=None,
                limit=effective_limit,
                reverse=False,
            )
            return self._success(
                {
                    "column_family": resolved_family,
                    "prefix": prefix,
                    "limit": effective_limit,
                    "item_count": len(items),
                    "is_truncated": truncated,
                    "items": items,
                }
            )
        except Exception as exc:
            return self._failure("scan_prefix", exc, {"prefix": prefix})

    @kernel_function(description="List RocksDB key-value pairs between an inclusive start key and an exclusive end key. Set reverse to walk the range from the highest key downwards.")
    @plugin_function_logger("RocksDbPlugin")
    def scan_range(
        self,
        start_key: Optional[str] = None,
        end_key: Optional[str] = None,
        limit: Optional[int] = None,
        reverse: bool = False,
        column_family: Optional[str] = None,
    ) -> RocksDbResult:
        try:
            resolved_family = self._resolve_column_family(column_family)
            effective_limit = self._resolve_limit(limit)
            normalized_reverse = self._coerce_bool(reverse, False)
            items, truncated = self._scan(
                column_family=resolved_family,
                prefix=None,
                start_key=start_key,
                end_key=end_key,
                limit=effective_limit,
                reverse=normalized_reverse,
            )
            return self._success(
                {
                    "column_family": resolved_family,
                    "start_key": start_key,
                    "end_key": end_key,
                    "reverse": normalized_reverse,
                    "limit": effective_limit,
                    "item_count": len(items),
                    "is_truncated": truncated,
                    "items": items,
                }
            )
        except Exception as exc:
            return self._failure(
                "scan_range", exc, {"start_key": start_key, "end_key": end_key}
            )

    @kernel_function(description="List the column families available in the configured RocksDB database.")
    @plugin_function_logger("RocksDbPlugin")
    def list_column_families(self) -> RocksDbResult:
        try:
            payload = self._remote_request("GET", "/column_families")
            column_families = payload.get("column_families")
            if not isinstance(column_families, list):
                raise RuntimeError(
                    "RocksDB service returned an unexpected column_families payload."
                )

            return self._success(
                {
                    "column_families": column_families,
                    "configured_column_family": self.column_family,
                }
            )
        except Exception as exc:
            return self._failure("list_column_families", exc)

    @kernel_function(description="Report size and key-count estimates for the configured RocksDB database.")
    @plugin_function_logger("RocksDbPlugin")
    def get_database_stats(self) -> RocksDbResult:
        try:
            payload = self._remote_request("GET", "/stats")
            statistics = payload.get("stats", payload)
            return self._success(
                {
                    "column_family": self.column_family,
                    "read_only": self.read_only,
                    "stats": statistics,
                }
            )
        except Exception as exc:
            return self._failure("get_database_stats", exc)

    @kernel_function(description="Write a single RocksDB key-value pair. This is refused when the action is configured as read-only.")
    @plugin_function_logger("RocksDbPlugin")
    def put_value(
        self,
        key: str,
        value: Any,
        column_family: Optional[str] = None,
    ) -> RocksDbResult:
        blocked_result = self._write_guard("put_value")
        if blocked_result is not None:
            return blocked_result

        try:
            resolved_family = self._resolve_column_family(column_family)
            self._remote_request(
                "POST",
                "/put",
                {"key": key, "value": value, "column_family": resolved_family},
            )

            log_event(
                "[ROCKSDB_PLUGIN] Key written",
                extra={"column_family": resolved_family},
                level=logging.INFO,
            )
            return self._success(
                {"key": key, "column_family": resolved_family, "written": True}
            )
        except Exception as exc:
            return self._failure("put_value", exc, {"key": key})

    @kernel_function(description="Delete a single RocksDB key. This is refused when the action is configured as read-only.")
    @plugin_function_logger("RocksDbPlugin")
    def delete_value(self, key: str, column_family: Optional[str] = None) -> RocksDbResult:
        blocked_result = self._write_guard("delete_value")
        if blocked_result is not None:
            return blocked_result

        try:
            resolved_family = self._resolve_column_family(column_family)
            self._remote_request(
                "POST", "/delete", {"key": key, "column_family": resolved_family}
            )

            log_event(
                "[ROCKSDB_PLUGIN] Key deleted",
                extra={"column_family": resolved_family},
                level=logging.INFO,
            )
            return self._success(
                {"key": key, "column_family": resolved_family, "deleted": True}
            )
        except Exception as exc:
            return self._failure("delete_value", exc, {"key": key})

    @kernel_function(description="Apply several RocksDB put and delete operations atomically. Each operation needs an op of put or delete, a key, and a value for puts. This is refused when the action is configured as read-only.")
    @plugin_function_logger("RocksDbPlugin")
    def write_batch(
        self,
        operations: Union[str, List[Dict[str, Any]]],
        column_family: Optional[str] = None,
    ) -> RocksDbResult:
        blocked_result = self._write_guard("write_batch")
        if blocked_result is not None:
            return blocked_result

        try:
            resolved_family = self._resolve_column_family(column_family)
            normalized_operations = self._normalize_batch_operations(operations)
            if not normalized_operations:
                raise ValueError("At least one batch operation is required.")
            if len(normalized_operations) > self.max_results:
                raise ValueError(
                    f"Batch operations are limited to {self.max_results} entries per call."
                )

            self._remote_request(
                "POST",
                "/batch",
                {"operations": normalized_operations, "column_family": resolved_family},
            )

            log_event(
                "[ROCKSDB_PLUGIN] Batch applied",
                extra={
                    "column_family": resolved_family,
                    "operation_count": len(normalized_operations),
                },
                level=logging.INFO,
            )
            return self._success(
                {
                    "column_family": resolved_family,
                    "operation_count": len(normalized_operations),
                    "applied": True,
                }
            )
        except Exception as exc:
            return self._failure("write_batch", exc)

    def _validate_configuration(self) -> None:
        if self.key_encoding not in SUPPORTED_KEY_ENCODINGS:
            raise ValueError("RocksDbPlugin key_encoding must be either 'utf8' or 'base64'.")
        if self.value_encoding not in SUPPORTED_VALUE_ENCODINGS:
            raise ValueError(
                "RocksDbPlugin value_encoding must be one of 'utf8', 'base64', or 'json'."
            )
        if self.max_results < 1 or self.max_results > MAX_RESULTS_CEILING:
            raise ValueError(
                f"RocksDbPlugin max_results must be between 1 and {MAX_RESULTS_CEILING}."
            )
        if self.max_value_bytes < 1 or self.max_value_bytes > MAX_VALUE_BYTES_CEILING:
            raise ValueError(
                f"RocksDbPlugin max_value_bytes must be between 1 and {MAX_VALUE_BYTES_CEILING}."
            )
        if self.timeout < 1 or self.timeout > MAX_TIMEOUT:
            raise ValueError(
                f"RocksDbPlugin timeout must be between 1 and {MAX_TIMEOUT} seconds."
            )

        self.base_url = normalize_rocksdb_base_url(self.base_url)
        if not self.base_url:
            raise ValueError("RocksDbPlugin requires base_url for the RocksDB service.")
        if self.auth_scheme not in SUPPORTED_AUTH_SCHEMES:
            raise ValueError(
                "RocksDbPlugin auth_scheme must be one of 'none', 'bearer', or 'api_key'."
            )
        if self.auth_scheme != AUTH_SCHEME_NONE and not self.auth_key:
            raise ValueError(
                "RocksDbPlugin requires auth.key when auth_scheme is 'bearer' or 'api_key'."
            )

    def _success(self, payload: Dict[str, Any]) -> RocksDbResult:
        return RocksDbResult(dict(payload), self.metadata)

    def _failure(
        self,
        operation: str,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
    ) -> RocksDbResult:
        log_event(
            f"[ROCKSDB_PLUGIN] {operation} failed: {error}",
            extra={"operation": operation, "column_family": self.column_family},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        payload = {"operation": operation, "error": str(error)}
        if context:
            payload.update(context)
        return RocksDbResult(payload, self.metadata)

    def _write_guard(self, operation: str) -> Optional[RocksDbResult]:
        if not self.read_only:
            return None
        return RocksDbResult(
            {
                "operation": operation,
                "error": (
                    f"The '{operation}' operation is blocked because this RocksDB action is "
                    "configured as read-only."
                ),
                "read_only": True,
            },
            self.metadata,
        )

    def _resolve_column_family(self, column_family: Optional[str]) -> str:
        candidate = str(column_family or "").strip()
        return candidate or self.column_family

    def _resolve_limit(self, limit: Optional[int]) -> int:
        if limit in (None, ""):
            return self.max_results
        try:
            requested_limit = int(limit)
        except (TypeError, ValueError):
            return self.max_results
        if requested_limit < 1:
            return self.max_results
        return min(requested_limit, self.max_results)

    def _scan(
        self,
        column_family: str,
        prefix: Optional[str],
        start_key: Optional[str],
        end_key: Optional[str],
        limit: int,
        reverse: bool,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        request_payload = {
            "column_family": column_family,
            "limit": limit,
            "reverse": reverse,
        }
        if prefix not in (None, ""):
            request_payload["prefix"] = prefix
        if start_key not in (None, ""):
            request_payload["start_key"] = start_key
        if end_key not in (None, ""):
            request_payload["end_key"] = end_key

        payload = self._remote_request("POST", "/scan", request_payload)
        remote_items = payload.get("items")
        if not isinstance(remote_items, list):
            raise RuntimeError("RocksDB service returned an unexpected scan payload.")

        items = []
        for entry in remote_items[:limit]:
            entry_dict = entry if isinstance(entry, dict) else {}
            value, truncated, byte_length = self._normalize_value(entry_dict.get("value"))
            items.append(
                {
                    "key": entry_dict.get("key"),
                    "value": value,
                    "value_bytes": byte_length,
                    "value_truncated": truncated,
                }
            )

        is_truncated = bool(payload.get("truncated", len(remote_items) > limit))
        return items, is_truncated

    def _remote_request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        session = self._http_session
        if session is None:
            session = requests.Session()
            self._http_session = session

        request_payload = None
        if payload is not None:
            # The service needs the wire encoding to interpret keys and values correctly.
            request_payload = dict(payload)
            request_payload["key_encoding"] = self.key_encoding
            request_payload["value_encoding"] = self.value_encoding

        response = session.request(
            method,
            f"{self.base_url}{path}",
            json=request_payload,
            headers=self._build_remote_headers(),
            timeout=self.timeout,
            verify=self.verify_tls,
        )

        status_code = getattr(response, "status_code", None)
        if status_code is None or int(status_code) >= 400:
            raise RuntimeError(
                f"RocksDB service request to {path} failed with HTTP {status_code}."
            )

        try:
            body = response.json()
        except Exception as decode_error:
            raise RuntimeError(
                f"RocksDB service request to {path} returned a non-JSON response."
            ) from decode_error

        if not isinstance(body, dict):
            raise RuntimeError(
                f"RocksDB service request to {path} returned an unexpected payload shape."
            )
        return body

    def _build_remote_headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.auth_scheme == AUTH_SCHEME_BEARER and self.auth_key:
            headers["Authorization"] = f"Bearer {self.auth_key}"
        elif self.auth_scheme == AUTH_SCHEME_API_KEY and self.auth_key:
            headers[self.api_key_header] = self.auth_key
        return headers

    def _normalize_value(self, value: Any) -> Tuple[Any, bool, int]:
        """Cap an oversized service value so one record cannot flood the model context."""
        if value is None:
            return None, False, 0

        if isinstance(value, str):
            raw_bytes = value.encode("utf-8", errors="replace")
        else:
            raw_bytes = json.dumps(value, default=str).encode("utf-8")

        byte_length = len(raw_bytes)
        if byte_length <= self.max_value_bytes:
            return value, False, byte_length
        return (
            raw_bytes[: self.max_value_bytes].decode("utf-8", errors="replace"),
            True,
            byte_length,
        )

    def _normalize_key_list(self, keys: Union[str, List[Any]]) -> List[str]:
        candidate_keys = keys
        if isinstance(candidate_keys, str):
            stripped_keys = candidate_keys.strip()
            if stripped_keys.startswith("["):
                try:
                    candidate_keys = json.loads(stripped_keys)
                except (TypeError, ValueError) as decode_error:
                    raise ValueError(
                        "Keys must be a list or a valid JSON array string."
                    ) from decode_error
            else:
                candidate_keys = [
                    part.strip() for part in stripped_keys.split(",") if part.strip()
                ]

        if not isinstance(candidate_keys, (list, tuple)):
            raise ValueError("Keys must be a list or a valid JSON array string.")
        return [str(single_key) for single_key in candidate_keys if str(single_key).strip()]

    def _normalize_batch_operations(
        self, operations: Union[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        candidate_operations = operations
        if isinstance(candidate_operations, str):
            try:
                candidate_operations = json.loads(candidate_operations)
            except (TypeError, ValueError) as decode_error:
                raise ValueError(
                    "Batch operations must be a list or a valid JSON array string."
                ) from decode_error

        if isinstance(candidate_operations, dict):
            candidate_operations = [candidate_operations]
        if not isinstance(candidate_operations, (list, tuple)):
            raise ValueError("Batch operations must be a list or a valid JSON array string.")

        normalized_operations = []
        for operation in candidate_operations:
            if not isinstance(operation, dict):
                raise ValueError("Each batch operation must be an object.")
            operation_name = str(operation.get("op") or "").strip().lower()
            if operation_name not in ("put", "delete"):
                raise ValueError("Batch operations must use an op of 'put' or 'delete'.")
            if str(operation.get("key") or "").strip() == "":
                raise ValueError("Each batch operation requires a key.")
            normalized_operations.append(
                {
                    "op": operation_name,
                    "key": operation.get("key"),
                    "value": operation.get("value"),
                }
            )
        return normalized_operations

    @staticmethod
    def _normalize_choice(value: Any, default_value: str) -> str:
        normalized_value = str(value or "").strip().lower()
        return normalized_value or default_value

    @staticmethod
    def _normalize_prefix_hints(prefix_hints: Any) -> List[str]:
        if prefix_hints in (None, ""):
            return []
        if isinstance(prefix_hints, str):
            candidates = [part.strip() for part in prefix_hints.replace("\n", ",").split(",")]
        elif isinstance(prefix_hints, (list, tuple)):
            candidates = [str(part).strip() for part in prefix_hints]
        else:
            return []
        return [candidate for candidate in candidates if candidate]

    @staticmethod
    def _coerce_bool(value: Any, default_value: bool) -> bool:
        if value in (None, ""):
            return default_value
        if isinstance(value, bool):
            return value
        normalized_value = str(value).strip().lower()
        if normalized_value in ("true", "1", "yes", "on"):
            return True
        if normalized_value in ("false", "0", "no", "off"):
            return False
        return default_value

    @staticmethod
    def _coerce_int(value: Any, default_value: int, field_name: str) -> int:
        if value in (None, ""):
            return default_value
        try:
            return int(value)
        except (TypeError, ValueError) as convert_error:
            raise ValueError(
                f"RocksDbPlugin {field_name} must be an integer."
            ) from convert_error

    @staticmethod
    def _safe_length(value: Any) -> Optional[int]:
        try:
            return len(value)
        except TypeError:
            return None
