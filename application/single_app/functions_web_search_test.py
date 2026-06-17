# functions_web_search_test.py
"""Admin Web Search connection testing helpers."""

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, List, Tuple
from urllib.parse import urlparse

from foundry_agent_runtime import FoundryAgentInvocationError, execute_foundry_agent
from functions_appinsights import log_event
from semantic_kernel.contents.chat_message_content import ChatMessageContent


WEB_SEARCH_TEST_QUERY = (
    "Use the Grounding with Bing Search tool to find the official Microsoft website. "
    "Reply with the page title and URL only."
)

SENSITIVE_FIELD_NAMES = ("secret", "password", "key", "token")


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _safe_str(value).lower() in {"1", "true", "yes", "on"}


def _extract_foundry_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    foundry_payload = payload.get("foundry")
    if isinstance(foundry_payload, dict):
        return foundry_payload

    web_search_agent = payload.get("web_search_agent")
    if isinstance(web_search_agent, dict):
        other_settings = web_search_agent.get("other_settings") or {}
        nested_foundry = other_settings.get("azure_ai_foundry")
        if isinstance(nested_foundry, dict):
            merged = dict(nested_foundry)
            merged.setdefault("endpoint", web_search_agent.get("azure_openai_gpt_endpoint"))
            merged.setdefault("api_version", web_search_agent.get("azure_openai_gpt_api_version"))
            return merged

    return {}


def build_web_search_foundry_settings(payload: Dict[str, Any]) -> Dict[str, str]:
    """Normalize Web Search Foundry settings from the admin test payload."""

    foundry_payload = _extract_foundry_payload(payload)
    return {
        "agent_id": _safe_str(foundry_payload.get("agent_id")),
        "endpoint": _safe_str(foundry_payload.get("endpoint")),
        "api_version": _safe_str(foundry_payload.get("api_version")),
        "authentication_type": _safe_str(
            foundry_payload.get("authentication_type") or "managed_identity"
        ),
        "managed_identity_type": _safe_str(
            foundry_payload.get("managed_identity_type") or "system_assigned"
        ),
        "managed_identity_client_id": _safe_str(foundry_payload.get("managed_identity_client_id")),
        "tenant_id": _safe_str(foundry_payload.get("tenant_id")),
        "client_id": _safe_str(foundry_payload.get("client_id")),
        "client_secret": _safe_str(foundry_payload.get("client_secret")),
        "cloud": _safe_str(foundry_payload.get("cloud")),
        "authority": _safe_str(foundry_payload.get("authority")),
    }


def validate_web_search_foundry_settings(foundry_settings: Dict[str, str]) -> List[str]:
    """Return user-actionable validation errors before making a Foundry request."""

    errors: List[str] = []
    endpoint = foundry_settings.get("endpoint", "")
    api_version = foundry_settings.get("api_version", "")
    agent_id = foundry_settings.get("agent_id", "")
    auth_type = foundry_settings.get("authentication_type", "managed_identity")
    managed_identity_type = foundry_settings.get("managed_identity_type", "system_assigned")

    if not endpoint:
        errors.append("Foundry Project Endpoint is required.")
    else:
        parsed_endpoint = urlparse(endpoint)
        if parsed_endpoint.scheme != "https" or not parsed_endpoint.netloc:
            errors.append("Foundry Project Endpoint must be a valid HTTPS URL.")
        if "/api/projects/" not in parsed_endpoint.path:
            errors.append(
                "Foundry Project Endpoint must include /api/projects/<project-name>."
            )

    if not api_version:
        errors.append("Foundry API Version is required.")

    if not agent_id:
        errors.append("Foundry Agent ID is required.")

    if auth_type not in {"managed_identity", "service_principal"}:
        errors.append("Authentication Type must be Managed Identity or Service Principal.")

    if auth_type == "managed_identity":
        if managed_identity_type not in {"system_assigned", "user_assigned"}:
            errors.append("Managed Identity Type must be system-assigned or user-assigned.")
        if managed_identity_type == "user_assigned" and not foundry_settings.get(
            "managed_identity_client_id"
        ):
            errors.append("Managed Identity Client ID is required for user-assigned identity.")

    if auth_type == "service_principal":
        if not foundry_settings.get("tenant_id"):
            errors.append("Tenant ID is required for service principal authentication.")
        if not foundry_settings.get("client_id"):
            errors.append("Client ID is required for service principal authentication.")
        if not foundry_settings.get("client_secret"):
            errors.append("Client Secret is required for service principal authentication.")

    if auth_type == "service_principal" and foundry_settings.get("cloud") == "custom":
        authority = foundry_settings.get("authority", "")
        if not authority:
            errors.append("Authority Endpoint is required when Custom cloud is selected.")
        else:
            parsed_authority = urlparse(authority)
            if parsed_authority.scheme != "https" or not parsed_authority.netloc:
                errors.append("Authority Endpoint must be a valid HTTPS URL.")

    return errors


