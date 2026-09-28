# functions_image_references.py

"""Resolve authorized chat and workspace images into model-ready references.

This module stays importable without application configuration. Runtime dependencies that may
initialize Azure clients, Flask, or Cosmos containers are imported only inside the functions that
need them.
"""

import ntpath
import re
from importlib import import_module

from functions_image_api_route import ImageGenerationError
from functions_image_formats import (
    HEIF_REFERENCE_MESSAGE,
    MODEL_IMAGE_MAX_EDGE,
    ImageFormatError,
    detect_image_format,
    is_heif_file_name,
    is_image_file_name,
    normalize_model_image,
)


MAX_APP_REFERENCE_IMAGES = 10
MAX_REFERENCE_PAYLOAD_BYTES = 50 * 1024 * 1024

_REFERENCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
_SCOPES = frozenset({"personal", "group", "public"})


class ImageReferenceError(ImageGenerationError):
    """Safe image-reference failure with a stable error code and HTTP status."""


def _reference_error(message, code="invalid_image_references", status_code=400):
    raise ImageReferenceError(message, code, status_code)


def _clean_id(value, field_name):
    if not isinstance(value, str):
        _reference_error(f"The image reference {field_name} is invalid.")
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 256 or not _REFERENCE_ID_PATTERN.fullmatch(normalized):
        _reference_error(f"The image reference {field_name} is invalid.")
    return normalized


def parse_image_references(raw, *, max_count=MAX_APP_REFERENCE_IMAGES):
    """Validate and normalize a reference-image request body."""
    if not isinstance(raw, list):
        _reference_error("Image references must be a list.")
    try:
        limit = max(0, int(max_count))
    except (TypeError, ValueError):
        limit = MAX_APP_REFERENCE_IMAGES

    parsed = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            _reference_error("Each image reference must be an object.")
        reference_type = str(item.get("type") or "").strip().lower()
        if reference_type == "message":
            message_id = _clean_id(item.get("message_id"), "message_id")
            key = ("message", message_id)
            normalized = {"type": "message", "message_id": message_id}
        elif reference_type == "document":
            document_id = _clean_id(item.get("document_id"), "document_id")
            scope = str(item.get("scope") or "").strip().lower()
            if scope not in _SCOPES:
                _reference_error("The document reference scope is invalid.")
            scope_id = None
            if scope in ("group", "public"):
                scope_id = _clean_id(item.get("scope_id"), "scope_id")
            key = ("document", document_id, scope, scope_id)
            normalized = {
                "type": "document",
                "document_id": document_id,
                "scope": scope,
                "scope_id": scope_id,
            }
        else:
            _reference_error("The image reference type is invalid.")
        if key in seen:
            continue
        seen.add(key)
        parsed.append(normalized)
        if len(parsed) > limit:
            _reference_error(
                f"You can attach at most {limit} reference image{'s' if limit != 1 else ''}.",
                "too_many_reference_images",
                400,
            )
    return parsed


def effective_max_reference_images(capability):
    """Return the application-bounded reference limit for an image-edit capability."""
    if not isinstance(capability, dict) or not capability.get("editing"):
        return 0
    try:
        limit = int(capability.get("max_reference_images") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(MAX_APP_REFERENCE_IMAGES, limit))


def _setting_enabled(settings, key):
    if not isinstance(settings, dict):
        return False
    if key in settings:
        return bool(settings.get(key))
    nested = settings.get("settings")
    return bool(nested.get(key)) if isinstance(nested, dict) else False


def _scope_enabled(settings, scope):
    keys = {
        "personal": "enable_user_workspace",
        "group": "enable_group_workspaces",
        "public": "enable_public_workspaces",
    }
    return _setting_enabled(settings, keys[scope])


def _not_found():
    _reference_error(
        "The reference image could not be found or is no longer available.",
        "image_reference_not_found",
        404,
    )


def _unsupported_format(message="Only images can be used as reference images."):
    _reference_error(message, "unsupported_reference_format", 415)


def _is_not_found_error(error):
    return (
        isinstance(error, (LookupError, KeyError))
        or type(error).__name__ == "CosmosResourceNotFoundError"
        or getattr(error, "status_code", None) == 404
    )


def _screening_details(error):
    try:
        contracts = import_module("content_screening.contracts")
    except Exception:
        return None
    if not isinstance(error, getattr(contracts, "ScreeningError")):
        return None
    return {
        "message": getattr(error, "public_message", "Content screening could not complete."),
        "code": getattr(error, "code", "screening_error"),
        "status_code": getattr(error, "status_code", 503),
    }


def _map_reader_error(error):
    screening = _screening_details(error)
    if screening:
        _reference_error(screening["message"], screening["code"], screening["status_code"])
    if isinstance(error, PermissionError) or _is_not_found_error(error):
        _not_found()
    raise error


def _default_message_reader(conversation_id, message_id):
    config = import_module("config")
    messages = import_module("functions_image_messages")
    return messages.get_complete_image_content(
        config.cosmos_messages_container,
        conversation_id,
        message_id,
    )


