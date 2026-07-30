# functions_mcp_server_config.py

import json
import logging
import os
import re
from urllib.parse import urlparse

import requests

from config import (
    INBOUND_MCP_AUTHORIZATION_SERVER_METADATA_PATH,
    INBOUND_MCP_PRM_PATH,
    INBOUND_MCP_PRM_PATHS,
    INBOUND_MCP_RESOURCE_PATH,
    TENANT_ID,
)


INBOUND_MCP_SETTINGS_DEFAULTS = {
    "enable_inbound_mcp_server": False,
    "inbound_mcp_required_user_role": "InboundMCPUserAccess",
    "inbound_mcp_required_app_role": "InboundMCPAppAccess",
    "inbound_mcp_required_user_roles": ["InboundMCPUserAccess"],
    "inbound_mcp_required_app_roles": ["InboundMCPAppAccess"],
    "inbound_mcp_required_scope": "DelegatedMcpServerAccess",
    "inbound_mcp_allowed_client_app_entries": [],
    "inbound_mcp_allowed_client_app_ids": [],
    "inbound_mcp_allow_external_tenants": False,
    "inbound_mcp_allowed_tenant_entries": [],
    "inbound_mcp_allowed_tenant_ids": [],
    "inbound_mcp_allow_all_source_ids": True,
    "inbound_mcp_allowed_source_entries": [
        {
            "value": "*",
            "description": "Allow all inbound MCP source IDs",
        },
    ],
    "inbound_mcp_allowed_source_ids": ["*"],
    "inbound_mcp_source_header": "X-SimpleChat-MCP-Source",
    "enable_inbound_mcp_rate_limits": True,
    "inbound_mcp_rate_limit_window_seconds": 60,
    "inbound_mcp_rate_limit_read_per_window": 120,
    "inbound_mcp_rate_limit_search_per_window": 30,
    "inbound_mcp_rate_limit_write_per_window": 10,
    "inbound_mcp_max_request_bytes": 65536,
}
INBOUND_MCP_MUTABLE_SETTING_KEYS = tuple(INBOUND_MCP_SETTINGS_DEFAULTS.keys())
INBOUND_MCP_LEGACY_REQUIRED_ROLE_KEY = "inbound_mcp_required_role"
INBOUND_MCP_LEGACY_REQUIRED_ROLE_VALUE = "McpServerAccess"
INBOUND_MCP_EASY_AUTH_EXCLUDED_PATHS = (
    *INBOUND_MCP_PRM_PATHS,
    INBOUND_MCP_AUTHORIZATION_SERVER_METADATA_PATH,
    INBOUND_MCP_RESOURCE_PATH,
    f"{INBOUND_MCP_RESOURCE_PATH}/health",
)


def _normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off", ""}:
            return False
    return bool(value)


def _normalize_int(value, default_value, minimum_value, maximum_value):
    try:
        integer_value = int(value)
    except (TypeError, ValueError):
        integer_value = default_value
    return min(max(integer_value, minimum_value), maximum_value)


def _iter_list_values(value, depth=0):
    if value is None or depth > 5:
        return

    if isinstance(value, str):
        stripped_value = value.strip()
        if not stripped_value:
            return

        if stripped_value.startswith("[") or stripped_value.startswith('"'):
            try:
                parsed_value = json.loads(stripped_value)
            except (TypeError, ValueError):
                parsed_value = None

            if isinstance(parsed_value, (list, tuple, set)):
                for candidate in parsed_value:
                    yield from _iter_list_values(candidate, depth + 1)
                return

            if isinstance(parsed_value, str) and parsed_value != stripped_value:
                yield from _iter_list_values(parsed_value, depth + 1)
                return

        for candidate in re.split(r"[\r\n,;]+", stripped_value):
            yield candidate
        return

    if isinstance(value, (list, tuple, set)):
        for candidate in value:
            yield from _iter_list_values(candidate, depth + 1)
        return

    if isinstance(value, dict):
        for key in ("value", "id", "guid", "client_id", "tenant_id", "source_id"):
            candidate = str(value.get(key) or "").strip()
            if candidate:
                yield candidate
                return
        return

    yield value


