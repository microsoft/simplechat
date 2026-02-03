# functions_agent_payload.py
"""Utility helpers for normalizing agent payloads before validation and storage."""

from copy import deepcopy
from typing import Any, Dict, List

_SUPPORTED_AGENT_TYPES = {"local", "aifoundry"}
_APIM_FIELDS = [
    "azure_agent_apim_gpt_endpoint",
    "azure_agent_apim_gpt_subscription_key",
    "azure_agent_apim_gpt_deployment",
    "azure_agent_apim_gpt_api_version",
]
_GPT_FIELDS = [
    "azure_openai_gpt_endpoint",
    "azure_openai_gpt_key",
    "azure_openai_gpt_deployment",
    "azure_openai_gpt_api_version",
]
_FREE_FORM_TEXT = [
    "name",
    "display_name",
    "description",
    "instructions",
]
_TEXT_FIELDS = [
    "name",
    "display_name",
    "description",
    "instructions",
    "azure_openai_gpt_endpoint",
    "azure_openai_gpt_deployment",
    "azure_openai_gpt_api_version",
    "azure_agent_apim_gpt_endpoint",
    "azure_agent_apim_gpt_deployment",
    "azure_agent_apim_gpt_api_version",
    "model_endpoint_id",
    "model_id",
    "model_provider",
]
_STRING_DEFAULT_FIELDS = [
    "azure_openai_gpt_endpoint",
    "azure_openai_gpt_key",
    "azure_openai_gpt_deployment",
    "azure_openai_gpt_api_version",
    "azure_agent_apim_gpt_endpoint",
    "azure_agent_apim_gpt_subscription_key",
    "azure_agent_apim_gpt_deployment",
    "azure_agent_apim_gpt_api_version",
    "model_endpoint_id",
    "model_id",
    "model_provider",
]

_MAX_FIELD_LENGTHS = {
    "name": 100,
    "display_name": 200,
    "description": 2000,
    "instructions": 30000,
    "azure_openai_gpt_endpoint": 2048,
    "azure_openai_gpt_key": 1024,
    "azure_openai_gpt_deployment": 256,
    "azure_openai_gpt_api_version": 64,
    "azure_agent_apim_gpt_endpoint": 2048,
    "azure_agent_apim_gpt_subscription_key": 1024,
    "azure_agent_apim_gpt_deployment": 256,
    "azure_agent_apim_gpt_api_version": 64,
    "model_endpoint_id": 128,
    "model_id": 128,
    "model_provider": 32,
}
_FOUNDRY_FIELD_LENGTHS = {
    "agent_id": 128,
    "endpoint": 2048,
    "api_version": 64,
    "authority": 2048,
    "tenant_id": 64,
    "client_id": 64,
    "client_secret": 1024,
    "managed_identity_client_id": 64,
}


class AgentPayloadError(ValueError):
    """Raised when an agent payload violates backend requirements."""


def is_azure_ai_foundry_agent(agent: Dict[str, Any]) -> bool:
    """Return True when the agent type is Azure AI Foundry."""
    agent_type = (agent or {}).get("agent_type", "local")
    if isinstance(agent_type, str):
        return agent_type.strip().lower() == "aifoundry"
    return False


def _normalize_text_fields(payload: Dict[str, Any]) -> None:
    for field in _TEXT_FIELDS:
        value = payload.get(field)
        if isinstance(value, str):
            payload[field] = value.strip()


def _coerce_actions(actions: Any) -> List[str]:
    if actions is None or actions == "":
        return []
    if not isinstance(actions, list):
        raise AgentPayloadError("actions_to_load must be an array of strings.")
    cleaned: List[str] = []
    for item in actions:
        if isinstance(item, str):
            trimmed = item.strip()
            if trimmed:
                cleaned.append(trimmed)
        else:
            raise AgentPayloadError("actions_to_load entries must be strings.")
    return cleaned


