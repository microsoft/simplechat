# functions_mcp_destinations.py
"""Outbound MCP destination governance helpers."""

import fnmatch
import ipaddress
import json
import logging
import os
import re
from urllib.parse import urlparse, urlunparse

try:
    from flask import current_app, has_request_context, session
except ImportError:  # pragma: no cover - supports source-level functional tests without Flask installed.
    current_app = None
    has_request_context = None
    session = None

from functions_appinsights import log_event
from functions_mcp_operations import (
    MCP_PLUGIN_TYPE,
    MCP_REMOTE_TRANSPORTS,
    normalize_mcp_additional_fields,
    validate_mcp_endpoint_for_transport,
)


ENABLE_MCP_DESTINATION_GOVERNANCE_ENV = "ENABLE_MCP_DESTINATION_GOVERNANCE"
MCP_ALLOWED_DESTINATIONS_ENV = "MCP_ALLOWED_DESTINATIONS"
MCP_ALLOWED_PERSONAL_DESTINATIONS_ENV = "MCP_ALLOWED_PERSONAL_DESTINATIONS"
MCP_ALLOWED_GROUP_DESTINATIONS_ENV = "MCP_ALLOWED_GROUP_DESTINATIONS"
MCP_ALLOWED_GLOBAL_DESTINATIONS_ENV = "MCP_ALLOWED_GLOBAL_DESTINATIONS"
MCP_BLOCK_UNSAFE_DESTINATIONS_ENV = "MCP_BLOCK_UNSAFE_DESTINATIONS"

MCP_DESTINATION_SCOPE_PERSONAL = "personal"
MCP_DESTINATION_SCOPE_GROUP = "group"
MCP_DESTINATION_SCOPE_GLOBAL = "global"
MCP_DESTINATION_SCOPE_ALL = "all"

MCP_DESTINATION_SCOPE_ALIASES = {
    "": MCP_DESTINATION_SCOPE_PERSONAL,
    "user": MCP_DESTINATION_SCOPE_PERSONAL,
    "personal": MCP_DESTINATION_SCOPE_PERSONAL,
    "workspace": MCP_DESTINATION_SCOPE_PERSONAL,
    "group": MCP_DESTINATION_SCOPE_GROUP,
    "group_action": MCP_DESTINATION_SCOPE_GROUP,
    "admin": MCP_DESTINATION_SCOPE_GLOBAL,
    "global": MCP_DESTINATION_SCOPE_GLOBAL,
    "global_action": MCP_DESTINATION_SCOPE_GLOBAL,
}
MCP_DESTINATION_ITEM_POLICY_ENTITY_TYPES = {
    MCP_DESTINATION_SCOPE_PERSONAL: "mcp_personal_destination",
    MCP_DESTINATION_SCOPE_GROUP: "mcp_group_destination",
    MCP_DESTINATION_SCOPE_GLOBAL: "mcp_global_destination",
}
MCP_GROUP_DESTINATION_TARGET_PREFIX = "group:"
MCP_GROUP_DESTINATION_TARGET_SEPARATOR = "::"

MCP_DESTINATION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MCP_UNSAFE_METADATA_IPS = {
    ipaddress.ip_address("168.63.129.16"),
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.169.250"),
    ipaddress.ip_address("169.254.169.251"),
}


class McpDestinationPolicyError(PermissionError):
    """Raised when an outbound MCP destination is denied by policy."""


def normalize_mcp_destination_scope(scope_type):
    """Normalize an outbound MCP destination policy scope."""
    normalized_scope = str(scope_type or "").strip().lower()
    return MCP_DESTINATION_SCOPE_ALIASES.get(normalized_scope, MCP_DESTINATION_SCOPE_PERSONAL)