def normalize_inbound_mcp_list(value, lowercase=False, default=None):
    normalized_values = []
    seen_values = set()
    for candidate in _iter_list_values(value):
        normalized_value = str(candidate or "").strip()
        if not normalized_value:
            continue
        if lowercase:
            normalized_value = normalized_value.lower()
        if normalized_value in seen_values:
            continue
        seen_values.add(normalized_value)
        normalized_values.append(normalized_value)

    if not normalized_values and default is not None:
        return list(default)
    return normalized_values


def normalize_inbound_mcp_single_value(value, default_value="", lowercase=False, max_length=256):
    """Normalize a single inbound MCP setting value."""
    normalized_values = normalize_inbound_mcp_list(value, lowercase=lowercase)
    normalized_value = normalized_values[0] if normalized_values else str(default_value or "").strip()
    if lowercase:
        normalized_value = normalized_value.lower()
    return normalized_value[:max_length]


def _iter_entry_values(value, depth=0):
    if value is None or depth > 5:
        return

    if isinstance(value, str):
        stripped_value = value.strip()
        if not stripped_value:
            return

        if stripped_value.startswith("["):
            try:
                parsed_value = json.loads(stripped_value)
            except (TypeError, ValueError):
                parsed_value = None

            if isinstance(parsed_value, (list, tuple, set)):
                for candidate in parsed_value:
                    yield from _iter_entry_values(candidate, depth + 1)
                return

        for candidate in re.split(r"[\r\n,;]+", stripped_value):
            normalized_candidate = str(candidate or "").strip()
            if normalized_candidate:
                yield {
                    "value": normalized_candidate,
                    "description": "",
                }
        return

    if isinstance(value, dict):
        entry_value = ""
        for key in ("value", "id", "guid", "client_id", "tenant_id", "source_id"):
            entry_value = str(value.get(key) or "").strip()
            if entry_value:
                break
        if entry_value:
            yield {
                "value": entry_value,
                "description": _normalize_text(value.get("description") or value.get("label") or value.get("name"), "", max_length=256),
            }
        return

    if isinstance(value, (list, tuple, set)):
        for candidate in value:
            yield from _iter_entry_values(candidate, depth + 1)
        return

    normalized_value = str(value or "").strip()
    if normalized_value:
        yield {
            "value": normalized_value,
            "description": "",
        }


def normalize_inbound_mcp_value_entries(value, lowercase=False, default=None):
    """Normalize MCP allowlist entries into [{value, description}] objects."""
    normalized_entries = []
    seen_values = set()
    for entry in _iter_entry_values(value):
        normalized_value = str(entry.get("value") or "").strip()
        if not normalized_value:
            continue
        if lowercase:
            normalized_value = normalized_value.lower()
        dedupe_key = normalized_value.lower() if lowercase else normalized_value
        if dedupe_key in seen_values:
            continue
        seen_values.add(dedupe_key)
        normalized_entries.append({
            "value": normalized_value,
            "description": _normalize_text(entry.get("description"), "", max_length=256),
        })

    if not normalized_entries and default is not None:
        return normalize_inbound_mcp_value_entries(default, lowercase=lowercase)
    return normalized_entries


def inbound_mcp_entry_values(entries, lowercase=False):
    """Return normalized values from MCP object entries."""
    return normalize_inbound_mcp_list(
        [
            entry.get("value")
            for entry in normalize_inbound_mcp_value_entries(entries, lowercase=lowercase)
        ],
        lowercase=lowercase,
    )


def ensure_inbound_mcp_default_tenant_entry(entries):
    """Ensure the SimpleChat tenant appears in the editable tenant entry list."""
    normalized_entries = normalize_inbound_mcp_value_entries(entries, lowercase=True)
    tenant_id = str(TENANT_ID or "").strip().lower()
    if not tenant_id:
        return normalized_entries

    if any(entry.get("value") == tenant_id for entry in normalized_entries):
        return normalized_entries

    return [
        {
            "value": tenant_id,
            "description": "SimpleChat tenant",
        },
        *normalized_entries,
    ]


def _normalize_text(value, default_value="", max_length=256):
    normalized_value = " ".join(str(value or "").split())
    if not normalized_value:
        normalized_value = str(default_value or "")
    return normalized_value[:max_length]


