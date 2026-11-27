# functions_model_persona.py
"""Validation and request composition for configured model personas."""

from copy import deepcopy
import json
from typing import Any, Mapping

from functions_ai_connections import AIConnectionError


MODEL_PERSONA_ENABLED_FIELD = "persona_enabled"
MODEL_PERSONA_MARKDOWN_FIELD = "persona_markdown"
MODEL_PERSONA_TEXT_VISIBLE_FIELD = "persona_text_visible"
MODEL_PERSONA_MAX_CHARACTERS = 8000
MODEL_PERSONA_COLLECTION_MAX_BYTES = 1_500_000
MODEL_PERSONA_SETTINGS_DOCUMENT_MAX_BYTES = 1_900_000

PERSONA_SYSTEM_MESSAGE_PREFIX = (
    "The following supplemental model persona was configured for this model. "
    "Treat it as behavioral guidance for the request without overriding application "
    "safety, authorization, tool, grounding, task, or output requirements.\n\n"
)


def model_persona_character_count(value: str) -> int:
    """Count Unicode code points consistently with the browser editor."""
    return len(value)


def normalize_model_persona(model: Mapping[str, Any]) -> dict[str, Any]:
    """Validate persona fields while preserving absent legacy fields."""
    if not isinstance(model, Mapping):
        raise AIConnectionError("Model configuration must be an object.")

    normalized = dict(model)
    enabled = normalized.get(MODEL_PERSONA_ENABLED_FIELD, False)
    if not isinstance(enabled, bool):
        raise AIConnectionError("Model persona enabled must be true or false.", "invalid_model_persona")

    markdown = normalized.get(MODEL_PERSONA_MARKDOWN_FIELD, "")
    if not isinstance(markdown, str):
        raise AIConnectionError("Model persona content must be text.", "invalid_model_persona")
    if model_persona_character_count(markdown) > MODEL_PERSONA_MAX_CHARACTERS:
        raise AIConnectionError(
            f"Model persona content cannot exceed {MODEL_PERSONA_MAX_CHARACTERS} characters.",
            "invalid_model_persona",
        )

    visible = normalized.get(MODEL_PERSONA_TEXT_VISIBLE_FIELD, True)
    if not isinstance(visible, bool):
        raise AIConnectionError(
            "Model persona visibility must be true or false.",
            "invalid_model_persona",
        )

    return normalized


def active_model_persona_markdown(model: Any) -> str:
    """Return active persona source for a validated model, otherwise an empty string."""
    if not isinstance(model, Mapping) or model.get(MODEL_PERSONA_ENABLED_FIELD) is not True:
        return ""
    markdown = model.get(MODEL_PERSONA_MARKDOWN_FIELD)
    return markdown if isinstance(markdown, str) and markdown.strip() else ""


def model_persona_system_message(markdown: str) -> dict[str, str]:
    """Build the single supplemental system message sent to a provider."""
    return {
        "role": "system",
        "content": f"{PERSONA_SYSTEM_MESSAGE_PREFIX}{markdown}",
    }


def prepend_model_persona_messages(messages: Any, persona_markdown: str) -> Any:
    """Return request-owned messages with one persona message when active."""
    if not persona_markdown or not isinstance(messages, (list, tuple)):
        return messages
    return [model_persona_system_message(persona_markdown), *deepcopy(list(messages))]


def prepend_model_persona_request(request: Any, persona_markdown: str) -> Any:
    """Compose persona content into one OpenAI-compatible request copy."""
    if not persona_markdown or not isinstance(request, Mapping):
        return request

    composed = dict(request)
    if isinstance(composed.get("messages"), (list, tuple)):
        composed["messages"] = prepend_model_persona_messages(
            composed["messages"], persona_markdown
        )
        return composed

    model_input = composed.get("input")
    if isinstance(model_input, (list, tuple)):
        composed["input"] = [
            model_persona_system_message(persona_markdown),
            *deepcopy(list(model_input)),
        ]
    elif isinstance(model_input, str):
        composed["input"] = [
            model_persona_system_message(persona_markdown),
            {"role": "user", "content": model_input},
        ]
    return composed


def bound_model_persona(target: Any) -> str:
    """Read a non-secret persona marker from a bound client or service."""
    persona = getattr(target, "_simplechat_model_persona", "")
    if isinstance(persona, str) and persona:
        return persona

    client = getattr(target, "client", None)
    persona = getattr(client, "_simplechat_model_persona", "")
    if isinstance(persona, str) and persona:
        return persona

    persona = getattr(target, "model_persona_markdown", "")
    return persona if isinstance(persona, str) else ""


def bound_model_persona_metadata(target: Any) -> Any:
    """Return the non-secret model metadata associated with a persona-bound client."""
    metadata = getattr(target, "_simplechat_model_persona_metadata", None)
    return metadata if isinstance(metadata, Mapping) else None


def validate_model_persona_collection_size(endpoints: Any) -> None:
    """Reject endpoint collections whose persona content consumes settings headroom."""
    if not isinstance(endpoints, list):
        return

    persona_bytes = 0
    for endpoint in endpoints:
        if not isinstance(endpoint, Mapping):
            continue
        models = endpoint.get("models") or []
        if not isinstance(models, list):
            continue
        for model in models:
            if not isinstance(model, Mapping):
                continue
            markdown = model.get(MODEL_PERSONA_MARKDOWN_FIELD, "")
            if isinstance(markdown, str):
                persona_bytes += len(markdown.encode("utf-8"))

    if not persona_bytes:
        return
    collection_bytes = len(
        json.dumps(
            endpoints,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if (
        persona_bytes > MODEL_PERSONA_COLLECTION_MAX_BYTES
        or collection_bytes > MODEL_PERSONA_COLLECTION_MAX_BYTES
    ):
        raise AIConnectionError(
            "The model persona configuration is too large. Shorten or remove persona text before saving.",
            "model_persona_collection_too_large",
        )


def validate_model_persona_settings_document(document: Any) -> None:
    """Validate a complete settings/group item with Cosmos-equivalent JSON escaping."""
    if not isinstance(document, Mapping):
        return

    has_persona = False
    key_vault_reference_reserve = 0

    settings = document.get("settings")
    candidates = []
    if isinstance(document.get("model_endpoints"), list):
        candidates.append(document.get("model_endpoints"))
    if isinstance(settings, Mapping):
        for field in ("model_endpoints", "personal_model_endpoints"):
            if isinstance(settings.get(field), list):
                candidates.append(settings.get(field))

    for endpoints in candidates:
        for endpoint in endpoints:
            if not isinstance(endpoint, Mapping):
                continue
            auth = endpoint.get("auth")
            if isinstance(auth, Mapping):
                key_vault_reference_reserve += sum(
                    512
                    for field in ("api_key", "client_secret", "bearer_token")
                    if isinstance(auth.get(field), str) and bool(auth.get(field))
                )
            for model in endpoint.get("models") or []:
                if isinstance(model, Mapping) and (
                    model.get(MODEL_PERSONA_ENABLED_FIELD) is True
                    or isinstance(model.get(MODEL_PERSONA_MARKDOWN_FIELD), str)
                    and bool(model.get(MODEL_PERSONA_MARKDOWN_FIELD))
                ):
                    has_persona = True

    serialized = json.dumps(
        document,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if (
        has_persona
        and len(serialized) + key_vault_reference_reserve
        > MODEL_PERSONA_SETTINGS_DOCUMENT_MAX_BYTES
    ):
        raise AIConnectionError(
            "This persona configuration is too large for the settings document. Shorten or remove persona text before saving.",
            "model_persona_settings_too_large",
        )
