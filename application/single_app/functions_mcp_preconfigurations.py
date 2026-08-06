# functions_mcp_preconfigurations.py
"""Validated server-side catalog for MCP server preconfigurations."""

import copy
import json
import logging
import os
import re
from functools import lru_cache

try:
    from flask import current_app
except ImportError:  # pragma: no cover - supports source-level functional tests without Flask installed.
    current_app = None
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from functions_appinsights import log_event
from functions_mcp_catalog_implementations import (
    McpImplementationValidationError,
    clear_mcp_implementation_schema_cache,
    find_secret_like_field,
    validate_mcp_implementation_settings,
)
from functions_mcp_destinations import (
    MCP_DESTINATION_SCOPE_GLOBAL,
    MCP_DESTINATION_SCOPE_GROUP,
    MCP_DESTINATION_SCOPE_PERSONAL,
    McpDestinationPolicyError,
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
MCP_PRECONFIGURATION_CATALOG_TIER_PUBLIC = "public"
MCP_PRECONFIGURATION_CATALOG_TIER_ENTERPRISE = "enterprise"
MCP_PRECONFIGURATION_AUTH_TIER_PUBLIC = "public_unauthenticated"
MCP_PRECONFIGURATION_AUTH_TIER_USER_CREDENTIAL = "user_supplied_credential"
MCP_PRECONFIGURATION_AUTH_TIER_ENTRA = "delegated_oauth_entra"
MCP_PRECONFIGURATION_DEPLOYMENT_HOSTED_REMOTE = "hosted_remote"
MCP_PRECONFIGURATION_POLICY_PREFIX = "preconfiguration:"
MCP_DESTINATION_POLICY_PREFIXES_WITHOUT_ENDPOINT_REVIEW = (
    MCP_PRECONFIGURATION_POLICY_PREFIX,
    "preset:",
    "transport:",
)
MCP_ENTERPRISE_REQUIRED_GOVERNANCE_GATES = {
    "destination_allowlist",
    "preconfiguration_policy",
    "per_tool_allowlist",
    "audit_logging",
    "identity_review",
}

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


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_catalog_tier(value):
    normalized_tier = str(value or "").strip().lower()
    if normalized_tier == MCP_PRECONFIGURATION_CATALOG_TIER_ENTERPRISE:
        return MCP_PRECONFIGURATION_CATALOG_TIER_ENTERPRISE
    return MCP_PRECONFIGURATION_CATALOG_TIER_PUBLIC


def _default_auth_tier_for_requirement(auth_requirement):
    normalized_requirement = str(auth_requirement or "").strip().lower()
    if normalized_requirement == "none":
        return MCP_PRECONFIGURATION_AUTH_TIER_PUBLIC
    if normalized_requirement == "identity":
        return MCP_PRECONFIGURATION_AUTH_TIER_ENTRA
    return MCP_PRECONFIGURATION_AUTH_TIER_USER_CREDENTIAL


def _default_deployment_model(definition):
    if definition.get("developmentOnly", False):
        return "local_reference"
    return MCP_PRECONFIGURATION_DEPLOYMENT_HOSTED_REMOTE


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
                f"[MCP_PRECONFIGURATIONS] Preconfiguration directory does not exist: {directory}",
                level=logging.WARNING,
                debug_only=True,
            )
            continue

        for file_name in sorted(os.listdir(directory)):
            if file_name.lower().endswith(".json"):
                yield os.path.join(directory, file_name), source


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

    secret_path = find_secret_like_field(definition.get("defaults", {}))
    if secret_path:
        raise McpPreconfigurationValidationError(
            f"{os.path.basename(file_path)} contains a secret-like default field: {secret_path}."
        )

    validate_mcp_implementation_settings(
        definition,
        file_path,
        MCP_PRECONFIGURATIONS_ROOT,
        "preconfiguration",
    )

    catalog_tier = _normalize_catalog_tier(definition.get("catalogTier"))
    if catalog_tier == MCP_PRECONFIGURATION_CATALOG_TIER_ENTERPRISE:
        if definition.get("authRequirement") == "none":
            raise McpPreconfigurationValidationError(
                f"{os.path.basename(file_path)} enterprise templates must require identity or credentials."
            )
        auth_tier = definition.get("authTier") or _default_auth_tier_for_requirement(definition.get("authRequirement"))
        if auth_tier == MCP_PRECONFIGURATION_AUTH_TIER_PUBLIC:
            raise McpPreconfigurationValidationError(
                f"{os.path.basename(file_path)} enterprise templates cannot use public unauthenticated auth tier."
            )
        if not _coerce_bool(definition.get("disabledByDefault")):
            raise McpPreconfigurationValidationError(
                f"{os.path.basename(file_path)} enterprise templates must be disabled by default."
            )
        if not _coerce_bool(definition.get("requiresAdminEnablement")):
            raise McpPreconfigurationValidationError(
                f"{os.path.basename(file_path)} enterprise templates must require admin enablement."
            )
        governance_gates = set(definition.get("requiredGovernanceGates") or [])
        missing_gates = sorted(MCP_ENTERPRISE_REQUIRED_GOVERNANCE_GATES - governance_gates)
        if missing_gates:
            raise McpPreconfigurationValidationError(
                f"{os.path.basename(file_path)} enterprise template is missing governance gates: "
                f"{', '.join(missing_gates)}."
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
    preconfiguration["catalogTier"] = _normalize_catalog_tier(preconfiguration.get("catalogTier"))
    preconfiguration["authTier"] = preconfiguration.get("authTier") or _default_auth_tier_for_requirement(
        preconfiguration.get("authRequirement")
    )
    preconfiguration["deploymentModel"] = preconfiguration.get("deploymentModel") or _default_deployment_model(
        preconfiguration
    )
    preconfiguration["disabledByDefault"] = _coerce_bool(preconfiguration.get("disabledByDefault"))
    preconfiguration["requiresAdminEnablement"] = _coerce_bool(preconfiguration.get("requiresAdminEnablement"))
    preconfiguration["requiresEndpointReview"] = _coerce_bool(preconfiguration.get("requiresEndpointReview"))
    preconfiguration.setdefault("requiredGovernanceGates", [])
    preconfiguration.setdefault("operatorNotes", [])
    preconfiguration.setdefault("implementation", {})
    preconfiguration.setdefault("additionalSettings", {})
    return preconfiguration


@lru_cache(maxsize=1)
def load_mcp_server_preconfigurations():
    """Load, validate, and return enabled MCP server preconfigurations."""
    preconfiguration_by_id = {}

    for file_path, source in _iter_preconfiguration_definition_paths():
        try:
            definition = _load_json_file(file_path)
            _validate_mcp_preconfiguration(definition, file_path)
        except (
            OSError,
            json.JSONDecodeError,
            ValidationError,
            McpImplementationValidationError,
            McpPreconfigurationValidationError,
        ) as exc:
            log_event(
                f"[MCP_PRECONFIGURATIONS] Failed to load MCP preconfiguration definition: {exc}",
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
    additional_fields["implementation"] = copy.deepcopy(preconfiguration.get("implementation") or {})
    additional_fields["additionalSettings"] = copy.deepcopy(preconfiguration.get("additionalSettings") or {})
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


def _requires_explicit_preconfiguration_policy(preconfiguration):
    return (
        preconfiguration.get("catalogTier") == MCP_PRECONFIGURATION_CATALOG_TIER_ENTERPRISE
        or _coerce_bool(preconfiguration.get("disabledByDefault"))
        or _coerce_bool(preconfiguration.get("requiresAdminEnablement"))
    )


def _is_explicit_preconfiguration_policy_match(preconfiguration, decision):
    preconfiguration_id = normalize_mcp_preconfiguration_id(preconfiguration.get("id"))
    matched_pattern = str(decision.get("matched_pattern") or "").strip().lower()
    return bool(preconfiguration_id and matched_pattern == f"{MCP_PRECONFIGURATION_POLICY_PREFIX}{preconfiguration_id}")


def _is_specific_destination_policy_match(decision):
    matched_pattern = str(decision.get("matched_pattern") or "").strip().lower()
    if not matched_pattern or matched_pattern == "*":
        return False
    return not matched_pattern.startswith(MCP_DESTINATION_POLICY_PREFIXES_WITHOUT_ENDPOINT_REVIEW)


def _build_manifest_without_preconfiguration_match(manifest):
    destination_manifest = copy.deepcopy(manifest)
    additional_fields = destination_manifest.get("additionalFields")
    if not isinstance(additional_fields, dict):
        additional_fields = {}
    additional_fields = dict(additional_fields)
    additional_fields["preconfiguration_id"] = ""
    destination_manifest["additionalFields"] = additional_fields
    return destination_manifest


def _evaluate_specific_destination_policy(manifest, scope_type, scope_id="", user_id="", policy_config=None):
    return evaluate_mcp_destination_policy(
        _build_manifest_without_preconfiguration_match(manifest),
        scope_type=scope_type,
        scope_id=scope_id,
        policy_config=policy_config,
        user_id=user_id,
    )


def _enterprise_destination_policy_is_allowed(preconfiguration, manifest, normalized_scope, scope_id, user_id, policy_config):
    if not _coerce_bool(preconfiguration.get("requiresEndpointReview")):
        return True
    destination_decision = _evaluate_specific_destination_policy(
        manifest,
        normalized_scope,
        scope_id=scope_id,
        user_id=user_id,
        policy_config=policy_config,
    )
    return destination_decision.get("allowed", False) and _is_specific_destination_policy_match(destination_decision)


def _is_preconfiguration_available_for_scope(
    preconfiguration,
    normalized_scope,
    scope_id="",
    user_id="",
    policy_config=None,
):
    if not _is_scope_eligible(preconfiguration, normalized_scope):
        return False

    manifest = _build_preconfiguration_manifest(preconfiguration)
    decision = evaluate_mcp_destination_policy(
        manifest,
        scope_type=normalized_scope,
        scope_id=scope_id,
        policy_config=policy_config,
        user_id=user_id,
    )
    if not decision.get("allowed", False):
        return False

    if _requires_explicit_preconfiguration_policy(preconfiguration):
        return (
            _is_explicit_preconfiguration_policy_match(preconfiguration, decision)
            and _enterprise_destination_policy_is_allowed(
                preconfiguration,
                manifest,
                normalized_scope,
                scope_id,
                user_id,
                policy_config,
            )
        )

    return True


def build_mcp_server_preconfigurations_response(
    action_scope=MCP_DESTINATION_SCOPE_PERSONAL,
    scope_id="",
    user_id="",
    settings=None,
):
    """Return the API response payload for MCP server preconfigurations."""
    normalized_scope = normalize_mcp_destination_scope(action_scope)
    policy_config = get_mcp_destination_policy_config(settings, user_id=user_id)
    preconfigurations = [
        copy.deepcopy(preconfiguration)
        for preconfiguration in load_mcp_server_preconfigurations()
        if _is_preconfiguration_available_for_scope(
            preconfiguration,
            normalized_scope,
            scope_id=scope_id,
            user_id=user_id,
            policy_config=policy_config,
        )
    ]
    return {
        "defaultPreconfiguration": MCP_DEFAULT_SERVER_PRECONFIGURATION_ID,
        "scope": normalized_scope,
        "preconfigurations": preconfigurations,
    }


def evaluate_mcp_preconfiguration_manifest_policy(
    manifest,
    scope_type=MCP_DESTINATION_SCOPE_PERSONAL,
    scope_id="",
    user_id="",
    settings=None,
):
    """Evaluate catalog-specific MCP preconfiguration policy for a submitted manifest."""
    if not isinstance(manifest, dict) or manifest.get("type") != MCP_PLUGIN_TYPE:
        return {
            "allowed": True,
            "reason": "not_mcp_preconfiguration",
            "matched_pattern": "",
        }

    additional_fields = manifest.get("additionalFields") if isinstance(manifest.get("additionalFields"), dict) else {}
    preconfiguration_id = normalize_mcp_preconfiguration_id(additional_fields.get("preconfiguration_id"))
    if not preconfiguration_id:
        return {
            "allowed": True,
            "reason": "no_preconfiguration_selected",
            "matched_pattern": "",
        }

    preconfiguration = get_mcp_server_preconfiguration(preconfiguration_id)
    if not preconfiguration:
        return {
            "allowed": False,
            "reason": "MCP preconfiguration is not available.",
            "matched_pattern": "",
            "preconfiguration_id": preconfiguration_id,
        }

    if not _requires_explicit_preconfiguration_policy(preconfiguration):
        return {
            "allowed": True,
            "reason": "preconfiguration_has_no_explicit_policy_requirement",
            "matched_pattern": "",
            "preconfiguration_id": preconfiguration_id,
        }

    policy_config = get_mcp_destination_policy_config(settings, user_id=user_id)
    decision = evaluate_mcp_destination_policy(
        manifest,
        scope_type=scope_type,
        scope_id=scope_id,
        policy_config=policy_config,
        user_id=user_id,
    )
    if decision.get("allowed") and _is_explicit_preconfiguration_policy_match(preconfiguration, decision):
        if not _enterprise_destination_policy_is_allowed(
            preconfiguration,
            manifest,
            scope_type,
            scope_id,
            user_id,
            policy_config,
        ):
            return {
                "allowed": False,
                "reason": "MCP enterprise preconfiguration requires a specific destination policy.",
                "matched_pattern": decision.get("matched_pattern", ""),
                "preconfiguration_id": preconfiguration_id,
            }
        return {
            "allowed": True,
            "reason": "matched_explicit_preconfiguration_policy",
            "matched_pattern": decision.get("matched_pattern", ""),
            "preconfiguration_id": preconfiguration_id,
        }

    return {
        "allowed": False,
        "reason": "MCP enterprise preconfiguration requires an explicit preconfiguration policy.",
        "matched_pattern": decision.get("matched_pattern", ""),
        "preconfiguration_id": preconfiguration_id,
    }


def assert_mcp_preconfiguration_manifest_allowed(
    manifest,
    scope_type=MCP_DESTINATION_SCOPE_PERSONAL,
    scope_id="",
    user_id="",
    settings=None,
    operation="mcp",
):
    """Raise when a submitted MCP manifest uses a gated preconfiguration without explicit policy."""
    decision = evaluate_mcp_preconfiguration_manifest_policy(
        manifest,
        scope_type=scope_type,
        scope_id=scope_id,
        user_id=user_id,
        settings=settings,
    )
    if decision.get("allowed"):
        return decision
    raise McpDestinationPolicyError(
        f"{decision.get('reason')} Operation '{operation}' is not allowed for this MCP preconfiguration."
    )


def clear_mcp_server_preconfiguration_cache():
    """Clear preconfiguration caches for tests or future admin refresh actions."""
    load_mcp_server_preconfigurations.cache_clear()
    _load_mcp_preconfiguration_schema.cache_clear()
    clear_mcp_implementation_schema_cache()