def normalize_inbound_mcp_settings(settings):
    """Normalize mutable inbound MCP runtime settings in-place."""
    if not isinstance(settings, dict):
        return False

    changed = False
    legacy_required_role = settings.get(INBOUND_MCP_LEGACY_REQUIRED_ROLE_KEY)
    if "inbound_mcp_required_user_role" not in settings and legacy_required_role:
        legacy_roles = normalize_inbound_mcp_list(legacy_required_role)
        if legacy_roles == [INBOUND_MCP_LEGACY_REQUIRED_ROLE_VALUE]:
            legacy_roles = INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_required_user_roles"]
        settings["inbound_mcp_required_user_role"] = normalize_inbound_mcp_single_value(
            legacy_roles,
            INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_required_user_role"],
        )
        changed = True

    for key, default_value in INBOUND_MCP_SETTINGS_DEFAULTS.items():
        if key not in settings:
            settings[key] = list(default_value) if isinstance(default_value, list) else default_value
            changed = True

    required_user_role = normalize_inbound_mcp_single_value(
        settings.get("inbound_mcp_required_user_role") or settings.get("inbound_mcp_required_user_roles"),
        INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_required_user_role"],
        max_length=128,
    )
    required_app_role = normalize_inbound_mcp_single_value(
        settings.get("inbound_mcp_required_app_role") or settings.get("inbound_mcp_required_app_roles"),
        INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_required_app_role"],
        max_length=128,
    )
    client_app_entries = normalize_inbound_mcp_value_entries(
        settings.get("inbound_mcp_allowed_client_app_entries") or settings.get("inbound_mcp_allowed_client_app_ids"),
        lowercase=True,
    )
    allow_external_tenants = _normalize_bool(settings.get("inbound_mcp_allow_external_tenants"))
    if allow_external_tenants:
        tenant_entries = ensure_inbound_mcp_default_tenant_entry(
            settings.get("inbound_mcp_allowed_tenant_entries") or settings.get("inbound_mcp_allowed_tenant_ids")
        )
        allowed_tenant_ids = inbound_mcp_entry_values(tenant_entries, lowercase=True)
    else:
        tenant_entries = normalize_inbound_mcp_value_entries(settings.get("inbound_mcp_allowed_tenant_entries"), lowercase=True)
        allowed_tenant_ids = [str(TENANT_ID or "").strip().lower()] if str(TENANT_ID or "").strip() else []

    allow_all_source_ids = _normalize_bool(settings.get("inbound_mcp_allow_all_source_ids"))
    if allow_all_source_ids:
        source_entries = normalize_inbound_mcp_value_entries(
            settings.get("inbound_mcp_allowed_source_entries"),
            default=INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_allowed_source_entries"],
        )
        allowed_source_ids = ["*"]
    else:
        source_entries = normalize_inbound_mcp_value_entries(
            settings.get("inbound_mcp_allowed_source_entries") or settings.get("inbound_mcp_allowed_source_ids")
        )
        source_entries = [entry for entry in source_entries if entry.get("value") != "*"]
        allowed_source_ids = inbound_mcp_entry_values(source_entries)

    normalized_values = {
        "enable_inbound_mcp_server": _normalize_bool(settings.get("enable_inbound_mcp_server")),
        "inbound_mcp_required_user_role": required_user_role,
        "inbound_mcp_required_app_role": required_app_role,
        "inbound_mcp_required_user_roles": [required_user_role] if required_user_role else [],
        "inbound_mcp_required_app_roles": [required_app_role] if required_app_role else [],
        "inbound_mcp_required_scope": _normalize_text(
            settings.get("inbound_mcp_required_scope"),
            INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_required_scope"],
            max_length=128,
        ),
        "inbound_mcp_allowed_client_app_entries": client_app_entries,
        "inbound_mcp_allowed_client_app_ids": inbound_mcp_entry_values(client_app_entries, lowercase=True),
        "inbound_mcp_allow_external_tenants": allow_external_tenants,
        "inbound_mcp_allowed_tenant_entries": tenant_entries,
        "inbound_mcp_allowed_tenant_ids": allowed_tenant_ids,
        "inbound_mcp_allow_all_source_ids": allow_all_source_ids,
        "inbound_mcp_allowed_source_entries": source_entries,
        "inbound_mcp_allowed_source_ids": allowed_source_ids,
        "inbound_mcp_source_header": _normalize_text(
            settings.get("inbound_mcp_source_header"),
            INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_source_header"],
            max_length=128,
        ),
        "enable_inbound_mcp_rate_limits": _normalize_bool(
            settings.get(
                "enable_inbound_mcp_rate_limits",
                INBOUND_MCP_SETTINGS_DEFAULTS["enable_inbound_mcp_rate_limits"],
            )
        ),
        "inbound_mcp_rate_limit_window_seconds": _normalize_int(
            settings.get("inbound_mcp_rate_limit_window_seconds"),
            INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_rate_limit_window_seconds"],
            10,
            3600,
        ),
        "inbound_mcp_rate_limit_read_per_window": _normalize_int(
            settings.get("inbound_mcp_rate_limit_read_per_window"),
            INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_rate_limit_read_per_window"],
            1,
            10000,
        ),
        "inbound_mcp_rate_limit_search_per_window": _normalize_int(
            settings.get("inbound_mcp_rate_limit_search_per_window"),
            INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_rate_limit_search_per_window"],
            1,
            10000,
        ),
        "inbound_mcp_rate_limit_write_per_window": _normalize_int(
            settings.get("inbound_mcp_rate_limit_write_per_window"),
            INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_rate_limit_write_per_window"],
            1,
            10000,
        ),
        "inbound_mcp_max_request_bytes": _normalize_int(
            settings.get("inbound_mcp_max_request_bytes"),
            INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_max_request_bytes"],
            1024,
            1048576,
        ),
    }

    for key, normalized_value in normalized_values.items():
        if settings.get(key) != normalized_value:
            settings[key] = normalized_value
            changed = True

    return changed