def _coerce_other_settings(settings: Any) -> Dict[str, Any]:
    if settings in (None, ""):
        return {}
    if not isinstance(settings, dict):
        raise AgentPayloadError("other_settings must be an object.")
    return settings


def _coerce_agent_type(agent_type: Any) -> str:
    if isinstance(agent_type, str):
        agent_type = agent_type.strip().lower()
    else:
        agent_type = "local"
    if agent_type not in _SUPPORTED_AGENT_TYPES:
        return "local"
    return agent_type


def _coerce_completion_tokens(value: Any) -> int:
    if value in (None, "", " "):
        return -1
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AgentPayloadError("max_completion_tokens must be an integer.") from exc

def _validate_field_lengths(payload: Dict[str, Any]) -> None:
    for field, max_len in _MAX_FIELD_LENGTHS.items():
        value = payload.get(field, "")
        if isinstance(value, str) and len(value) > max_len:
            raise AgentPayloadError(f"{field} exceeds maximum length of {max_len}.")


def _validate_foundry_field_lengths(foundry_settings: Dict[str, Any]) -> None:
    for field, max_len in _FOUNDRY_FIELD_LENGTHS.items():
        value = foundry_settings.get(field, "")
        if isinstance(value, str) and len(value) > max_len:
            raise AgentPayloadError(f"azure_ai_foundry.{field} exceeds maximum length of {max_len}.")

def sanitize_agent_payload(agent: Dict[str, Any]) -> Dict[str, Any]:
    """Return a sanitized copy of the agent payload or raise AgentPayloadError."""
    if not isinstance(agent, dict):
        raise AgentPayloadError("Agent payload must be an object.")

    sanitized = deepcopy(agent)
    _normalize_text_fields(sanitized)

    for field in _STRING_DEFAULT_FIELDS:
        value = sanitized.get(field)
        if value is None:
            sanitized[field] = ""

    _validate_field_lengths(sanitized)

    agent_type = _coerce_agent_type(sanitized.get("agent_type"))
    sanitized["agent_type"] = agent_type

    sanitized["other_settings"] = _coerce_other_settings(sanitized.get("other_settings"))
    sanitized["actions_to_load"] = _coerce_actions(sanitized.get("actions_to_load"))
    sanitized["max_completion_tokens"] = _coerce_completion_tokens(
        sanitized.get("max_completion_tokens")
    )

    sanitized["enable_agent_gpt_apim"] = bool(
        sanitized.get("enable_agent_gpt_apim", False)
    )
    sanitized.setdefault("is_global", False)
    sanitized.setdefault("is_group", False)

    if agent_type == "aifoundry":
        sanitized["enable_agent_gpt_apim"] = False
        for field in _APIM_FIELDS:
            sanitized.pop(field, None)
        sanitized["actions_to_load"] = []

        foundry_settings = sanitized["other_settings"].get("azure_ai_foundry")
        if not isinstance(foundry_settings, dict):
            raise AgentPayloadError(
                "Azure AI Foundry agents require other_settings.azure_ai_foundry."
            )
        agent_id = str(foundry_settings.get("agent_id", "")).strip()
        if not agent_id:
            raise AgentPayloadError(
                "Azure AI Foundry agents require other_settings.azure_ai_foundry.agent_id."
            )
        foundry_settings["agent_id"] = agent_id
        _validate_foundry_field_lengths(foundry_settings)
        sanitized["other_settings"]["azure_ai_foundry"] = foundry_settings
    else:
        # Remove stale foundry metadata when toggling back to local agents.
        azure_foundry = sanitized["other_settings"].get("azure_ai_foundry")
        if azure_foundry is not None and not isinstance(azure_foundry, dict):
            raise AgentPayloadError("azure_ai_foundry must be an object when provided.")
        if azure_foundry:
            sanitized["other_settings"].pop("azure_ai_foundry", None)

    return sanitized