def normalize_mcp_policy_id(value):
    """Normalize a policy-bound preset or preconfiguration id."""
    normalized_value = str(value or "").strip().lower()
    normalized_value = re.sub(r"\s+", "_", normalized_value)
    if MCP_DESTINATION_ID_PATTERN.fullmatch(normalized_value):
        return normalized_value
    return ""


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_pattern_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                raw_values = parsed if isinstance(parsed, list) else []
            except (TypeError, ValueError):
                raw_values = []
        else:
            raw_values = re.split(r"[\s,]+", text)
    else:
        raw_values = [value]

    patterns = []
    seen_patterns = set()
    for raw_pattern in raw_values:
        pattern = str(raw_pattern or "").strip()
        if not pattern or pattern in seen_patterns:
            continue
        patterns.append(pattern)
        seen_patterns.add(pattern)
    return patterns


def _get_nested_setting(settings, key, default=None):
    if not isinstance(settings, dict):
        return default
    if key in settings:
        return settings.get(key)
    governance = settings.get("mcp_destination_governance")
    if isinstance(governance, dict) and key in governance:
        return governance.get(key)
    return default


def _get_current_app_config_value(key, default=None):
    if current_app is None:
        return default
    try:
        return current_app.config.get(key, default)
    except RuntimeError:
        return default


def _get_request_user_id():
    if has_request_context is None or session is None:
        return ""
    try:
        if not has_request_context():
            return ""
        user = session.get("user")
        if isinstance(user, dict):
            return str(user.get("oid") or "").strip()
    except RuntimeError:
        return ""
    return ""


def _list_governance_item_policies(entity_type):
    try:
        from functions_governance import list_item_policies
    except Exception as exc:
        log_event(
            "[MCPDestinationPolicy] Unable to import governance item policies",
            extra={"entity_type": entity_type, "error": str(exc)},
            level=logging.WARNING,
            debug_only=True,
        )
        return []

    try:
        return list_item_policies(entity_type=entity_type)
    except Exception as exc:
        log_event(
            "[MCPDestinationPolicy] Unable to load governance item policies",
            extra={"entity_type": entity_type, "error": str(exc)},
            level=logging.WARNING,
            debug_only=True,
        )
        return []


def _get_governance_group_ids_for_user(user_id):
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return set()

    try:
        from functions_governance import get_user_governance_group_ids
    except Exception as exc:
        log_event(
            "[MCPDestinationPolicy] Unable to import governance group lookup",
            extra={"error": str(exc)},
            level=logging.WARNING,
            debug_only=True,
        )
        return set()

    try:
        return set(get_user_governance_group_ids(normalized_user_id))
    except Exception as exc:
        log_event(
            "[MCPDestinationPolicy] Unable to load governance group ids",
            extra={"user_id_present": bool(normalized_user_id), "error": str(exc)},
            level=logging.WARNING,
            debug_only=True,
        )
        return set()


def _governance_item_policy_applies_to_user(policy, user_id, user_group_ids):
    if not isinstance(policy, dict):
        return False
    if policy.get("allow_all", True):
        return True

    normalized_user_id = str(user_id or "").strip()
    allowed_users = {
        str(allowed_user_id or "").strip()
        for allowed_user_id in policy.get("allowed_users", [])
        if str(allowed_user_id or "").strip()
    }
    if normalized_user_id and normalized_user_id in allowed_users:
        return True

    allowed_groups = {
        str(allowed_group_id or "").strip()
        for allowed_group_id in policy.get("allowed_groups", [])
        if str(allowed_group_id or "").strip()
    }
    return bool(allowed_groups.intersection(user_group_ids or set()))


def _normalize_governance_destination_item_id(scope_type, item_id):
    normalized_item_id = str(item_id or "").strip()
    normalized_scope = normalize_mcp_destination_scope(scope_type)
    if normalized_scope != MCP_DESTINATION_SCOPE_GROUP:
        return "", normalized_item_id

    if normalized_item_id.lower().startswith(MCP_GROUP_DESTINATION_TARGET_PREFIX) and MCP_GROUP_DESTINATION_TARGET_SEPARATOR in normalized_item_id:
        group_target, pattern = normalized_item_id.split(MCP_GROUP_DESTINATION_TARGET_SEPARATOR, 1)
        group_id = group_target[len(MCP_GROUP_DESTINATION_TARGET_PREFIX):].strip()
        return group_id, pattern.strip()

    return "", normalized_item_id


