# functions_mcp_catalog_implementations.py
"""Shared validation helpers for MCP catalog implementation-specific settings."""

import json
import os
import re
from functools import lru_cache

from jsonschema import Draft7Validator


MCP_IMPLEMENTATION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MCP_IMPLEMENTATION_SCHEMAS_DIR = "implementation_schemas"
MCP_SECRET_FIELD_PATTERN = re.compile(r"(key|secret|password|token|connection)", re.IGNORECASE)
MCP_ALLOWED_SECRET_LIKE_FIELD_NAMES = {"api_key_header_name"}


class McpImplementationValidationError(ValueError):
    """Raised when an MCP catalog implementation block fails validation."""


def normalize_mcp_implementation_id(value):
    """Normalize an MCP catalog implementation identifier."""
    normalized_value = str(value or "").strip().lower()
    normalized_value = re.sub(r"\s+", "_", normalized_value)
    if MCP_IMPLEMENTATION_ID_PATTERN.fullmatch(normalized_value):
        return normalized_value
    return ""


def find_secret_like_field(value, path="", allowed_field_names=None):
    """Return the first secret-like field path in a catalog value, or an empty string."""
    allowed_names = set(allowed_field_names or MCP_ALLOWED_SECRET_LIKE_FIELD_NAMES)
    if isinstance(value, dict):
        for key, child_value in value.items():
            key_text = str(key or "")
            child_path = f"{path}.{key_text}" if path else key_text
            if MCP_SECRET_FIELD_PATTERN.search(key_text) and key_text not in allowed_names:
                return child_path
            secret_path = find_secret_like_field(child_value, child_path, allowed_names)
            if secret_path:
                return secret_path
    elif isinstance(value, list):
        for index, child_value in enumerate(value):
            secret_path = find_secret_like_field(child_value, f"{path}[{index}]", allowed_names)
            if secret_path:
                return secret_path
    return ""


def normalize_mcp_implementation_block(definition):
    """Return a normalized implementation block from a catalog definition."""
    implementation = definition.get("implementation")
    if implementation is None:
        return {}
    if not isinstance(implementation, dict):
        raise McpImplementationValidationError("implementation must be an object.")

    implementation_id = normalize_mcp_implementation_id(implementation.get("id"))
    if not implementation_id or implementation_id != implementation.get("id"):
        raise McpImplementationValidationError("implementation.id is invalid.")

    schema_version = str(implementation.get("schemaVersion") or "1.0.0").strip()
    if not re.fullmatch(r"^[0-9]+\.[0-9]+\.[0-9]+$", schema_version):
        raise McpImplementationValidationError("implementation.schemaVersion is invalid.")

    return {
        "id": implementation_id,
        "schemaVersion": schema_version,
    }


def _load_json_file(file_path):
    with open(file_path, "r", encoding="utf-8") as json_file:
        return json.load(json_file)


def _candidate_schema_paths(catalog_root, definition_file_path, implementation_id, schema_kind):
    schema_file_name = f"{implementation_id}.{schema_kind}.schema.json"
    candidates = [
        os.path.join(catalog_root, MCP_IMPLEMENTATION_SCHEMAS_DIR, schema_file_name),
    ]
    if definition_file_path:
        definition_dir = os.path.dirname(definition_file_path)
        candidates.append(os.path.join(definition_dir, MCP_IMPLEMENTATION_SCHEMAS_DIR, schema_file_name))
        candidates.append(os.path.join(os.path.dirname(definition_dir), MCP_IMPLEMENTATION_SCHEMAS_DIR, schema_file_name))

    seen_paths = set()
    for candidate in candidates:
        normalized_candidate = os.path.abspath(candidate)
        if normalized_candidate in seen_paths:
            continue
        seen_paths.add(normalized_candidate)
        yield normalized_candidate


@lru_cache(maxsize=128)
def _load_implementation_schema(schema_path):
    return _load_json_file(schema_path)


def _find_implementation_schema_path(catalog_root, definition_file_path, implementation_id, schema_kind):
    for schema_path in _candidate_schema_paths(catalog_root, definition_file_path, implementation_id, schema_kind):
        if os.path.isfile(schema_path):
            return schema_path
    return ""


def validate_mcp_implementation_settings(definition, file_path, catalog_root, schema_kind):
    """Validate provider-specific catalog settings against an implementation schema."""
    implementation = normalize_mcp_implementation_block(definition)
    additional_settings = definition.get("additionalSettings") or {}
    if not isinstance(additional_settings, dict):
        raise McpImplementationValidationError("additionalSettings must be an object.")

    if not implementation:
        if additional_settings:
            raise McpImplementationValidationError("additionalSettings requires an implementation block.")
        return {}

    secret_path = find_secret_like_field(additional_settings)
    if secret_path:
        raise McpImplementationValidationError(
            f"additionalSettings contains a secret-like field: {secret_path}."
        )

    schema_path = _find_implementation_schema_path(
        catalog_root,
        file_path,
        implementation["id"],
        schema_kind,
    )
    if not schema_path:
        raise McpImplementationValidationError(
            f"implementation schema '{implementation['id']}.{schema_kind}.schema.json' was not found."
        )

    schema = _load_implementation_schema(schema_path)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(additional_settings), key=lambda error: list(error.path))
    if errors:
        messages = "; ".join(error.message for error in errors)
        raise McpImplementationValidationError(
            f"additionalSettings failed {implementation['id']} implementation validation: {messages}"
        )

    return implementation


def clear_mcp_implementation_schema_cache():
    """Clear cached implementation schemas for tests and admin refresh operations."""
    _load_implementation_schema.cache_clear()