def get_inbound_mcp_runtime_config(settings=None):
    """Return normalized runtime config backed by the Cosmos app_settings document."""
    if settings is None:
        # Imported locally to avoid a settings/config cache import cycle during app startup.
        import app_settings_cache

        settings_getter = getattr(app_settings_cache, "get_settings_cache", None)
        settings = settings_getter() if callable(settings_getter) else {}

    config = dict(settings or {})
    normalize_inbound_mcp_settings(config)
    config["inbound_mcp_resource_path"] = INBOUND_MCP_RESOURCE_PATH
    config["inbound_mcp_prm_path"] = INBOUND_MCP_PRM_PATH
    config["inbound_mcp_prm_paths"] = list(INBOUND_MCP_PRM_PATHS)
    config["inbound_mcp_authorization_server_metadata_path"] = INBOUND_MCP_AUTHORIZATION_SERVER_METADATA_PATH
    return config


def _build_public_endpoint_url(base_url, path):
    normalized_base_url = str(base_url or "").strip().rstrip("/")
    normalized_path = str(path or "").strip()
    if not normalized_base_url or not normalized_path.startswith("/"):
        return ""
    return f"{normalized_base_url}{normalized_path}"


def _first_header_value(value):
    return str(value or "").split(",", 1)[0].strip()


def _sanitize_host(value):
    return str(value or "").split("/", 1)[0].replace("\r", "").replace("\n", "").strip()


def _is_local_metadata_host(host):
    normalized_host = str(host or "").split(":", 1)[0].strip().lower()
    return normalized_host in {"localhost", "127.0.0.1", "::1"}


def build_inbound_mcp_public_base_url(flask_request):
    """Return the externally visible request base URL for OAuth metadata."""
    if not flask_request:
        return ""

    host = _sanitize_host(flask_request.host)
    if not host:
        return ""

    scheme = _first_header_value(flask_request.headers.get("X-Forwarded-Proto"))
    if scheme not in {"http", "https"}:
        scheme = str(getattr(flask_request, "scheme", "") or "").strip().lower()
    if scheme not in {"http", "https"}:
        scheme = "https"
    if scheme == "http" and not _is_local_metadata_host(host):
        scheme = "https"

    return f"{scheme}://{host}"


def _response_has_easy_auth_redirect(response):
    if response.is_redirect:
        return True

    location = str(response.headers.get("Location") or "").strip()
    if not location:
        return False

    parsed_location = urlparse(location)
    location_path = str(parsed_location.path or "").lower()
    location_host = str(parsed_location.hostname or "").lower()
    return (
        location_path.startswith("/.auth/login")
        or location_host == "login.microsoftonline.com"
        or location_host.endswith(".login.microsoftonline.com")
    )


