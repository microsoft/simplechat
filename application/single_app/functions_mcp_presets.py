# functions_mcp_presets.py
"""Validated server-side catalog for MCP server presets."""

import copy
import json
import logging
import os
import re
from functools import lru_cache

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from functions_appinsights import log_event
from functions_mcp_catalog_implementations import (
    McpImplementationValidationError,
    clear_mcp_implementation_schema_cache,
    find_secret_like_field,
    validate_mcp_implementation_settings,
)


MCP_DEFAULT_SERVER_PRESET_ID = "generic"
MCP_PRESET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MCP_PRESET_SCHEMA_FILE = "mcp_server_preset.schema.json"
MCP_PRESET_DEFINITIONS_DIR = "definitions"
MCP_PRESET_PATHS_ENV = "SIMPLECHAT_MCP_PRESET_PATHS"
MCP_PRESET_BUNDLED_SOURCE = "bundled"
MCP_PRESET_CUSTOM_SOURCE = "custom"

MCP_PRESETS_ROOT = os.path.join(os.path.dirname(__file__), "mcp_presets")
MCP_PRESET_SCHEMA_PATH = os.path.join(MCP_PRESETS_ROOT, MCP_PRESET_SCHEMA_FILE)
MCP_BUNDLED_PRESET_DIR = os.path.join(MCP_PRESETS_ROOT, MCP_PRESET_DEFINITIONS_DIR)

MCP_FALLBACK_GENERIC_PRESET = {
    "id": MCP_DEFAULT_SERVER_PRESET_ID,
    "version": "1.0.0",
    "displayName": "Generic MCP Server",
    "description": "Default MCP server preset for standards-compliant MCP servers.",
    "provider": "Generic",
    "enabled": True,
    "sortOrder": 10,
    "defaults": {
        "transport": "streamable_http",
        "auth_method": "none",
        "api_key_header_name": "X-API-Key",
        "load_tools": True,
        "load_prompts": False,
        "request_timeout": 30,
        "connect_timeout": 10,
        "sse_read_timeout": 300,
        "retry_count": 0,
        "retry_backoff_seconds": 1,
        "allowed_tool_names": [],
    },
    "ui": {
        "helpText": "Use generic unless the server needs a specific compatibility preset.",
        "endpointPlaceholder": "https://example.com/mcp",
        "websocketEndpointPlaceholder": "wss://example.com/mcp",
    },
    "constraints": {
        "allowedTransports": ["streamable_http", "sse", "websocket", "stdio"],
        "allowedAuthMethods": ["none", "bearer", "api_key", "basic", "identity"],
        "customHeadersAllowed": True,
        "stdioAllowed": True,
    },
    "implementation": {
        "id": MCP_DEFAULT_SERVER_PRESET_ID,
        "schemaVersion": "1.0.0",
    },
    "additionalSettings": {
        "compatibilityProfile": "standards_compliant",
    },
    "suggestedHeaders": [],
    "warnings": [],
}


class McpPresetValidationError(ValueError):
    """Raised when an MCP preset definition fails validation."""


def normalize_mcp_preset_id(value):
    """Normalize a preset identifier without accepting unsafe file path syntax."""
    normalized_value = str(value or "").strip().lower()
    normalized_value = re.sub(r"\s+", "_", normalized_value)
    aliases = {
        "": MCP_DEFAULT_SERVER_PRESET_ID,
        "default": MCP_DEFAULT_SERVER_PRESET_ID,
        "standard": MCP_DEFAULT_SERVER_PRESET_ID,
        "generic": MCP_DEFAULT_SERVER_PRESET_ID,
        "splunk_mcp": "splunk",
        "splunk-enterprise": "splunk",
        "splunk_enterprise": "splunk",
    }
    normalized_value = aliases.get(normalized_value, normalized_value)
    if not MCP_PRESET_ID_PATTERN.fullmatch(normalized_value):
        return MCP_DEFAULT_SERVER_PRESET_ID
    return normalized_value


def _load_json_file(file_path):
    with open(file_path, "r", encoding="utf-8") as json_file:
        return json.load(json_file)


@lru_cache(maxsize=1)
def _load_mcp_preset_schema():
    return _load_json_file(MCP_PRESET_SCHEMA_PATH)


def _get_custom_preset_directories():
    raw_paths = os.getenv(MCP_PRESET_PATHS_ENV, "")
    directories = []
    for raw_path in raw_paths.split(os.pathsep):
        directory = raw_path.strip()
        if directory:
            directories.append(directory)
    return directories


