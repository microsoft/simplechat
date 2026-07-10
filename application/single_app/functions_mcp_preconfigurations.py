# functions_mcp_preconfigurations.py
"""Validated server-side catalog for MCP server preconfigurations."""

import copy
import json
import logging
import os
import re
from functools import lru_cache
from json import JSONDecodeError

try:
    from flask import current_app
except ImportError:  # pragma: no cover - supports source-level functional tests without Flask installed.
    current_app = None
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from functions_appinsights import log_event
from functions_mcp_destinations import (
    MCP_DESTINATION_SCOPE_GLOBAL,
    MCP_DESTINATION_SCOPE_GROUP,
    MCP_DESTINATION_SCOPE_PERSONAL,
    evaluate_mcp_destination_policy,
    get_mcp_destination_policy_config,
    normalize_mcp_destination_scope,
)
from functions_mcp_operations import (
    MCP_PLUGIN_TYPE,
    MCP_REMOTE_TRANSPORTS,
    normalize_mcp_auth_method,
    normalize_mcp_transport,
    validate_mcp_endpoint_for_transport,
)
from functions_mcp_presets import MCP_DEFAULT_SERVER_PRESET_ID, mcp_server_preset_exists, normalize_mcp_preset_id


MCP_DEFAULT_SERVER_PRECONFIGURATION_ID = ""
MCP_PRECONFIGURATION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MCP_PRECONFIGURATION_SCHEMA_FILE = "mcp_server_preconfiguration.schema.json"
MCP_PRECONFIGURATION_DEFINITIONS_DIR = "definitions"
MCP_PRECONFIGURATION_PATHS_ENV = "SIMPLECHAT_MCP_PRECONFIGURATION_PATHS"
ENABLE_LOCAL_MCP_PRECONFIGURATION_ENV = "ENABLE_LOCAL_MCP_PRECONFIGURATION"
MCP_PRECONFIGURATION_BUNDLED_SOURCE = "bundled"
MCP_PRECONFIGURATION_CUSTOM_SOURCE = "custom"

MCP_PRECONFIGURATIONS_ROOT = os.path.join(os.path.dirname(__file__), "mcp_preconfigurations")
MCP_PRECONFIGURATION_SCHEMA_PATH = os.path.join(MCP_PRECONFIGURATIONS_ROOT, MCP_PRECONFIGURATION_SCHEMA_FILE)
MCP_BUNDLED_PRECONFIGURATION_DIR = os.path.join(
    MCP_PRECONFIGURATIONS_ROOT,
    MCP_PRECONFIGURATION_DEFINITIONS_DIR,
)
MCP_VALID_PRECONFIGURATION_SCOPES = {
    MCP_DESTINATION_SCOPE_PERSONAL,
    MCP_DESTINATION_SCOPE_GROUP,
    MCP_DESTINATION_SCOPE_GLOBAL,
}
MCP_SECRET_FIELD_PATTERN = re.compile(r"(key|secret|password|token|connection)", re.IGNORECASE)
MCP_ALLOWED_SECRET_LIKE_DEFAULT_FIELDS = {"api_key_header_name"}


class McpPreconfigurationValidationError(ValueError):
    """Raised when an MCP preconfiguration definition fails validation."""


def normalize_mcp_preconfiguration_id(value):
    """Normalize a preconfiguration identifier without accepting unsafe file path syntax."""
    normalized_value = str(value or "").strip().lower()
    normalized_value = re.sub(r"\s+", "_", normalized_value)
    aliases = {
        "": MCP_DEFAULT_SERVER_PRECONFIGURATION_ID,
        "custom": MCP_DEFAULT_SERVER_PRECONFIGURATION_ID,
        "none": MCP_DEFAULT_SERVER_PRECONFIGURATION_ID,
    }
    normalized_value = aliases.get(normalized_value, normalized_value)
    if normalized_value == MCP_DEFAULT_SERVER_PRECONFIGURATION_ID:
        return normalized_value
    if not MCP_PRECONFIGURATION_ID_PATTERN.fullmatch(normalized_value):
        return MCP_DEFAULT_SERVER_PRECONFIGURATION_ID
    return normalized_value


def _load_json_file(file_path):
    with open(file_path, "r", encoding="utf-8") as json_file:
        return json.load(json_file)


@lru_cache(maxsize=1)
def _load_mcp_preconfiguration_schema():
    return _load_json_file(MCP_PRECONFIGURATION_SCHEMA_PATH)


def _get_current_app_config_value(key, default=None):
    if current_app is None:
        return default
    try:
        return current_app.config.get(key, default)
    except RuntimeError:
        return default


