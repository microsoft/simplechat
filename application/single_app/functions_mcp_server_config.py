# functions_mcp_server_config.py

import json
import os
import re

import requests

from config import INBOUND_MCP_PRM_PATH, INBOUND_MCP_RESOURCE_PATH, TENANT_ID


INBOUND_MCP_SETTINGS_DEFAULTS = {
    "enable_inbound_mcp_server": False,
    "inbound_mcp_required_user_roles": ["InboundMCPUserAccess"],
    "inbound_mcp_required_app_roles": ["InboundMCPAppAccess"],
    "inbound_mcp_required_scope": "DelegatedMcpServerAccess",
    "inbound_mcp_allowed_client_app_ids": [],
    "inbound_mcp_allowed_tenant_ids": [],
    "inbound_mcp_allowed_source_ids": ["*"],
    "inbound_mcp_source_header": "X-SimpleChat-MCP-Source",
}
INBOUND_MCP_MUTABLE_SETTING_KEYS = tuple(INBOUND_MCP_SETTINGS_DEFAULTS.keys())
INBOUND_MCP_LEGACY_REQUIRED_ROLE_KEY = "inbound_mcp_required_role"
INBOUND_MCP_LEGACY_REQUIRED_ROLE_VALUE = "McpServerAccess"
INBOUND_MCP_EASY_AUTH_EXCLUDED_PATHS = (
    INBOUND_MCP_PRM_PATH,
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
    if "inbound_mcp_required_user_roles" not in settings and legacy_required_role:
        legacy_roles = normalize_inbound_mcp_list(legacy_required_role)
        if legacy_roles == [INBOUND_MCP_LEGACY_REQUIRED_ROLE_VALUE]:
            legacy_roles = INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_required_user_roles"]
        settings["inbound_mcp_required_user_roles"] = legacy_roles
        changed = True

    for key, default_value in INBOUND_MCP_SETTINGS_DEFAULTS.items():
        if key not in settings:
            settings[key] = list(default_value) if isinstance(default_value, list) else default_value
            changed = True

    normalized_values = {
        "enable_inbound_mcp_server": _normalize_bool(settings.get("enable_inbound_mcp_server")),
        "inbound_mcp_required_user_roles": normalize_inbound_mcp_list(
            settings.get("inbound_mcp_required_user_roles"),
            default=INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_required_user_roles"],
        ),
        "inbound_mcp_required_app_roles": normalize_inbound_mcp_list(
            settings.get("inbound_mcp_required_app_roles"),
            default=INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_required_app_roles"],
        ),
        "inbound_mcp_required_scope": _normalize_text(
            settings.get("inbound_mcp_required_scope"),
            INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_required_scope"],
            max_length=128,
        ),
        "inbound_mcp_allowed_client_app_ids": normalize_inbound_mcp_list(
            settings.get("inbound_mcp_allowed_client_app_ids"),
            lowercase=True,
        ),
        "inbound_mcp_allowed_tenant_ids": normalize_inbound_mcp_list(
            settings.get("inbound_mcp_allowed_tenant_ids"),
        ),
        "inbound_mcp_allowed_source_ids": normalize_inbound_mcp_list(
            settings.get("inbound_mcp_allowed_source_ids"),
            default=INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_allowed_source_ids"],
        ),
        "inbound_mcp_source_header": _normalize_text(
            settings.get("inbound_mcp_source_header"),
            INBOUND_MCP_SETTINGS_DEFAULTS["inbound_mcp_source_header"],
            max_length=128,
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
        from functions_settings import get_settings

        settings = get_settings() or {}

    config = dict(settings or {})
    normalize_inbound_mcp_settings(config)
    if not config.get("inbound_mcp_allowed_tenant_ids") and TENANT_ID:
        config["inbound_mcp_allowed_tenant_ids"] = [TENANT_ID]
    config["inbound_mcp_resource_path"] = INBOUND_MCP_RESOURCE_PATH
    config["inbound_mcp_prm_path"] = INBOUND_MCP_PRM_PATH
    return config


def _build_public_endpoint_url(base_url, path):
    normalized_base_url = str(base_url or "").strip().rstrip("/")
    normalized_path = str(path or "").strip()
    if not normalized_base_url or not normalized_path.startswith("/"):
        return ""
    return f"{normalized_base_url}{normalized_path}"


def _response_has_easy_auth_redirect(response):
    location = str(response.headers.get("Location") or "").lower()
    if response.is_redirect:
        return True
    return "/.auth/login" in location or "login.microsoftonline.com" in location


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

    if path == INBOUND_MCP_PRM_PATH:
        if response.status_code == 200 and payload and payload.get("mcp_endpoint") == INBOUND_MCP_RESOURCE_PATH:
            result["success"] = True
            result["message"] = "Protected resource metadata returned JSON successfully."
            return result
        result["message"] = "Protected resource metadata did not return the expected JSON contract."
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
            endpoint_results.append({
                "path": path,
                "status_code": None,
                "content_type": "",
                "success": False,
                "message": f"Endpoint probe failed: {request_error}",
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
