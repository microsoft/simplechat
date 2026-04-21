# functions_blob_storage_operations.py
"""Shared configuration helpers for the blob storage action."""

from typing import Any, Dict, List, Optional


BLOB_STORAGE_PLUGIN_TYPE = "blob_storage"
BLOB_STORAGE_CAPABILITY_DEFINITIONS = [
    {
        "key": "list_container_contents",
        "function_name": "list_container_contents",
        "label": "List container contents",
        "description": "List blobs in the configured container and optional prefix.",
    },
    {
        "key": "read_file_content",
        "function_name": "read_file_content",
        "label": "Read file content",
        "description": "Read the contents of supported files from the configured container.",
    },
    {
        "key": "upload_file_to_container",
        "function_name": "upload_file_to_container",
        "label": "Upload file to container",
        "description": "Upload supported files into the configured container.",
    },
]

BLOB_STORAGE_FILE_TYPE_DEFINITIONS = [
    {
        "key": "markdown",
        "label": "Markdown",
        "description": "Supports .md and .markdown files stored as UTF-8 text.",
        "extensions": [".md", ".markdown"],
        "content_type": "text/markdown; charset=utf-8",
    }
]


def get_default_blob_storage_capabilities() -> Dict[str, bool]:
    """Return the default enabled blob storage capabilities."""
    return {
        "list_container_contents": True,
        "read_file_content": True,
        "upload_file_to_container": False,
    }


def normalize_blob_storage_capabilities(raw_capabilities: Any = None) -> Dict[str, bool]:
    """Normalize stored blob storage capability settings into a complete boolean map."""
    normalized = get_default_blob_storage_capabilities()

    if raw_capabilities is None:
        return normalized

    if isinstance(raw_capabilities, dict):
        for capability_key in normalized:
            if capability_key in raw_capabilities:
                normalized[capability_key] = bool(raw_capabilities[capability_key])
        return normalized

    if isinstance(raw_capabilities, (list, tuple, set)):
        enabled_items = {str(item or "").strip() for item in raw_capabilities if str(item or "").strip()}
        return {
            definition["key"]: (
                definition["key"] in enabled_items or definition["function_name"] in enabled_items
            )
            for definition in BLOB_STORAGE_CAPABILITY_DEFINITIONS
        }

    return normalized


def get_blob_storage_enabled_function_names(raw_capabilities: Any = None) -> List[str]:
    """Return the enabled blob storage function names in display order."""
    normalized = normalize_blob_storage_capabilities(raw_capabilities)
    return [
        definition["function_name"]
        for definition in BLOB_STORAGE_CAPABILITY_DEFINITIONS
        if normalized.get(definition["key"], False)
    ]


def resolve_blob_storage_action_capabilities(
    action_capability_map: Any,
    action_defaults: Any = None,
    action_id: Optional[str] = None,
    action_name: Optional[str] = None,
) -> Dict[str, bool]:
    """Merge per-agent overrides with action-level default blob storage capabilities."""
    resolved_defaults = normalize_blob_storage_capabilities(action_defaults)

    if not isinstance(action_capability_map, dict):
        return resolved_defaults

    for candidate_key in (str(action_id or "").strip(), str(action_name or "").strip()):
        if candidate_key and candidate_key in action_capability_map:
            return normalize_blob_storage_capabilities(action_capability_map.get(candidate_key))

    return resolved_defaults


def get_default_blob_storage_read_file_types() -> Dict[str, bool]:
    """Return the default enabled file types for blob reads."""
    return {definition["key"]: True for definition in BLOB_STORAGE_FILE_TYPE_DEFINITIONS}


def get_default_blob_storage_upload_file_types() -> Dict[str, bool]:
    """Return the default enabled file types for blob uploads."""
    return {definition["key"]: True for definition in BLOB_STORAGE_FILE_TYPE_DEFINITIONS}


def _normalize_blob_storage_file_types(raw_file_types: Any, defaults: Dict[str, bool]) -> Dict[str, bool]:
    normalized = dict(defaults)

    if raw_file_types is None:
        return normalized

    if isinstance(raw_file_types, dict):
        for file_type_key in normalized:
            if file_type_key in raw_file_types:
                normalized[file_type_key] = bool(raw_file_types[file_type_key])
        return normalized

    if isinstance(raw_file_types, (list, tuple, set)):
        enabled_items = {str(item or "").strip() for item in raw_file_types if str(item or "").strip()}
        for file_type_key in normalized:
            normalized[file_type_key] = file_type_key in enabled_items
        return normalized

    return normalized