def _merge_unique_patterns(base_patterns, additional_patterns):
    merged = list(base_patterns or [])
    seen_patterns = {str(pattern) for pattern in merged}
    for pattern in additional_patterns or []:
        normalized_pattern = str(pattern or "").strip()
        if not normalized_pattern or normalized_pattern in seen_patterns:
            continue
        merged.append(normalized_pattern)
        seen_patterns.add(normalized_pattern)
    return merged


def _append_governance_destination_patterns(policy_config, user_id=""):
    normalized_user_id = str(user_id or "").strip() or _get_request_user_id()
    user_group_ids = None

    for scope_type, entity_type in MCP_DESTINATION_ITEM_POLICY_ENTITY_TYPES.items():
        patterns = []
        scoped_group_patterns = {}
        for policy in _list_governance_item_policies(entity_type):
            if not _governance_item_policy_applies_to_user(
                policy,
                normalized_user_id,
                user_group_ids if user_group_ids is not None else set(),
            ):
                if user_group_ids is None:
                    user_group_ids = _get_governance_group_ids_for_user(normalized_user_id)
                    if _governance_item_policy_applies_to_user(policy, normalized_user_id, user_group_ids):
                        group_id, pattern = _normalize_governance_destination_item_id(scope_type, policy.get("item_id"))
                        if group_id:
                            scoped_group_patterns.setdefault(group_id, []).append(pattern)
                        else:
                            patterns.append(pattern)
                continue

            group_id, pattern = _normalize_governance_destination_item_id(scope_type, policy.get("item_id"))
            if group_id:
                scoped_group_patterns.setdefault(group_id, []).append(pattern)
            else:
                patterns.append(pattern)

        policy_config["scope_patterns"][scope_type] = _merge_unique_patterns(
            policy_config["scope_patterns"].get(scope_type, []),
            patterns,
        )
        for group_id, group_patterns in scoped_group_patterns.items():
            policy_config["group_patterns"][group_id] = _merge_unique_patterns(
                policy_config["group_patterns"].get(group_id, []),
                group_patterns,
            )

    return policy_config


def get_mcp_destination_policy_config(settings=None, user_id=""):
    """Return outbound MCP destination policy config from settings and environment."""
    scoped_group_patterns = _get_nested_setting(settings, "mcp_allowed_group_destination_overrides", {})
    if not isinstance(scoped_group_patterns, dict):
        scoped_group_patterns = {}

    policy_config = {
        "enabled": _coerce_bool(
            _get_nested_setting(
                settings,
                "enable_mcp_destination_governance",
                _get_current_app_config_value(
                    "ENABLE_MCP_DESTINATION_GOVERNANCE",
                    os.getenv(ENABLE_MCP_DESTINATION_GOVERNANCE_ENV, "false"),
                ),
            ),
            default=False,
        ),
        "block_unsafe_destinations": _coerce_bool(
            _get_nested_setting(
                settings,
                "mcp_block_unsafe_destinations",
                _get_current_app_config_value(
                    "MCP_BLOCK_UNSAFE_DESTINATIONS",
                    os.getenv(MCP_BLOCK_UNSAFE_DESTINATIONS_ENV, "false"),
                ),
            ),
            default=False,
        ),
        "common_patterns": _coerce_pattern_list(
            _get_nested_setting(
                settings,
                "mcp_allowed_destinations",
                _get_current_app_config_value("MCP_ALLOWED_DESTINATIONS", os.getenv(MCP_ALLOWED_DESTINATIONS_ENV, "")),
            )
        ),
        "scope_patterns": {
            MCP_DESTINATION_SCOPE_PERSONAL: _coerce_pattern_list(
                _get_nested_setting(
                    settings,
                    "mcp_allowed_personal_destinations",
                    _get_current_app_config_value(
                        "MCP_ALLOWED_PERSONAL_DESTINATIONS",
                        os.getenv(MCP_ALLOWED_PERSONAL_DESTINATIONS_ENV, ""),
                    ),
                )
            ),
            MCP_DESTINATION_SCOPE_GROUP: _coerce_pattern_list(
                _get_nested_setting(
                    settings,
                    "mcp_allowed_group_destinations",
                    _get_current_app_config_value(
                        "MCP_ALLOWED_GROUP_DESTINATIONS",
                        os.getenv(MCP_ALLOWED_GROUP_DESTINATIONS_ENV, ""),
                    ),
                )
            ),
            MCP_DESTINATION_SCOPE_GLOBAL: _coerce_pattern_list(
                _get_nested_setting(
                    settings,
                    "mcp_allowed_global_destinations",
                    _get_current_app_config_value(
                        "MCP_ALLOWED_GLOBAL_DESTINATIONS",
                        os.getenv(MCP_ALLOWED_GLOBAL_DESTINATIONS_ENV, ""),
                    ),
                )
            ),
        },
        "group_patterns": {
            str(group_id): _coerce_pattern_list(patterns)
            for group_id, patterns in scoped_group_patterns.items()
        },
    }
    if not policy_config.get("enabled"):
        return policy_config
    return _append_governance_destination_patterns(policy_config, user_id=user_id)