def personal_document_metadata_reader(
    document_id, user_id, group_id=None, public_workspace_id=None, *, metadata_only=False,
):
    """Read a personal reference from the personal container only.

    Without a scope hint the screening reader also searches group and public containers,
    which would let a ``personal`` reference bypass the per-scope workspace feature flags.
    Pass it as ``metadata_reader`` to ``read_available_document_bytes``.
    """
    access = import_module("content_screening.access")
    return access._read_authorized_document(
        document_id,
        user_id,
        group_id,
        public_workspace_id,
        metadata_only=metadata_only,
        scope_type="personal" if group_id is None and public_workspace_id is None else None,
    )


def _default_document_reader(
    document_id, user_id, *, group_id=None, public_workspace_id=None, purpose="model", personal_only=False,
):
    access = import_module("content_screening.access")
    return access.read_available_document_bytes(
        document_id,
        user_id,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
        purpose=purpose,
        metadata_reader=personal_document_metadata_reader if personal_only else None,
    )


def _default_image_loader(message_doc, complete_content):
    editor = import_module("functions_image_edit")
    return editor.load_current_image_bytes(message_doc, complete_content)


def _message_file_name(message_doc):
    metadata = message_doc.get("metadata") if isinstance(message_doc.get("metadata"), dict) else {}
    for key in ("file_name", "filename", "name"):
        if message_doc.get(key):
            return message_doc.get(key)
    for key in ("file_name", "filename", "original_file_name", "upload_file_name"):
        if metadata.get(key):
            return metadata.get(key)
    return ""


def _document_file_name(document):
    if not isinstance(document, dict):
        return ""
    return document.get("file_name") or document.get("filename") or document.get("name") or ""


def _workspace_document_id(message_doc):
    metadata = message_doc.get("metadata") if isinstance(message_doc.get("metadata"), dict) else {}
    return str(message_doc.get("workspace_document_id") or metadata.get("workspace_document_id") or "").strip()


def _safe_file_name(file_name, fallback="reference-image"):
    base_name = ntpath.basename(str(file_name or "").replace("/", "\\")).strip()
    if not base_name:
        base_name = fallback
    return base_name[:255]


def _check_heif(file_name, image_bytes):
    if is_heif_file_name(file_name) or detect_image_format(image_bytes) in ("image/heic", "image/heif"):
        _unsupported_format(HEIF_REFERENCE_MESSAGE)


def _read_message_reference(reference, conversation_id, user_id, message_reader, document_reader, image_loader):
    message_id = reference["message_id"]
    if not message_id.startswith(f"{conversation_id}_"):
        _not_found()
    try:
        message_doc, complete_content = message_reader(conversation_id, message_id)
    except Exception as error:
        _map_reader_error(error)
    if str(message_doc.get("conversation_id") or "") != str(conversation_id):
        _not_found()

    role = str(message_doc.get("role") or "").strip().lower()
    if role == "image":
        try:
            _mime_type, image_bytes = image_loader(message_doc, complete_content)
        except Exception as error:
            _map_reader_error(error)
        file_name = _message_file_name(message_doc) or "image.png"
        return image_bytes, {
            "type": "message",
            "message_id": message_id,
            "scope": None,
            "scope_id": None,
            "file_name": _safe_file_name(file_name, "image.png"),
        }

    if role != "file":
        _unsupported_format()
    document_id = _workspace_document_id(message_doc)
    if not document_id:
        _unsupported_format()
    try:
        document, image_bytes = document_reader(document_id, user_id, purpose="model")
    except Exception as error:
        _map_reader_error(error)
    message_file_name = _message_file_name(message_doc)
    document_file_name = _document_file_name(document)
    if not is_image_file_name(message_file_name) and not is_image_file_name(document_file_name):
        _unsupported_format()
    file_name = message_file_name if is_image_file_name(message_file_name) else document_file_name
    _check_heif(file_name, image_bytes)
    return image_bytes, {
        "type": "message",
        "message_id": message_id,
        "scope": None,
        "scope_id": None,
        "file_name": _safe_file_name(file_name),
    }


def _read_document_reference(reference, settings, user_id, document_reader):
    scope = reference["scope"]
    if not _scope_enabled(settings, scope):
        _not_found()
    kwargs = {"purpose": "model"}
    if scope == "group":
        kwargs["group_id"] = reference["scope_id"]
    elif scope == "public":
        kwargs["public_workspace_id"] = reference["scope_id"]
    else:
        kwargs["personal_only"] = True
    try:
        document, image_bytes = document_reader(reference["document_id"], user_id, **kwargs)
    except Exception as error:
        _map_reader_error(error)
    if scope == "personal" and isinstance(document, dict) and (
        document.get("group_id") or document.get("public_workspace_id")
    ):
        _not_found()
    file_name = _document_file_name(document)
    if not is_image_file_name(file_name):
        _unsupported_format()
    _check_heif(file_name, image_bytes)
    return image_bytes, {
        "type": "document",
        "document_id": reference["document_id"],
        "scope": scope,
        "scope_id": reference.get("scope_id"),
        "file_name": _safe_file_name(file_name),
    }