def _get_preset_source_directories():
    directories = [(MCP_BUNDLED_PRESET_DIR, MCP_PRESET_BUNDLED_SOURCE)]
    directories.extend(
        (custom_dir, MCP_PRESET_CUSTOM_SOURCE)
        for custom_dir in _get_custom_preset_directories()
    )
    return directories


def _iter_preset_definition_paths():
    for directory, source in _get_preset_source_directories():
        if not os.path.isdir(directory):
            log_event(
                f"[MCPPresets] Preset directory does not exist: {directory}",
                level=logging.WARNING,
                debug_only=True,
            )
            continue

        for file_name in sorted(os.listdir(directory)):
            if file_name.lower().endswith(".json"):
                yield os.path.join(directory, file_name), source


def _validate_mcp_preset(definition, file_path):
    schema = _load_mcp_preset_schema()
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(definition), key=lambda error: list(error.path))
    if errors:
        messages = "; ".join(error.message for error in errors)
        raise McpPresetValidationError(f"{os.path.basename(file_path)} failed schema validation: {messages}")

    preset_id = normalize_mcp_preset_id(definition.get("id"))
    if definition.get("id") != preset_id:
        raise McpPresetValidationError(f"{os.path.basename(file_path)} has an invalid preset id.")

    file_stem = os.path.splitext(os.path.basename(file_path))[0].lower()
    if file_stem != preset_id:
        raise McpPresetValidationError(
            f"{os.path.basename(file_path)} must use a file name that matches preset id '{preset_id}'."
        )

    secret_path = find_secret_like_field(definition.get("defaults", {}))
    if secret_path:
        raise McpPresetValidationError(
            f"{os.path.basename(file_path)} contains a secret-like default field: {secret_path}."
        )

    validate_mcp_implementation_settings(
        definition,
        file_path,
        MCP_PRESETS_ROOT,
        "preset",
    )


def _sanitize_preset_for_client(definition, source):
    preset = copy.deepcopy(definition)
    preset["source"] = source
    preset.setdefault("implementation", {})
    preset.setdefault("additionalSettings", {})
    return preset


@lru_cache(maxsize=1)
def load_mcp_server_presets():
    """Load, validate, and return enabled MCP server presets."""
    preset_by_id = {}

    for file_path, source in _iter_preset_definition_paths():
        try:
            definition = _load_json_file(file_path)
            _validate_mcp_preset(definition, file_path)
        except (
            OSError,
            json.JSONDecodeError,
            ValidationError,
            McpImplementationValidationError,
            McpPresetValidationError,
        ) as exc:
            log_event(
                f"[MCPPresets] Failed to load MCP preset definition: {exc}",
                level=logging.WARNING,
                debug_only=True,
            )
            continue

        if not definition.get("enabled", True):
            continue

        preset = _sanitize_preset_for_client(definition, source)
        preset_by_id[preset["id"]] = preset

    if MCP_DEFAULT_SERVER_PRESET_ID not in preset_by_id:
        fallback = copy.deepcopy(MCP_FALLBACK_GENERIC_PRESET)
        fallback["source"] = "fallback"
        preset_by_id[MCP_DEFAULT_SERVER_PRESET_ID] = fallback
        log_event(
            "[MCPPresets] Generic MCP preset was not loaded; using fallback definition.",
            level=logging.WARNING,
            debug_only=True,
        )

    return sorted(
        preset_by_id.values(),
        key=lambda preset: (preset.get("sortOrder", 100), preset.get("displayName", ""), preset.get("id", "")),
    )


def get_mcp_server_preset(preset_id):
    """Return one enabled MCP server preset by id, falling back to generic."""
    normalized_id = normalize_mcp_preset_id(preset_id)
    presets = {preset["id"]: preset for preset in load_mcp_server_presets()}
    return presets.get(normalized_id) or presets[MCP_DEFAULT_SERVER_PRESET_ID]


def mcp_server_preset_exists(preset_id):
    """Return True when the normalized preset id exists in the enabled catalog."""
    normalized_id = normalize_mcp_preset_id(preset_id)
    return any(preset["id"] == normalized_id for preset in load_mcp_server_presets())


def build_mcp_server_presets_response():
    """Return the API response payload for MCP server presets."""
    return {
        "defaultPreset": MCP_DEFAULT_SERVER_PRESET_ID,
        "presets": copy.deepcopy(load_mcp_server_presets()),
    }


def clear_mcp_server_preset_cache():
    """Clear preset caches for tests or future admin refresh actions."""
    load_mcp_server_presets.cache_clear()
    _load_mcp_preset_schema.cache_clear()
    clear_mcp_implementation_schema_cache()
