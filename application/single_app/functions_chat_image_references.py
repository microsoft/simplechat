# functions_chat_image_references.py
"""Chat request helpers for direct Image-mode reference images."""

from functions_image_edit import compose_edit_prompt, normalize_mask
from functions_image_references import (
    ImageReferenceError,
    effective_max_reference_images,
    parse_image_references,
    reference_prompt,
    resolve_image_references,
)


MAX_MASK_REGIONS = 999


def _empty_prepared_references():
    return {
        "sources": [],
        "provenance": [],
        "mask": None,
        "mask_metadata": None,
        "input_fidelity": "",
    }


def _bounded_mask_regions(value):
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        raise ImageReferenceError(
            "The selected region count is invalid.",
            "invalid_image_mask",
            400,
        )
    try:
        regions = int(value)
    except (TypeError, ValueError) as exc:
        raise ImageReferenceError(
            "The selected region count is invalid.",
            "invalid_image_mask",
            400,
        ) from exc
    return max(0, min(regions, MAX_MASK_REGIONS))


def read_chat_image_reference_request(data):
    """Read direct Image-mode reference fields from a chat request body."""
    request_data = data if isinstance(data, dict) else {}
    image_mask = request_data.get("image_mask")
    if image_mask is not None and not isinstance(image_mask, str):
        raise ImageReferenceError(
            "The selected region must be an encoded PNG mask.",
            "invalid_image_mask",
            400,
        )
    return {
        "raw_references": request_data.get("image_references"),
        "image_mask": image_mask,
        "mask_regions": _bounded_mask_regions(request_data.get("image_mask_regions")),
        "image_mask_dropped": bool(request_data.get("image_mask_dropped")),
    }


def _validate_capability_for_references(capability, reference_count):
    effective_limit = effective_max_reference_images(capability)
    if (
        not isinstance(capability, dict)
        or capability.get("enabled") is False
        or not capability.get("editing")
        or effective_limit <= 0
    ):
        message = str(
            (capability or {}).get("reason")
            or "The selected image model cannot use reference images."
        ).strip()
        raise ImageReferenceError(message, "unsupported_image_operation", 400)
    if reference_count > effective_limit:
        raise ImageReferenceError(
            f"The selected image model accepts at most {effective_limit} reference image"
            f"{'s' if effective_limit != 1 else ''}.",
            "too_many_reference_images",
            400,
        )
    return effective_limit


def _validate_mask_rules(image_mask, reference_count, capability):
    if not image_mask:
        return
    if reference_count != 1:
        raise ImageReferenceError(
            "A selected region can only be used with one reference image.",
            "unsupported_image_operation",
            400,
        )
    if not (isinstance(capability, dict) and capability.get("masking")):
        raise ImageReferenceError(
            "The selected image model cannot edit a selected region. Clear the selection and try again.",
            "unsupported_image_operation",
            400,
        )


def prepare_chat_image_references(
    settings,
    user_id,
    conversation_id,
    raw_references,
    image_mask,
    mask_regions,
    *,
    capability=None,
    message_reader=None,
    document_reader=None,
    image_loader=None,
):
    """Prepare direct Image-mode reference sources and optional mask metadata."""
    if raw_references in (None, ""):
        if image_mask:
            raise ImageReferenceError(
                "A selected region can only be used with one reference image.",
                "unsupported_image_operation",
                400,
            )
        return _empty_prepared_references()

    parsed_references = parse_image_references(raw_references)
    if not parsed_references:
        if image_mask:
            raise ImageReferenceError(
                "A selected region can only be used with one reference image.",
                "unsupported_image_operation",
                400,
            )
        return _empty_prepared_references()

    active_capability = capability
    if active_capability is None:
        from functions_image_edit import resolve_image_edit_capability

        active_capability = resolve_image_edit_capability(settings)

    _validate_capability_for_references(active_capability, len(parsed_references))
    _validate_mask_rules(image_mask, len(parsed_references), active_capability)

    resolved = resolve_image_references(
        settings,
        user_id,
        conversation_id,
        parsed_references,
        active_capability,
        message_reader=message_reader,
        document_reader=document_reader,
        image_loader=image_loader,
    )
    sources = list(resolved.get("sources") or [])
    provenance = list(resolved.get("provenance") or [])

    mask = None
    mask_metadata = None
    if image_mask and sources:
        source = sources[0]
        max_mask_bytes = active_capability.get("max_mask_bytes")
        mask_kwargs = {"regions": mask_regions}
        if max_mask_bytes:
            mask_kwargs["max_bytes"] = max_mask_bytes
        mask = normalize_mask(
            image_mask,
            source.get("width"),
            source.get("height"),
            **mask_kwargs,
        )
        if mask:
            mask_metadata = {
                "coverage": mask.get("coverage"),
                "regions": mask.get("regions"),
            }

    return {
        "sources": sources,
        "provenance": provenance,
        "mask": mask,
        "mask_metadata": mask_metadata,
        "input_fidelity": "high" if active_capability.get("input_fidelity") else "",
    }


def compose_chat_reference_prompt(instruction, reference_count, mask):
    """Return the prompt used when direct Image mode has reference images."""
    if mask and int(reference_count or 0) == 1:
        return compose_edit_prompt("", instruction, mask)
    return reference_prompt(instruction, reference_count)


def chat_reference_thoughts(data):
    """Return streaming compatibility thoughts for direct Image-mode reference requests."""
    request_data = data if isinstance(data, dict) else {}
    if not request_data.get("image_generation"):
        return []
    references = request_data.get("image_references")
    if not isinstance(references, list) or not references:
        return []

    reference_count = min(len(references), 10)
    noun = "reference image" if reference_count == 1 else "reference images"
    thoughts = [f"Using {reference_count} {noun}"]
    if request_data.get("image_mask"):
        thoughts.append("Editing the selected region of the reference image")
    if request_data.get("image_mask_dropped"):
        thoughts.append("The original selection mask isn't saved, so this retry edits the whole image")
    return thoughts