def _normalize_references(originals, capability, max_edge):
    prepared = []
    allowed_formats = capability.get("input_formats") or None
    for index, item in enumerate(originals):
        try:
            prepared.append(
                normalize_model_image(
                    item["bytes"],
                    allowed_formats=allowed_formats,
                    max_edge=max_edge,
                    file_stem=f"reference-{index + 1}",
                )
            )
        except ImageFormatError as error:
            _reference_error(error.public_message, error.code, error.status_code)
    return prepared


def _log_resolution(references, prepared):
    try:
        log_event = import_module("functions_appinsights").log_event
        log_event(
            "[IMAGE_REFERENCES] Resolved image references.",
            extra={
                "reference_count": len(references),
                "source_count": len(prepared),
                "reference_types": [reference.get("type") for reference in references],
                "reference_ids": [
                    reference.get("message_id") or reference.get("document_id")
                    for reference in references
                ],
            },
            debug_only=True,
        )
    except Exception:
        pass


def resolve_image_references(
    settings,
    user_id,
    conversation_id,
    references,
    capability,
    *,
    message_reader=None,
    document_reader=None,
    image_loader=None,
):
    """Authorize, screen, normalize, and return model-ready image references."""
    normalized_references = parse_image_references(references or [])
    if not normalized_references:
        return {"sources": [], "provenance": []}

    effective_limit = effective_max_reference_images(capability)
    if not isinstance(capability, dict) or capability.get("enabled") is False or not capability.get("editing") or effective_limit <= 0:
        reason = str((capability or {}).get("reason") or "The selected image model cannot use reference images.").strip()
        _reference_error(reason, "unsupported_image_operation", 400)
    if len(normalized_references) > effective_limit:
        _reference_error(
            f"The selected image model accepts at most {effective_limit} reference image"
            f"{'s' if effective_limit != 1 else ''}.",
            "too_many_reference_images",
            400,
        )

    active_message_reader = message_reader or _default_message_reader
    active_document_reader = document_reader or _default_document_reader
    active_image_loader = image_loader or _default_image_loader

    originals = []
    for reference in normalized_references:
        if reference["type"] == "message":
            image_bytes, provenance = _read_message_reference(
                reference,
                conversation_id,
                user_id,
                active_message_reader,
                active_document_reader,
                active_image_loader,
            )
        else:
            image_bytes, provenance = _read_document_reference(
                reference,
                settings,
                user_id,
                active_document_reader,
            )
        _check_heif(provenance["file_name"], image_bytes)
        originals.append({"bytes": image_bytes, "provenance": provenance})

    prepared = _normalize_references(originals, capability, MODEL_IMAGE_MAX_EDGE)
    if sum(len(source["bytes"]) for source in prepared) > MAX_REFERENCE_PAYLOAD_BYTES:
        prepared = _normalize_references(originals, capability, 1536)
    if sum(len(source["bytes"]) for source in prepared) > MAX_REFERENCE_PAYLOAD_BYTES:
        prepared = _normalize_references(originals, capability, 1024)
    if sum(len(source["bytes"]) for source in prepared) > MAX_REFERENCE_PAYLOAD_BYTES:
        _reference_error("The reference images are too large to send together.", "image_too_large", 413)

    provenance_items = []
    for item, source in zip(originals, prepared):
        provenance = dict(item["provenance"])
        provenance["width"] = source.get("width")
        provenance["height"] = source.get("height")
        provenance_items.append(provenance)

    _log_resolution(normalized_references, prepared)
    return {"sources": prepared, "provenance": provenance_items}


def references_from_metadata(metadata):
    """Return parse-able references reconstructed from stored provenance metadata."""
    if not isinstance(metadata, dict):
        return []
    raw_items = metadata.get("image_references")
    if not isinstance(raw_items, list):
        return []
    rebuilt = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message" and item.get("message_id"):
            rebuilt.append({"type": "message", "message_id": item.get("message_id")})
        elif item.get("type") == "document" and item.get("document_id"):
            rebuilt.append({
                "type": "document",
                "document_id": item.get("document_id"),
                "scope": item.get("scope") or "personal",
                "scope_id": item.get("scope_id"),
            })
    try:
        return parse_image_references(rebuilt)
    except ImageReferenceError:
        return []


def reference_prompt(instruction, count):
    """Return a deterministic prompt that tells the model how to use references."""
    clean_instruction = " ".join(str(instruction or "").split())
    try:
        reference_count = max(0, int(count or 0))
    except (TypeError, ValueError):
        reference_count = 0
    if reference_count <= 0:
        return clean_instruction
    if reference_count == 1:
        prefix = "Use the attached reference image as the visual basis."
    else:
        prefix = (
            f"Use the {reference_count} attached reference images, numbered image 1 through "
            f"image {reference_count} in the order given, as visual references."
        )
    return f"{prefix} {clean_instruction}".strip()
