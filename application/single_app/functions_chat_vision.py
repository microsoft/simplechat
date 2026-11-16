# functions_chat_vision.py
"""Helpers for sending current-turn chat uploads to vision-capable chat models."""

import logging
from importlib import import_module

from functions_appinsights import log_event
from functions_image_formats import image_data_url, is_heif_file_name, is_image_file_name
from functions_image_references import resolve_image_references
from functions_model_capabilities import is_vision_capable_model


MAX_VISION_IMAGES = 4
MAX_VISION_IMAGE_PAYLOAD_BYTES = 20 * 1024 * 1024
VISION_INPUT_FORMATS = ["image/png", "image/jpeg", "image/webp", "image/gif"]
VISION_REFERENCE_CAPABILITY = {
    "enabled": True,
    "editing": True,
    "max_reference_images": 1,
    "input_formats": VISION_INPUT_FORMATS,
}

_OPENAI_COMPATIBLE_PROVIDER_KINDS = {
    "",
    "aoai",
    "azure",
    "azure_openai",
    "openai",
    "openai_style",
    "aifoundry",
    "new_foundry",
    "custom",
    "gemini",
    "anthropic",
    "claude",
}


def _message_is_inactive(message):
    metadata = message.get("metadata") if isinstance(message, dict) else {}
    thread_info = metadata.get("thread_info") if isinstance(metadata, dict) else {}
    return isinstance(thread_info, dict) and thread_info.get("active_thread") is False


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def _message_file_name(message):
    metadata = message.get("metadata") if isinstance(message, dict) else {}
    workspace_attachment = metadata.get("workspace_attachment") if isinstance(metadata, dict) else {}
    candidates = (
        message.get("filename"),
        message.get("file_name"),
        message.get("name"),
        metadata.get("file_name") if isinstance(metadata, dict) else None,
        metadata.get("original_file_name") if isinstance(metadata, dict) else None,
        workspace_attachment.get("file_name") if isinstance(workspace_attachment, dict) else None,
        workspace_attachment.get("filename") if isinstance(workspace_attachment, dict) else None,
    )
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return ""


def _selected_document_file_name(document):
    metadata = document.get("metadata") if isinstance(document, dict) else {}
    workspace_attachment = metadata.get("workspace_attachment") if isinstance(metadata, dict) else {}
    candidates = (
        document.get("file_name"),
        document.get("filename"),
        document.get("name"),
        document.get("title"),
        metadata.get("file_name") if isinstance(metadata, dict) else None,
        metadata.get("original_file_name") if isinstance(metadata, dict) else None,
        workspace_attachment.get("file_name") if isinstance(workspace_attachment, dict) else None,
    )
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return ""


def _selected_document_reference(document):
    if not isinstance(document, dict):
        return None
    file_name = _selected_document_file_name(document)
    if not file_name or not is_image_file_name(file_name) or is_heif_file_name(file_name):
        return None
    document_id = str(
        document.get("document_id")
        or document.get("doc_id")
        or document.get("id")
        or ""
    ).strip()
    if not document_id:
        return None
    scope = str(
        document.get("scope")
        or document.get("doc_scope")
        or document.get("document_scope")
        or ""
    ).strip().lower()
    if scope not in ("personal", "group", "public"):
        # Search results carry the owning workspace id rather than a scope name.
        if document.get("group_id"):
            scope = "group"
        elif document.get("public_workspace_id"):
            scope = "public"
        else:
            scope = "personal"
    scope_id = None
    if scope == "group":
        scope_id = document.get("scope_id") or document.get("group_id") or document.get("active_group_id")
    elif scope == "public":
        scope_id = (
            document.get("scope_id")
            or document.get("public_workspace_id")
            or document.get("active_public_workspace_id")
        )
    return {
        "type": "document",
        "document_id": document_id,
        "scope": scope,
        "scope_id": str(scope_id).strip() if scope_id not in (None, "") else None,
    }