def _get_custom_preconfiguration_directories():
    raw_paths = _get_current_app_config_value(
        "SIMPLECHAT_MCP_PRECONFIGURATION_PATHS",
        os.getenv(MCP_PRECONFIGURATION_PATHS_ENV, ""),
    )
    directories = []
    for raw_path in raw_paths.split(os.pathsep):
        directory = raw_path.strip()
        if directory:
            directories.append(directory)
    return directories


def _get_preconfiguration_source_directories():
    directories = [(MCP_BUNDLED_PRECONFIGURATION_DIR, MCP_PRECONFIGURATION_BUNDLED_SOURCE)]
    directories.extend(
        (custom_dir, MCP_PRECONFIGURATION_CUSTOM_SOURCE)
        for custom_dir in _get_custom_preconfiguration_directories()
    )
    return directories


def _iter_preconfiguration_definition_paths():
    for directory, source in _get_preconfiguration_source_directories():
        if not os.path.isdir(directory):
            log_event(
                f"[MCPPreconfigurations] Preconfiguration directory does not exist: {directory}",
                level=logging.WARNING,
                debug_only=True,
            )
            continue

        for file_name in sorted(os.listdir(directory)):
            if file_name.lower().endswith(".json"):
                yield os.path.join(directory, file_name), source


def _contains_secret_like_field(value, path=""):
    if isinstance(value, dict):
        for key, child_value in value.items():
            key_text = str(key or "")
            child_path = f"{path}.{key_text}" if path else key_text
            if MCP_SECRET_FIELD_PATTERN.search(key_text) and key_text not in MCP_ALLOWED_SECRET_LIKE_DEFAULT_FIELDS:
                return child_path
            secret_path = _contains_secret_like_field(child_value, child_path)
            if secret_path:
                return secret_path
    elif isinstance(value, list):
        for index, child_value in enumerate(value):
            secret_path = _contains_secret_like_field(child_value, f"{path}[{index}]")
            if secret_path:
                return secret_path
    return ""


def _validate_mcp_preconfiguration(definition, file_path):
    schema = _load_mcp_preconfiguration_schema()
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(definition), key=lambda error: list(error.path))
    if errors:
        messages = "; ".join(error.message for error in errors)
        raise McpPreconfigurationValidationError(
            f"{os.path.basename(file_path)} failed schema validation: {messages}"
        )

    preconfiguration_id = normalize_mcp_preconfiguration_id(definition.get("id"))
    if definition.get("id") != preconfiguration_id:
        raise McpPreconfigurationValidationError(
            f"{os.path.basename(file_path)} has an invalid preconfiguration id."
        )

    file_stem = os.path.splitext(os.path.basename(file_path))[0].lower()
    if file_stem != preconfiguration_id:
        raise McpPreconfigurationValidationError(
            f"{os.path.basename(file_path)} must use a file name that matches preconfiguration id "
            f"'{preconfiguration_id}'."
        )

    preset_id = normalize_mcp_preset_id(definition.get("presetId") or MCP_DEFAULT_SERVER_PRESET_ID)
    if not mcp_server_preset_exists(preset_id):
        raise McpPreconfigurationValidationError(
            f"{os.path.basename(file_path)} references unavailable MCP preset '{preset_id}'."
        )

    transport = normalize_mcp_transport(definition.get("transport"))
    if transport not in MCP_REMOTE_TRANSPORTS:
        raise McpPreconfigurationValidationError(
            f"{os.path.basename(file_path)} must use a remote MCP transport."
        )

    endpoint_errors = validate_mcp_endpoint_for_transport(definition.get("endpoint"), transport)
    if endpoint_errors:
        raise McpPreconfigurationValidationError(
            f"{os.path.basename(file_path)} has an invalid endpoint: {'; '.join(endpoint_errors)}"
        )

    auth_method = normalize_mcp_auth_method((definition.get("defaults") or {}).get("auth_method"))
    if definition.get("authRequirement") == "none" and auth_method != "none":
        raise McpPreconfigurationValidationError(
            f"{os.path.basename(file_path)} cannot require auth defaults when authRequirement is none."
        )

    secret_path = _contains_secret_like_field(definition.get("defaults", {}))
    if secret_path:
        raise McpPreconfigurationValidationError(
            f"{os.path.basename(file_path)} contains a secret-like default field: {secret_path}."
        )


def _is_development_preconfiguration_enabled(definition):
    if not definition.get("developmentOnly", False):
        return True
    configured_value = _get_current_app_config_value(
        "ENABLE_LOCAL_MCP_PRECONFIGURATION",
        os.getenv(ENABLE_LOCAL_MCP_PRECONFIGURATION_ENV, "false"),
    )
    if isinstance(configured_value, bool):
        return configured_value
    return str(configured_value).strip().lower() == "true"