def _response_looks_like_sign_in_html(response):
    content_type = str(response.headers.get("Content-Type") or "").lower()
    if "text/html" not in content_type:
        return False
    body_preview = (response.text or "")[:1200].lower()
    return (
        "<!doctype html" in body_preview
        or "<html" in body_preview
        or "sign in to your account" in body_preview
        or "/.auth/login" in body_preview
    )


def _safe_response_json(response):
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _evaluate_probe_response(path, response):
    payload = _safe_response_json(response)
    content_type = str(response.headers.get("Content-Type") or "")
    result = {
        "path": path,
        "status_code": response.status_code,
        "content_type": content_type,
        "success": False,
        "message": "",
    }

    if _response_has_easy_auth_redirect(response):
        result["message"] = "App Service Authentication redirected this endpoint to sign-in."
        return result

    if _response_looks_like_sign_in_html(response):
        result["message"] = "App Service Authentication returned a sign-in HTML page for this endpoint."
        return result

    if path in INBOUND_MCP_PRM_PATHS:
        if response.status_code == 200 and payload and payload.get("mcp_endpoint") == INBOUND_MCP_RESOURCE_PATH:
            result["success"] = True
            result["message"] = "Protected resource metadata returned JSON successfully."
            return result
        result["message"] = "Protected resource metadata did not return the expected JSON contract."
        return result

    if path == INBOUND_MCP_AUTHORIZATION_SERVER_METADATA_PATH:
        if response.status_code == 200 and payload and payload.get("authorization_endpoint") and payload.get("token_endpoint"):
            result["success"] = True
            result["message"] = "OAuth authorization server metadata returned JSON successfully."
            return result
        result["message"] = "OAuth authorization server metadata did not return the expected JSON contract."
        return result

    expected_errors = {"bearer_token_required", "inbound_mcp_disabled"}
    if response.status_code in {401, 404} and payload and payload.get("error") in expected_errors:
        result["success"] = True
        result["message"] = "Endpoint reached SimpleChat and returned the expected unauthenticated JSON response."
        return result

    result["message"] = "Endpoint did not return an expected SimpleChat unauthenticated JSON response."
    return result


def check_inbound_mcp_easy_auth_exclusions(base_url, timeout_seconds=8):
    """Verify Easy Auth exclusions let unauthenticated MCP requests reach SimpleChat."""
    endpoint_results = []
    for path in INBOUND_MCP_EASY_AUTH_EXCLUDED_PATHS:
        url = _build_public_endpoint_url(base_url, path)
        if not url:
            endpoint_results.append({
                "path": path,
                "status_code": None,
                "content_type": "",
                "success": False,
                "message": "Could not build a public URL for this endpoint.",
            })
            continue

        method = "POST" if path == INBOUND_MCP_RESOURCE_PATH else "GET"
        try:
            response = requests.request(
                method,
                url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={"jsonrpc": "2.0", "id": "easy-auth-check", "method": "tools/list", "params": {}}
                if method == "POST"
                else None,
                timeout=timeout_seconds,
                allow_redirects=False,
            )
            endpoint_results.append(_evaluate_probe_response(path, response))
        except requests.RequestException as request_error:
            log_event(
                "[InboundMCP] Easy Auth exclusion probe request failed.",
                extra={
                    "path": path,
                    "error_type": type(request_error).__name__,
                },
                level=logging.WARNING,
            )
            endpoint_results.append({
                "path": path,
                "status_code": None,
                "content_type": "",
                "success": False,
                "message": "Endpoint probe failed before reaching SimpleChat.",
            })

    success = all(result.get("success") for result in endpoint_results)
    return {
        "success": success,
        "required_excluded_paths": list(INBOUND_MCP_EASY_AUTH_EXCLUDED_PATHS),
        "endpoints": endpoint_results,
        "message": (
            "All inbound MCP Easy Auth exclusions are reachable."
            if success
            else "One or more inbound MCP endpoints are still intercepted before reaching SimpleChat."
        ),
    }


def is_mcp_ui_enabled():
    """Return whether the inbound MCP admin UI is enabled from OS environment only."""
    return _normalize_bool(os.getenv("ENABLE_MCP_UI", os.getenv("enable_mcp_ui", "false")))