def _collect_sensitive_values(value: Any, sensitive_values: List[str]) -> None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            lowered_key = str(key).lower()
            if any(field_name in lowered_key for field_name in SENSITIVE_FIELD_NAMES):
                secret_value = _safe_str(nested_value)
                if secret_value:
                    sensitive_values.append(secret_value)
            else:
                _collect_sensitive_values(nested_value, sensitive_values)
        return

    if isinstance(value, list):
        for item in value:
            _collect_sensitive_values(item, sensitive_values)


def _redact_sensitive_text(text: str, payload: Dict[str, Any]) -> str:
    redacted_text = _safe_str(text)
    sensitive_values: List[str] = []
    _collect_sensitive_values(payload, sensitive_values)
    for sensitive_value in sorted(set(sensitive_values), key=len, reverse=True):
        if len(sensitive_value) >= 4:
            redacted_text = redacted_text.replace(sensitive_value, "[redacted]")
    return redacted_text[:1000]


def _categorize_web_search_error(error: Exception) -> Tuple[str, str, List[str]]:
    error_text = _safe_str(error)
    lowered_error = error_text.lower()

    if any(marker in lowered_error for marker in ["401", "unauthorized", "authentication", "invalid_client", "credential"]):
        return (
            "authentication",
            "Foundry authentication failed before the web search agent could run.",
            [
                "Confirm the selected authentication type matches the identity you configured.",
                "For managed identity, make sure the App Service identity is enabled and available to the app.",
                "For service principal, verify the tenant ID, client ID, and secret or Key Vault reference.",
            ],
        )

    if any(marker in lowered_error for marker in ["403", "forbidden", "authorization", "permission", "rbac"]):
        return (
            "permission",
            "Foundry rejected the request because the configured identity does not have enough access.",
            [
                "Grant the identity Foundry User on the Foundry project; Azure Government and custom clouds may still show this role as Azure AI User.",
                "If role assignments were just added, wait a few minutes for propagation and test again.",
                "Confirm the agent itself has access to Grounding with Bing Search in the selected project.",
            ],
        )

    if any(marker in lowered_error for marker in ["404", "not found", "does not exist"]):
        return (
            "not_found",
            "The Foundry project endpoint or agent ID could not be found.",
            [
                "Confirm the endpoint is the project endpoint and includes /api/projects/<project-name>.",
                "Confirm the Foundry Agent ID is copied from the same project.",
                "Check that the API version is supported by the Foundry project.",
            ],
        )

    if any(marker in lowered_error for marker in ["429", "rate", "quota", "too many requests", "throttle"]):
        return (
            "quota_or_rate_limit",
            "Foundry or the model deployment throttled the web search test.",
            [
                "Wait and test again after the rate limit window clears.",
                "Check Foundry/model quota and the agent model deployment capacity.",
            ],
        )

    if any(marker in lowered_error for marker in ["timeout", "timed out", "connection", "dns", "name resolution", "network"]):
        return (
            "network",
            "The app could not reach the Foundry project endpoint.",
            [
                "Check private endpoint, DNS, VNet integration, and firewall rules for the App Service.",
                "Confirm the endpoint host is reachable from the deployed app environment.",
            ],
        )

    if any(marker in lowered_error for marker in ["bing", "grounding", "tool"]):
        return (
            "agent_tooling",
            "The Foundry agent ran into a web-search tool configuration problem.",
            [
                "Open the agent in Azure AI Foundry and confirm Grounding with Bing Search is enabled.",
                "Confirm any required Bing grounding terms or project-level settings are accepted.",
            ],
        )

    if isinstance(error, FoundryAgentInvocationError):
        return (
            "foundry_invocation",
            "The Foundry agent could not complete the web search test.",
            [
                "Review the endpoint, API version, agent ID, authentication settings, and agent tool configuration.",
                "Check Application Insights for the [WebSearchTest] event if the browser message is not enough.",
            ],
        )

    return (
        "unexpected",
        "The web search test failed unexpectedly.",
        [
            "Check Application Insights for the [WebSearchTest] event and verify the Foundry project settings.",
        ],
    )