def _default_port_for_scheme(scheme):
    if scheme in {"http", "ws"}:
        return 80
    if scheme in {"https", "wss"}:
        return 443
    return None


def _normalize_netloc(hostname, port, scheme):
    normalized_host = str(hostname or "").strip().lower()
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    default_port = _default_port_for_scheme(scheme)
    if port and port != default_port:
        return f"{normalized_host}:{port}"
    return normalized_host


def normalize_mcp_destination_endpoint(endpoint, transport):
    """Normalize an MCP remote endpoint for deterministic policy evaluation."""
    endpoint_errors = validate_mcp_endpoint_for_transport(endpoint, transport)
    if endpoint_errors:
        raise ValueError("; ".join(endpoint_errors))

    parsed_endpoint = urlparse(str(endpoint or "").strip())
    if parsed_endpoint.fragment:
        raise ValueError("MCP endpoint must not include a URL fragment")

    scheme = parsed_endpoint.scheme.lower()
    hostname = (parsed_endpoint.hostname or "").lower()
    netloc = _normalize_netloc(hostname, parsed_endpoint.port, scheme)
    path = parsed_endpoint.path or "/"
    return urlunparse((scheme, netloc, path, "", parsed_endpoint.query, ""))


def _unsafe_host_reason(hostname):
    normalized_host = str(hostname or "").strip().strip("[]").lower()
    if normalized_host in {"localhost", "localhost.localdomain"} or normalized_host.endswith(".localhost"):
        return "local hostnames are not allowed"

    try:
        ip_address = ipaddress.ip_address(normalized_host)
    except ValueError:
        return ""

    if ip_address in MCP_UNSAFE_METADATA_IPS:
        return "metadata-service addresses are not allowed"
    if ip_address.is_loopback:
        return "loopback addresses are not allowed"
    if ip_address.is_link_local:
        return "link-local addresses are not allowed"
    if ip_address.is_private:
        return "private network addresses are not allowed"
    if ip_address.is_multicast or ip_address.is_reserved or ip_address.is_unspecified:
        return "non-public IP addresses are not allowed"
    return ""