def _append_reference(references, seen, reference):
    if not reference:
        return
    key = (
        reference.get("type"),
        reference.get("message_id") or reference.get("document_id"),
        reference.get("scope"),
        reference.get("scope_id"),
    )
    if key in seen or len(references) >= MAX_VISION_IMAGES:
        return
    seen.add(key)
    references.append(reference)


def explicitly_selected_documents(search_documents, requested_document_ids):
    """Return retrieved documents the user explicitly selected for this message.

    Search can match any document in scope, and chat uploads from earlier turns are linked
    into the search selection automatically. Only the documents named in this request count
    as the user pointing at an image this turn.
    """
    requested = {
        str(document_id or "").strip()
        for document_id in (requested_document_ids or [])
        if str(document_id or "").strip()
    }
    if not requested:
        return []
    return [
        document
        for document in (search_documents or [])
        if isinstance(document, dict) and str(document.get("document_id") or "").strip() in requested
    ]


def collect_current_turn_image_references(all_messages, user_message_id, *, selected_documents=None):
    """Return current-turn image references in order, deduped and capped."""
    messages = [message for message in (all_messages or []) if isinstance(message, dict)]
    current_index = next(
        (index for index, message in enumerate(messages) if str(message.get("id") or "") == str(user_message_id or "")),
        len(messages) - 1,
    )
    last_assistant_index = -1
    for index, message in enumerate(messages[: max(current_index, -1)]):
        if _message_is_inactive(message):
            continue
        if message.get("role") == "assistant":
            last_assistant_index = index

    references = []
    seen = set()
    uploaded_document_ids = set()
    for message in messages[last_assistant_index + 1 : current_index + 1]:
        if _message_is_inactive(message):
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        role = message.get("role")
        file_name = _message_file_name(message)
        if role == "file":
            if (
                _truthy(metadata.get("is_user_upload"))
                and message.get("workspace_document_id")
                and file_name
                and is_image_file_name(file_name)
                and not is_heif_file_name(file_name)
            ):
                _append_reference(references, seen, {"type": "message", "message_id": message.get("id")})
                uploaded_document_ids.add(str(message.get("workspace_document_id")).strip())
        elif role == "image":
            if (
                _truthy(metadata.get("is_user_upload"))
                and file_name
                and is_image_file_name(file_name)
                and not is_heif_file_name(file_name)
            ):
                _append_reference(references, seen, {"type": "message", "message_id": message.get("id")})
        if len(references) >= MAX_VISION_IMAGES:
            return references

    for document in selected_documents or []:
        reference = _selected_document_reference(document)
        # An upload is also a workspace document; selecting it must not send it twice.
        if reference and reference["document_id"] in uploaded_document_ids:
            continue
        _append_reference(references, seen, reference)
        if len(references) >= MAX_VISION_IMAGES:
            break
    return references


def _reference_log_id(reference):
    if not isinstance(reference, dict):
        return None
    return reference.get("message_id") or reference.get("document_id")


def _snapshot_screening_request_state():
    """Capture request-local screening evidence before an optional image read.

    A held or unreadable document records a failure (and a read records a consumed source)
    on ``flask.g``. The model-call guard raises that failure and rechecks every recorded
    source, so an image that is skipped here must leave no trace or it would fail the turn.
    """
    flask = import_module("flask")
    if not flask.has_request_context():
        return None
    return (
        getattr(flask.g, "content_screening_error", None),
        dict(getattr(flask.g, "content_screening_sources", {}) or {}),
    )


def _restore_screening_request_state(snapshot):
    if snapshot is None:
        return
    flask = import_module("flask")
    if not flask.has_request_context():
        return
    previous_error, previous_sources = snapshot
    flask.g.content_screening_error = previous_error
    flask.g.content_screening_sources = previous_sources


