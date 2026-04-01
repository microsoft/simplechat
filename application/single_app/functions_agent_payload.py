# functions_agent_payload.py
"""Utility helpers for normalizing agent payloads before validation and storage."""

from copy import deepcopy
from typing import Any, Dict, List

_SUPPORTED_AGENT_TYPES = {"local", "aifoundry", "new_foundry"}
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
_SERVER_MANAGED_FIELDS = [
    "_attachments",
    "_etag",
    "_rid",
    "_self",
    "_ts",
    "created_at",
    "created_by",
    "modified_at",
    "modified_by",
    "updated_at",
    "last_updated",
    "user_id",
    "group_id",
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
_NEW_FOUNDRY_FIELD_LENGTHS = {
    "application_id": 256,
    "application_name": 200,
    "application_version": 64,
    "endpoint": 2048,
    "project_name": 256,
    "responses_api_version": 64,
    "activity_api_version": 64,
    "authority": 2048,
    "tenant_id": 64,
    "client_id": 64,
    "client_secret": 1024,
    "managed_identity_client_id": 64,
    "notes": 2000,
}


class AgentPayloadError(ValueError):
    """Raised when an agent payload violates backend requirements."""


def is_azure_ai_foundry_agent(agent: Dict[str, Any]) -> bool:
    """Return True when the agent type is Azure AI Foundry."""
    agent_type = (agent or {}).get("agent_type", "local")
    if isinstance(agent_type, str):
        return agent_type.strip().lower() in {"aifoundry", "new_foundry"}
    return False


def is_new_foundry_agent(agent: Dict[str, Any]) -> bool:
    """Return True when the agent type is the new Foundry experience."""
    agent_type = (agent or {}).get("agent_type", "local")
    if isinstance(agent_type, str):
        return agent_type.strip().lower() == "new_foundry"
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


def _validate_new_foundry_field_lengths(new_foundry_settings: Dict[str, Any]) -> None:
    for field, max_len in _NEW_FOUNDRY_FIELD_LENGTHS.items():
        value = new_foundry_settings.get(field, "")
        if isinstance(value, str) and len(value) > max_len:
            raise AgentPayloadError(f"new_foundry.{field} exceeds maximum length of {max_len}.")


def _strip_empty_values(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "")
    }


def _strip_server_managed_fields(payload: Dict[str, Any]) -> None:
    for field in _SERVER_MANAGED_FIELDS:
        payload.pop(field, None)

def sanitize_agent_payload(agent: Dict[str, Any]) -> Dict[str, Any]:
    """Return a sanitized copy of the agent payload or raise AgentPayloadError."""
    if not isinstance(agent, dict):
        raise AgentPayloadError("Agent payload must be an object.")

    sanitized = deepcopy(agent)
    _strip_server_managed_fields(sanitized)
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
        sanitized["other_settings"].pop("new_foundry", None)
    elif agent_type == "new_foundry":
        sanitized["enable_agent_gpt_apim"] = False
        for field in _APIM_FIELDS:
            sanitized.pop(field, None)
        sanitized["actions_to_load"] = []

        new_foundry_settings = sanitized["other_settings"].get("new_foundry")
        if not isinstance(new_foundry_settings, dict):
            raise AgentPayloadError(
                "New Foundry agents require other_settings.new_foundry."
            )

        application_id = str(new_foundry_settings.get("application_id", "")).strip()
        application_name = str(new_foundry_settings.get("application_name", "")).strip()
        application_version = str(new_foundry_settings.get("application_version", "")).strip()

        if not application_id:
            if application_name and application_version:
                application_id = f"{application_name}:{application_version}"
            elif application_name:
                application_id = application_name

        if not application_id:
            raise AgentPayloadError(
                "New Foundry agents require other_settings.new_foundry.application_id or application_name."
            )

        if ":" in application_id and not application_name:
            parsed_name, parsed_version = application_id.split(":", 1)
            application_name = application_name or parsed_name.strip()
            application_version = application_version or parsed_version.strip()

        new_foundry_settings["application_id"] = application_id
        if application_name:
            new_foundry_settings["application_name"] = application_name
        if application_version:
            new_foundry_settings["application_version"] = application_version

        response_version = str(
            new_foundry_settings.get("responses_api_version")
            or sanitized.get("azure_openai_gpt_api_version")
            or ""
        ).strip()
        if not response_version:
            raise AgentPayloadError(
                "New Foundry agents require other_settings.new_foundry.responses_api_version or azure_openai_gpt_api_version."
            )
        new_foundry_settings["responses_api_version"] = response_version

        activity_version = str(new_foundry_settings.get("activity_api_version", "")).strip()
        if activity_version:
            new_foundry_settings["activity_api_version"] = activity_version

        endpoint = str(
            new_foundry_settings.get("endpoint")
            or sanitized.get("azure_openai_gpt_endpoint")
            or ""
        ).strip()
        if endpoint:
            new_foundry_settings["endpoint"] = endpoint
            sanitized["azure_openai_gpt_endpoint"] = endpoint

        project_name = str(
            new_foundry_settings.get("project_name")
            or sanitized.get("azure_openai_gpt_deployment")
            or ""
        ).strip()
        if project_name:
            new_foundry_settings["project_name"] = project_name
            sanitized["azure_openai_gpt_deployment"] = project_name

        sanitized["azure_openai_gpt_api_version"] = response_version

        _validate_new_foundry_field_lengths(new_foundry_settings)
        sanitized["other_settings"]["new_foundry"] = _strip_empty_values(new_foundry_settings)
        sanitized["other_settings"].pop("azure_ai_foundry", None)
    else:
        # Remove stale foundry metadata when toggling back to local agents.
        azure_foundry = sanitized["other_settings"].get("azure_ai_foundry")
        if azure_foundry is not None and not isinstance(azure_foundry, dict):
            raise AgentPayloadError("azure_ai_foundry must be an object when provided.")
        if azure_foundry:
            sanitized["other_settings"].pop("azure_ai_foundry", None)
        new_foundry = sanitized["other_settings"].get("new_foundry")
        if new_foundry is not None and not isinstance(new_foundry, dict):
            raise AgentPayloadError("new_foundry must be an object when provided.")
        if new_foundry:
            sanitized["other_settings"].pop("new_foundry", None)

    return sanitized