def describe_mcp_destination(manifest):
    """Return normalized MCP destination metadata for a manifest."""
    if not isinstance(manifest, dict) or manifest.get("type") != MCP_PLUGIN_TYPE:
        return {
            "is_mcp": False,
            "is_remote": False,
            "transport": "",
            "endpoint": "",
            "normalized_endpoint": "",
        }

    additional_fields = normalize_mcp_additional_fields(manifest.get("additionalFields", {}))
    transport = additional_fields.get("transport")
    endpoint = str(manifest.get("endpoint") or "").strip()
    descriptor = {
        "is_mcp": True,
        "is_remote": transport in MCP_REMOTE_TRANSPORTS,
        "transport": transport,
        "endpoint": endpoint,
        "normalized_endpoint": "",
        "scheme": "",
        "host": "",
        "port": None,
        "path": "",
        "server_profile": normalize_mcp_policy_id(additional_fields.get("server_profile")),
        "preconfiguration_id": normalize_mcp_policy_id(additional_fields.get("preconfiguration_id")),
        "auth_method": str(additional_fields.get("auth_method") or "").strip().lower(),
    }

    if not descriptor["is_remote"]:
        return descriptor

    normalized_endpoint = normalize_mcp_destination_endpoint(endpoint, transport)
    parsed_endpoint = urlparse(normalized_endpoint)
    descriptor.update({
        "normalized_endpoint": normalized_endpoint,
        "scheme": parsed_endpoint.scheme,
        "host": parsed_endpoint.hostname or "",
        "port": parsed_endpoint.port or _default_port_for_scheme(parsed_endpoint.scheme),
        "path": parsed_endpoint.path or "/",
    })
    return descriptor


def _pattern_matches_destination(pattern, descriptor):
    normalized_pattern = str(pattern or "").strip()
    if not normalized_pattern:
        return False
    if normalized_pattern == "*":
        return True

    lowered_pattern = normalized_pattern.lower()
    if lowered_pattern.startswith("preconfiguration:"):
        pattern_id = normalize_mcp_policy_id(lowered_pattern.split(":", 1)[1])
        return bool(pattern_id and pattern_id == descriptor.get("preconfiguration_id"))
    if lowered_pattern.startswith("preset:"):
        pattern_id = normalize_mcp_policy_id(lowered_pattern.split(":", 1)[1])
        return bool(pattern_id and pattern_id == descriptor.get("server_profile"))
    if lowered_pattern.startswith("transport:"):
        transport = lowered_pattern.split(":", 1)[1].strip()
        return transport == descriptor.get("transport")

    if "://" not in normalized_pattern:
        return fnmatch.fnmatchcase(str(descriptor.get("host") or "").lower(), lowered_pattern)

    parsed_pattern = urlparse(normalized_pattern)
    if parsed_pattern.scheme and parsed_pattern.scheme.lower() != descriptor.get("scheme"):
        return False
    pattern_host = (parsed_pattern.hostname or "").lower()
    if not pattern_host or not fnmatch.fnmatchcase(str(descriptor.get("host") or "").lower(), pattern_host):
        return False
    if parsed_pattern.port and parsed_pattern.port != descriptor.get("port"):
        return False

    pattern_path = parsed_pattern.path or "/"
    destination_path = descriptor.get("path") or "/"
    if pattern_path == "/":
        return True
    if pattern_path.endswith("/*"):
        return destination_path.startswith(pattern_path[:-1])
    if pattern_path.endswith("*"):
        return destination_path.startswith(pattern_path[:-1])
    return destination_path.rstrip("/") == pattern_path.rstrip("/")


def _allowed_patterns_for_scope(policy_config, scope_type, scope_id):
    normalized_scope = normalize_mcp_destination_scope(scope_type)
    patterns = []
    patterns.extend(policy_config.get("common_patterns") or [])
    patterns.extend((policy_config.get("scope_patterns") or {}).get(normalized_scope) or [])
    if normalized_scope == MCP_DESTINATION_SCOPE_GROUP and scope_id:
        patterns.extend((policy_config.get("group_patterns") or {}).get(str(scope_id)) or [])
    return patterns


def infer_mcp_destination_scope(manifest, fallback_scope=MCP_DESTINATION_SCOPE_PERSONAL):
    """Infer an action scope from a stored MCP manifest when a caller does not pass one."""
    if not isinstance(manifest, dict):
        return normalize_mcp_destination_scope(fallback_scope), ""
    manifest_scope = str(manifest.get("scope") or "").strip().lower()
    if manifest_scope:
        scope_type = normalize_mcp_destination_scope(manifest_scope)
    elif manifest.get("is_group"):
        scope_type = MCP_DESTINATION_SCOPE_GROUP
    elif manifest.get("is_global"):
        scope_type = MCP_DESTINATION_SCOPE_GLOBAL
    else:
        scope_type = normalize_mcp_destination_scope(fallback_scope)

    if scope_type == MCP_DESTINATION_SCOPE_GROUP:
        return scope_type, manifest.get("group_id") or manifest.get("scope_id") or ""
    if scope_type == MCP_DESTINATION_SCOPE_GLOBAL:
        return scope_type, MCP_DESTINATION_SCOPE_GLOBAL
    return scope_type, manifest.get("user_id") or manifest.get("scope_id") or ""


