# functions_url_access_policy_test.py
"""Admin URL Access policy testing helpers."""

import logging
from typing import Any, Dict, List, Tuple

from functions_appinsights import log_event
from functions_source_review import (
    evaluate_source_review_url_policy,
    get_source_review_config,
    parse_source_review_list,
)


REASON_LABELS = {
    "allowed": "Allowed",
    "domain_allowed": "Domain allowed",
    "domain_not_allowed": "Domain not in allow list",
    "domain_blocked": "Domain is blocked",
    "blocked_hostname": "Hostname is blocked",
    "blocked_ip_address": "Hostname resolves to a blocked IP address",
    "empty_url": "URL is required",
    "hostname_resolution_empty": "Hostname resolution returned no addresses",
    "hostname_resolution_failed": "Hostname could not be resolved",
    "invalid_hostname": "Hostname is invalid",
    "invalid_port": "Port is invalid",
    "invalid_url": "URL is invalid",
    "ip_literal_hostname_not_allowed": "Literal IP addresses are blocked",
    "missing_host": "URL host is missing",
    "unsupported_scheme": "Only HTTP and HTTPS URLs are supported",
    "url_credentials_not_allowed": "URLs with embedded credentials are blocked",
}

REASON_GUIDANCE = {
    "domain_not_allowed": [
        "Add the hostname or parent domain to Allowed Domains, or leave the allow list blank to allow any public domain that passes safety checks.",
    ],
    "domain_blocked": [
        "Remove or narrow the matching Blocked Domains entry if this site should be available.",
    ],
    "blocked_hostname": [
        "URL Access always blocks localhost, metadata hosts, and internal hostnames unless the internal-host opt-in applies where supported.",
    ],
    "blocked_ip_address": [
        "The hostname resolved to a private, loopback, reserved, link-local, multicast, or unspecified IP address.",
    ],
    "hostname_resolution_failed": [
        "Confirm the hostname is public and resolvable from the app environment.",
    ],
    "ip_literal_hostname_not_allowed": [
        "Use a DNS hostname instead of a literal IP address.",
    ],
    "unsupported_scheme": [
        "Use a full http:// or https:// URL.",
    ],
    "url_credentials_not_allowed": [
        "Remove embedded usernames, passwords, or tokens from the URL.",
    ],
}


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _safe_str(value).lower() in {"1", "true", "yes", "on"}


def _reason_label(reason: str) -> str:
    return REASON_LABELS.get(reason or "", reason or "unknown")


def _build_policy_settings(payload: Dict[str, Any], global_settings: Dict[str, Any]) -> Dict[str, Any]:
    source_settings = dict(global_settings or {})

    if "enabled" in payload:
        source_settings["enable_url_access"] = _is_truthy(payload.get("enabled"))
    if "source_review_allow_internal_hosts" in payload:
        source_settings["source_review_allow_internal_hosts"] = _is_truthy(
            payload.get("source_review_allow_internal_hosts")
        )

    if "url_access_allowed_domains" in payload:
        allowed_domains = parse_source_review_list(payload.get("url_access_allowed_domains"))
        source_settings["url_access_allowed_domains"] = allowed_domains
        source_settings["source_review_allowed_domains"] = allowed_domains
    if "url_access_blocked_domains" in payload:
        blocked_domains = parse_source_review_list(payload.get("url_access_blocked_domains"))
        source_settings["url_access_blocked_domains"] = blocked_domains
        source_settings["source_review_blocked_domains"] = blocked_domains

    return get_source_review_config(source_settings)


def _build_policy_message(allowed: bool, domain_allowed: bool, reason: str) -> str:
    if allowed:
        return "URL Access would allow this URL."

    if domain_allowed:
        return f"Domain policy allows this URL, but URL safety validation blocked it: {_reason_label(reason)}."

    if reason == "domain_not_allowed":
        return "URL Access would block this URL because its domain is not in the allowed list."
    if reason == "domain_blocked":
        return "URL Access would block this URL because its domain matches the blocked list."
    if reason == "blocked_hostname":
        return "URL Access would block this URL because the hostname is not allowed."
    return f"URL Access would block this URL: {_reason_label(reason)}."


def _build_policy_details(
    evaluation: Dict[str, Any],
    source_settings: Dict[str, Any],
) -> List[str]:
    details = []
    if evaluation.get("normalized_url"):
        details.append(f"Normalized URL: {evaluation.get('normalized_url')}.")
    if evaluation.get("hostname"):
        details.append(f"Hostname: {evaluation.get('hostname')}.")

    allowed_domains = source_settings.get("url_access_allowed_domains") or []
    blocked_domains = source_settings.get("url_access_blocked_domains") or []
    details.append(
        "Allowed Domains: " + (", ".join(allowed_domains) if allowed_domains else "any public domain") + "."
    )
    details.append(
        "Blocked Domains: " + (", ".join(blocked_domains) if blocked_domains else "none") + "."
    )
    details.append(f"Domain policy result: {_reason_label(evaluation.get('domain_policy_reason', ''))}.")
    details.append(f"Safety validation result: {_reason_label(evaluation.get('url_access_reason', ''))}.")
    return details


def run_url_access_policy_test(
    payload: Dict[str, Any],
    *,
    global_settings: Dict[str, Any],
) -> Tuple[Dict[str, Any], int]:
    """Evaluate a URL against the current admin URL Access policy form values."""

    if "enabled" in payload and not _is_truthy(payload.get("enabled")):
        return {
            "success": False,
            "allowed": False,
            "status": "configuration_error",
            "message": "URL Access is currently disabled in this settings form.",
            "guidance": ["Turn on Enable URL Access for chat and workflows before testing."],
        }, 400

    test_url = _safe_str(payload.get("url"))
    if not test_url:
        return {
            "success": False,
            "allowed": False,
            "status": "empty_url",
            "message": "Enter a URL to test against the URL Access policy.",
            "guidance": ["Use a full http:// or https:// URL."],
        }, 400

    source_settings = _build_policy_settings(payload, global_settings)
    evaluation = evaluate_source_review_url_policy(test_url, source_settings)
    allowed = bool(evaluation.get("url_access_allowed"))
    domain_allowed = bool(evaluation.get("domain_policy_allowed"))
    reason = _safe_str(evaluation.get("url_access_reason") or evaluation.get("domain_policy_reason"))
    status_code = 200 if evaluation.get("normalized_url") else 400
    guidance = REASON_GUIDANCE.get(reason, [])

    log_event(
        "[UrlAccessPolicyTest] URL Access policy test completed",
        extra={
            "allowed": allowed,
            "domain_allowed": domain_allowed,
            "hostname": evaluation.get("hostname") or "",
            "reason": reason,
        },
        level=logging.INFO,
    )

    return {
        "success": evaluation.get("normalized_url") is not None,
        "allowed": allowed,
        "status": reason or "unknown",
        "message": _build_policy_message(allowed, domain_allowed, reason),
        "reason": reason,
        "reason_label": _reason_label(reason),
        "normalized_url": evaluation.get("normalized_url"),
        "hostname": evaluation.get("hostname") or "",
        "domain_policy": {
            "allowed": domain_allowed,
            "reason": evaluation.get("domain_policy_reason"),
            "reason_label": _reason_label(evaluation.get("domain_policy_reason", "")),
            "allowed_domains": list(source_settings.get("url_access_allowed_domains") or []),
            "blocked_domains": list(source_settings.get("url_access_blocked_domains") or []),
        },
        "details": _build_policy_details(evaluation, source_settings),
        "guidance": guidance,
    }, status_code