def build_vision_image_parts(
    settings,
    user_id,
    conversation_id,
    references,
    *,
    max_images=MAX_VISION_IMAGES,
    resolver=None,
):
    """Resolve references into OpenAI-style image_url message parts."""
    active_resolver = resolver or resolve_image_references
    image_parts = []
    total_bytes = 0
    for reference in list(references or [])[:max(0, int(max_images or 0))]:
        screening_snapshot = _snapshot_screening_request_state()
        try:
            resolved = active_resolver(
                settings,
                user_id,
                conversation_id,
                [reference],
                VISION_REFERENCE_CAPABILITY,
            )
            sources = resolved.get("sources") if isinstance(resolved, dict) else []
            prepared = sources[0] if sources else None
            if not prepared:
                _restore_screening_request_state(screening_snapshot)
                continue
            image_bytes = prepared.get("bytes") or b""
            if total_bytes + len(image_bytes) > MAX_VISION_IMAGE_PAYLOAD_BYTES:
                # The image was read but is not sent, so it is not a source of this answer.
                _restore_screening_request_state(screening_snapshot)
                log_event(
                    "[CHAT_API] Skipped current-turn vision image because the payload budget was reached.",
                    extra={
                        "conversation_id": conversation_id,
                        "reference_id": _reference_log_id(reference),
                        "included_count": len(image_parts),
                        "payload_bytes": total_bytes,
                    },
                    level=logging.INFO,
                    debug_only=True,
                )
                break
            total_bytes += len(image_bytes)
            image_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": image_data_url(prepared),
                    "detail": "auto",
                },
            })
        except Exception as exc:
            _restore_screening_request_state(screening_snapshot)
            log_event(
                "[CHAT_API] Skipped current-turn vision image.",
                extra={
                    "conversation_id": conversation_id,
                    "reference_id": _reference_log_id(reference),
                    "included_count": len(image_parts),
                    "error_type": type(exc).__name__,
                },
                level=logging.INFO,
                debug_only=True,
            )
            continue
    return image_parts


def should_include_current_turn_images(
    *,
    image_generation_enabled,
    agent_active,
    orchestration_active,
    model,
    endpoint,
    provider_kind,
):
    """Return whether the direct chat model path should receive current-turn images."""
    if image_generation_enabled or agent_active or orchestration_active:
        return False
    normalized_provider = str(provider_kind or "").strip().lower().replace("-", "_")
    if normalized_provider not in _OPENAI_COMPATIBLE_PROVIDER_KINDS:
        return False
    try:
        return bool(is_vision_capable_model(model, endpoint))
    except Exception as exc:
        log_event(
            "[CHAT_API] Could not evaluate current-turn vision capability.",
            extra={"model": str(model or ""), "error_type": type(exc).__name__},
            level=logging.INFO,
            debug_only=True,
        )
        return False


def attach_images_to_last_user_message(messages, image_parts):
    """Return a new message list with image parts attached to the last user message."""
    if not image_parts:
        return [dict(message) if isinstance(message, dict) else message for message in (messages or [])]
    updated_messages = []
    last_user_index = -1
    for index, message in enumerate(messages or []):
        if isinstance(message, dict) and message.get("role") == "user":
            last_user_index = index
        updated_messages.append(dict(message) if isinstance(message, dict) else message)
    if last_user_index < 0:
        return updated_messages
    target = dict(updated_messages[last_user_index])
    original_content = target.get("content", "")
    if isinstance(original_content, list):
        content_parts = [*original_content, *image_parts]
    else:
        text = str(original_content or "")
        # Some providers reject an empty text block, so it is only sent when there is text.
        content_parts = [{"type": "text", "text": text}, *image_parts] if text.strip() else list(image_parts)
    target["content"] = content_parts
    updated_messages[last_user_index] = target
    return updated_messages


def vision_thought_text(count):
    """Return the user-visible thought text for current-turn vision input."""
    image_count = int(count or 0)
    if image_count == 1:
        return "Including 1 image from this message"
    return f"Including {image_count} images from this message"