def evaluate_mcp_destination_policy(manifest, scope_type=None, scope_id="", policy_config=None, user_id=""):
    """Evaluate whether an MCP manifest may connect to its configured destination."""
    descriptor = describe_mcp_destination(manifest)
    if not descriptor["is_mcp"] or not descriptor["is_remote"]:
        return {
            "allowed": True,
            "reason": "not_remote_mcp_destination",
            "descriptor": descriptor,
            "matched_pattern": "",
        }

    policy = policy_config or get_mcp_destination_policy_config(user_id=user_id)
    inferred_scope_type, inferred_scope_id = infer_mcp_destination_scope(manifest)
    normalized_scope = normalize_mcp_destination_scope(scope_type or inferred_scope_type)
    normalized_scope_id = scope_id if scope_id not in (None, "") else inferred_scope_id

    unsafe_reason = _unsafe_host_reason(descriptor.get("host"))
    if policy.get("block_unsafe_destinations") and unsafe_reason:
        return {
            "allowed": False,
            "reason": unsafe_reason,
            "descriptor": descriptor,
            "matched_pattern": "",
            "scope_type": normalized_scope,
            "scope_id": normalized_scope_id,
        }

    if not policy.get("enabled"):
        return {
            "allowed": True,
            "reason": "destination_governance_disabled",
            "descriptor": descriptor,
            "matched_pattern": "",
            "scope_type": normalized_scope,
            "scope_id": normalized_scope_id,
        }

    allowed_patterns = _allowed_patterns_for_scope(policy, normalized_scope, normalized_scope_id)
    for pattern in allowed_patterns:
        if _pattern_matches_destination(pattern, descriptor):
            return {
                "allowed": True,
                "reason": "matched_destination_policy",
                "descriptor": descriptor,
                "matched_pattern": pattern,
                "scope_type": normalized_scope,
                "scope_id": normalized_scope_id,
            }

    return {
        "allowed": False,
        "reason": "MCP destination is not allowed for this action scope",
        "descriptor": descriptor,
        "matched_pattern": "",
        "scope_type": normalized_scope,
        "scope_id": normalized_scope_id,
    }


def assert_mcp_destination_allowed(
    manifest,
    scope_type=None,
    scope_id="",
    policy_config=None,
    operation="mcp",
    user_id="",
):
    """Raise when an outbound MCP destination is denied by policy."""
    decision = evaluate_mcp_destination_policy(
        manifest,
        scope_type=scope_type,
        scope_id=scope_id,
        policy_config=policy_config,
        user_id=user_id,
    )
    descriptor = decision.get("descriptor") or {}
    if decision.get("allowed"):
        log_event(
            "[MCPDestinationPolicy] MCP destination allowed",
            extra={
                "operation": operation,
                "scope_type": decision.get("scope_type"),
                "matched_pattern": decision.get("matched_pattern"),
                "transport": descriptor.get("transport"),
                "host": descriptor.get("host"),
                "reason": decision.get("reason"),
            },
            level=logging.INFO,
            debug_only=True,
        )
        return decision

    log_event(
        "[MCPDestinationPolicy] MCP destination denied",
        extra={
            "operation": operation,
            "scope_type": decision.get("scope_type"),
            "transport": descriptor.get("transport"),
            "host": descriptor.get("host"),
            "reason": decision.get("reason"),
        },
        level=logging.WARNING,
    )
    raise McpDestinationPolicyError(str(decision.get("reason") or "MCP destination is not allowed."))