def _sanitize_preconfiguration_for_client(definition, source):
    preconfiguration = copy.deepcopy(definition)
    preconfiguration["source"] = source
    return preconfiguration


@lru_cache(maxsize=1)
def load_mcp_server_preconfigurations():
    """Load, validate, and return enabled MCP server preconfigurations."""
    preconfiguration_by_id = {}

    for file_path, source in _iter_preconfiguration_definition_paths():
        try:
            definition = _load_json_file(file_path)
            _validate_mcp_preconfiguration(definition, file_path)
        except (OSError, JSONDecodeError, ValidationError, McpPreconfigurationValidationError) as exc:
            log_event(
                f"[MCPPreconfigurations] Failed to load MCP preconfiguration definition: {exc}",
                level=logging.WARNING,
                debug_only=True,
            )
            continue

        if not definition.get("enabled", True) or not _is_development_preconfiguration_enabled(definition):
            continue

        preconfiguration = _sanitize_preconfiguration_for_client(definition, source)
        preconfiguration_by_id[preconfiguration["id"]] = preconfiguration

    return sorted(
        preconfiguration_by_id.values(),
        key=lambda item: (item.get("sortOrder", 100), item.get("displayName", ""), item.get("id", "")),
    )


def get_mcp_server_preconfiguration(preconfiguration_id):
    """Return one enabled MCP server preconfiguration by id, or None."""
    normalized_id = normalize_mcp_preconfiguration_id(preconfiguration_id)
    if not normalized_id:
        return None
    preconfigurations = {
        preconfiguration["id"]: preconfiguration
        for preconfiguration in load_mcp_server_preconfigurations()
    }
    return preconfigurations.get(normalized_id)


def _is_scope_eligible(preconfiguration, action_scope):
    normalized_scope = normalize_mcp_destination_scope(action_scope)
    scope_eligibility = preconfiguration.get("scopeEligibility")
    if not isinstance(scope_eligibility, list) or not scope_eligibility:
        return True
    normalized_scopes = {
        normalize_mcp_destination_scope(scope)
        for scope in scope_eligibility
        if normalize_mcp_destination_scope(scope) in MCP_VALID_PRECONFIGURATION_SCOPES
    }
    return normalized_scope in normalized_scopes


def _build_preconfiguration_manifest(preconfiguration):
    defaults = preconfiguration.get("defaults") if isinstance(preconfiguration.get("defaults"), dict) else {}
    additional_fields = dict(defaults)
    additional_fields["transport"] = preconfiguration.get("transport")
    additional_fields["server_profile"] = preconfiguration.get("presetId") or MCP_DEFAULT_SERVER_PRESET_ID
    additional_fields["preconfiguration_id"] = preconfiguration.get("id")
    return {
        "name": preconfiguration.get("id") or "mcp_preconfiguration",
        "displayName": preconfiguration.get("displayName") or preconfiguration.get("id") or "MCP Preconfiguration",
        "description": preconfiguration.get("description") or "",
        "type": MCP_PLUGIN_TYPE,
        "endpoint": preconfiguration.get("endpoint") or "",
        "additionalFields": additional_fields,
        "auth": {
            "type": "none",
        },
    }


def _is_destination_policy_eligible(preconfiguration, action_scope, scope_id="", user_id="", settings=None):
    policy_config = get_mcp_destination_policy_config(settings, user_id=user_id)
    decision = evaluate_mcp_destination_policy(
        _build_preconfiguration_manifest(preconfiguration),
        scope_type=action_scope,
        scope_id=scope_id,
        policy_config=policy_config,
        user_id=user_id,
    )
    return decision.get("allowed", False)


def build_mcp_server_preconfigurations_response(
    action_scope=MCP_DESTINATION_SCOPE_PERSONAL,
    scope_id="",
    user_id="",
    settings=None,
):
    """Return the API response payload for MCP server preconfigurations."""
    normalized_scope = normalize_mcp_destination_scope(action_scope)
    preconfigurations = [
        copy.deepcopy(preconfiguration)
        for preconfiguration in load_mcp_server_preconfigurations()
        if (
            _is_scope_eligible(preconfiguration, normalized_scope)
            and _is_destination_policy_eligible(
                preconfiguration,
                normalized_scope,
                scope_id=scope_id,
                user_id=user_id,
                settings=settings,
            )
        )
    ]
    return {
        "defaultPreconfiguration": MCP_DEFAULT_SERVER_PRECONFIGURATION_ID,
        "scope": normalized_scope,
        "preconfigurations": preconfigurations,
    }


def clear_mcp_server_preconfiguration_cache():
    """Clear preconfiguration caches for tests or future admin refresh actions."""
    load_mcp_server_preconfigurations.cache_clear()
    _load_mcp_preconfiguration_schema.cache_clear()
