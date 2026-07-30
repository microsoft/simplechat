# functions_model_capabilities.py

import re
from collections.abc import Mapping


MODEL_IDENTIFIER_SEPARATOR_PATTERN = re.compile(r"[\s_.]+")
GPT_VISION_MODEL_PATTERN = re.compile(r"(?:^|-)gpt-(?:[5-9]|\d{2,})(?:-|$)")
O_SERIES_MODEL_PATTERN = re.compile(r"(?:^|-)o\d+(?:-|$)")
MODEL_IDENTIFIER_FIELDS = (
    "modelName",
    "displayName",
    "deploymentName",
    "deployment",
    "name",
)


def _normalize_model_identifier(value):
    return MODEL_IDENTIFIER_SEPARATOR_PATTERN.sub(
        "-",
        str(value or "").strip().lower(),
    )


def is_vision_capable_model_name(*model_names):
    """Return whether any supplied identifier names a supported vision model."""
    for model_name in model_names:
        normalized_name = _normalize_model_identifier(model_name)
        if (
            "vision" in normalized_name
            or "gpt-4o" in normalized_name
            or "gpt-4-1" in normalized_name
            or "gpt-4-5" in normalized_name
            or GPT_VISION_MODEL_PATTERN.search(normalized_name)
            or O_SERIES_MODEL_PATTERN.search(normalized_name)
        ):
            return True

    return False


def is_vision_capable_model(model):
    """Return whether a model record or identifier names a supported vision model."""
    if isinstance(model, str):
        return is_vision_capable_model_name(model)

    if isinstance(model, Mapping):
        model_names = [model.get(field_name) for field_name in MODEL_IDENTIFIER_FIELDS]
    else:
        model_names = [getattr(model, field_name, None) for field_name in MODEL_IDENTIFIER_FIELDS]

    return is_vision_capable_model_name(*model_names)