def _result_value(result: Any, field_name: str, default_value: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(field_name, default_value)
    return getattr(result, field_name, default_value)


def _preview_text(value: Any, limit: int = 700) -> str:
    text = _safe_str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _resolve_test_query(payload: Dict[str, Any]) -> str:
    query = _safe_str(payload.get("query"))
    if not query:
        return WEB_SEARCH_TEST_QUERY
    return query[:500]


def run_web_search_connection_test(
    payload: Dict[str, Any],
    *,
    global_settings: Dict[str, Any],
    execute_agent: Callable[..., Any] = execute_foundry_agent,
) -> Tuple[Dict[str, Any], int]:
    """Run a small Web Search Foundry agent smoke test and return a JSON-safe result."""

    if "enabled" in payload and not _is_truthy(payload.get("enabled")):
        return {
            "success": False,
            "status": "configuration_error",
            "message": "Web Search is currently disabled in this settings form.",
            "guidance": ["Turn on Enable Web Search via Foundry Agent before testing."],
        }, 400

    if "consent_accepted" in payload and not _is_truthy(payload.get("consent_accepted")):
        return {
            "success": False,
            "status": "configuration_error",
            "message": "Web Search consent has not been accepted.",
            "guidance": ["Accept the Grounding with Bing Search notice before testing."],
        }, 400

    foundry_settings = build_web_search_foundry_settings(payload)
    validation_errors = validate_web_search_foundry_settings(foundry_settings)
    if validation_errors:
        return {
            "success": False,
            "status": "configuration_error",
            "message": "Web Search test could not start because required settings are missing or invalid.",
            "guidance": validation_errors,
        }, 400

    test_query = _resolve_test_query(payload)
    message_history = [ChatMessageContent(role="user", content=test_query)]
    metadata = {"source": "admin_settings_web_search_test"}

    try:
        execution_result = execute_agent(
            foundry_settings=foundry_settings,
            global_settings=global_settings or {},
            message_history=message_history,
            metadata=metadata,
        )
        if inspect.isawaitable(execution_result):
            execution_result = asyncio.run(execution_result)

        response_message = _safe_str(_result_value(execution_result, "message", ""))
        citations = _result_value(execution_result, "citations", []) or []
        model = _safe_str(_result_value(execution_result, "model", ""))
        citation_count = len(citations) if isinstance(citations, list) else 0

        if not response_message:
            raise FoundryAgentInvocationError("Foundry agent returned an empty response.")

        status = "success"
        message = "Web Search test succeeded. The Foundry agent responded to a live web-search prompt."
        guidance: List[str] = []
        if citation_count == 0:
            status = "warning"
            message = "The Foundry agent responded, but no web citations were returned."
            guidance = [
                "Confirm the agent has Grounding with Bing Search enabled.",
                "Confirm the agent instructions allow it to use web search for the test prompt.",
            ]

        details = [
            "Foundry project endpoint and agent ID were accepted.",
            f"Agent response length: {len(response_message)} characters.",
            f"Detected web citations: {citation_count}.",
        ]
        if model:
            details.append(f"Agent model: {model}.")

        log_event(
            "[WebSearchTest] Foundry web search test completed",
            extra={
                "status": status,
                "agent_id": foundry_settings.get("agent_id"),
                "response_length": len(response_message),
                "citation_count": citation_count,
            },
            level=logging.INFO,
        )
        return {
            "success": True,
            "status": status,
            "message": message,
            "details": details,
            "guidance": guidance,
            "response_preview": _preview_text(response_message),
        }, 200
    except Exception as error:
        category, message, guidance = _categorize_web_search_error(error)
        safe_error = _redact_sensitive_text(str(error), payload)
        log_event(
            "[WebSearchTest] Foundry web search test failed",
            extra={
                "category": category,
                "agent_id": foundry_settings.get("agent_id"),
                "error": safe_error,
            },
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return {
            "success": False,
            "status": category,
            "message": message,
            "error": safe_error,
            "guidance": guidance,
        }, 500