def normalize_blob_storage_read_file_types(raw_file_types: Any = None) -> Dict[str, bool]:
    """Normalize stored blob read file type settings into a complete boolean map."""
    return _normalize_blob_storage_file_types(raw_file_types, get_default_blob_storage_read_file_types())


def normalize_blob_storage_upload_file_types(raw_file_types: Any = None) -> Dict[str, bool]:
    """Normalize stored blob upload file type settings into a complete boolean map."""
    return _normalize_blob_storage_file_types(raw_file_types, get_default_blob_storage_upload_file_types())


def get_enabled_blob_storage_read_file_types(raw_file_types: Any = None) -> List[str]:
    """Return enabled file types for blob reads in display order."""
    normalized = normalize_blob_storage_read_file_types(raw_file_types)
    return [definition["key"] for definition in BLOB_STORAGE_FILE_TYPE_DEFINITIONS if normalized.get(definition["key"], False)]


def get_enabled_blob_storage_upload_file_types(raw_file_types: Any = None) -> List[str]:
    """Return enabled file types for blob uploads in display order."""
    normalized = normalize_blob_storage_upload_file_types(raw_file_types)
    return [definition["key"] for definition in BLOB_STORAGE_FILE_TYPE_DEFINITIONS if normalized.get(definition["key"], False)]


def parse_storage_connection_string(connection_string: str) -> Dict[str, str]:
    """Parse an Azure Storage connection string into key/value pairs."""
    parsed: Dict[str, str] = {}
    for segment in str(connection_string or "").split(";"):
        normalized_segment = segment.strip()
        if not normalized_segment or "=" not in normalized_segment:
            continue
        key, value = normalized_segment.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def derive_blob_endpoint_from_connection_string(connection_string: str) -> str:
    """Derive the blob endpoint from a storage connection string when possible."""
    parsed = parse_storage_connection_string(connection_string)
    if not parsed:
        return ""

    if str(parsed.get("UseDevelopmentStorage", "")).strip().lower() == "true":
        return "http://127.0.0.1:10000/devstoreaccount1"

    blob_endpoint = str(parsed.get("BlobEndpoint") or "").strip()
    if blob_endpoint:
        return blob_endpoint.rstrip("/")

    account_name = str(parsed.get("AccountName") or "").strip()
    if not account_name:
        return ""

    protocol = str(parsed.get("DefaultEndpointsProtocol") or "https").strip() or "https"
    endpoint_suffix = str(parsed.get("EndpointSuffix") or "core.windows.net").strip() or "core.windows.net"
    return f"{protocol}://{account_name}.blob.{endpoint_suffix}".rstrip("/")


def normalize_blob_prefix(blob_prefix: str = "") -> str:
    """Normalize a stored blob prefix to a clean slash-separated path fragment."""
    return str(blob_prefix or "").strip().strip("/")


def detect_blob_storage_file_type(blob_name: str) -> str:
    """Return the normalized supported file type for a blob name, or an empty string."""
    candidate = str(blob_name or "").strip().lower()
    for definition in BLOB_STORAGE_FILE_TYPE_DEFINITIONS:
        for extension in definition["extensions"]:
            if candidate.endswith(extension):
                return definition["key"]
    return ""


def is_blob_storage_file_type_enabled(blob_name: str, enabled_file_types: Any) -> bool:
    """Return True when the blob name matches one of the enabled file types."""
    file_type = detect_blob_storage_file_type(blob_name)
    if not file_type:
        return False

    normalized = _normalize_blob_storage_file_types(
        enabled_file_types,
        {definition["key"]: True for definition in BLOB_STORAGE_FILE_TYPE_DEFINITIONS},
    )
    return bool(normalized.get(file_type, False))


def get_blob_storage_content_type(file_type: str) -> str:
    """Return the preferred content type for a supported blob file type."""
    normalized_type = str(file_type or "").strip().lower()
    for definition in BLOB_STORAGE_FILE_TYPE_DEFINITIONS:
        if definition["key"] == normalized_type:
            return definition["content_type"]
    return "application/octet-stream"