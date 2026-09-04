# functions_model_capabilities.py
"""Model capability resolution backed by the SimpleChat model capability catalog.

Capability answers resolve through a precedence chain so that a model which is not
present in the shipped catalog -- a customer's on-premises or bespoke model -- can
still be described accurately instead of being guessed at from its name:

    per-model override -> endpoint override -> catalog entry -> name heuristic

Only stdlib imports are used here on purpose. This module sits below the settings,
logging, and route layers, so pulling those in would risk import cycles.
"""

import json
import os
import re
import threading
from collections.abc import Mapping


MODEL_IDENTIFIER_SEPARATOR_PATTERN = re.compile(r"[\s_.]+")
GPT_VISION_MODEL_PATTERN = re.compile(r"(?:^|-)gpt-(?:[5-9]|\d{2,})(?:-|$)")
O_SERIES_MODEL_PATTERN = re.compile(r"(?:^|-)o\d+(?:-|$)")
REASONING_MODEL_PATTERN = re.compile(r"(?:^|-)(?:o\d+|gpt-(?:[5-9]|\d{2,}))(?:-|$)")
MODEL_IDENTIFIER_FIELDS = (
    "modelName",
    "displayName",
    "deploymentName",
    "deployment",
    "name",
)

CATALOG_RELATIVE_PATH = ("static", "json", "model_capabilities.json")

CAPABILITY_PROCESSES_IMAGES = "processesImages"
CAPABILITY_TOOL_CALLING = "toolCalling"
CAPABILITY_STRUCTURED_OUTPUT = "structuredOutput"
CAPABILITY_SUPPORTS_STREAMING = "supportsStreaming"
CAPABILITY_REASONING = "reasoning"

CAPABILITY_FIELD_NAMES = (
    "processesText",
    "generatesText",
    CAPABILITY_PROCESSES_IMAGES,
    "generatesImages",
    "processesAudio",
    "generatesAudio",
    "processesVideo",
    "generatesVideo",
    "processesBinaryFiles",
    "optimizedForCoding",
    CAPABILITY_TOOL_CALLING,
    CAPABILITY_STRUCTURED_OUTPUT,
    CAPABILITY_SUPPORTS_STREAMING,
    CAPABILITY_REASONING,
)

CATALOG_CONTEXT_LIMIT_FIELDS = ("inputTokenLimit", "contextWindow", "maxInputTokens")
CATALOG_OUTPUT_LIMIT_FIELDS = ("outputTokenLimit", "maxOutputTokens", "maxCompletionTokens")

_CATALOG_LOCK = threading.Lock()
_CATALOG_CACHE = None


def _normalize_model_identifier(value):
    return MODEL_IDENTIFIER_SEPARATOR_PATTERN.sub(
        "-",
        str(value or "").strip().lower(),
    )


def get_model_capability_catalog_path():
    """Return the absolute path of the shipped model capability catalog."""
    return os.path.join(os.path.dirname(__file__), *CATALOG_RELATIVE_PATH)


def reset_model_capability_catalog_cache():
    """Clear the cached catalog so a later read picks the file up again."""
    global _CATALOG_CACHE
    with _CATALOG_LOCK:
        _CATALOG_CACHE = None


def load_model_capability_catalog():
    """Return the parsed catalog, caching it after the first successful read."""
    global _CATALOG_CACHE
    with _CATALOG_LOCK:
        if _CATALOG_CACHE is not None:
            return _CATALOG_CACHE
        try:
            with open(get_model_capability_catalog_path(), "r", encoding="utf-8") as catalog_file:
                catalog = json.load(catalog_file)
        except (OSError, json.JSONDecodeError):
            catalog = {}
        if not isinstance(catalog, dict):
            catalog = {}
        _CATALOG_CACHE = catalog
        return _CATALOG_CACHE


def get_model_capability_catalog_records():
    """Return every model record defined by the catalog."""
    catalog = load_model_capability_catalog()
    return [record for record in catalog.get("models") or [] if isinstance(record, dict)]


def _get_record_field(record, field_name):
    if isinstance(record, Mapping):
        return record.get(field_name)
    return getattr(record, field_name, None)


def _iter_model_identifiers(model):
    """Yield every normalized identifier that could name the supplied model."""
    if model is None:
        return
    if isinstance(model, str):
        normalized = _normalize_model_identifier(model)
        if normalized:
            yield normalized
        return
    for field_name in MODEL_IDENTIFIER_FIELDS:
        normalized = _normalize_model_identifier(_get_record_field(model, field_name))
        if normalized:
            yield normalized


def _iter_catalog_record_identifiers(record):
    """Yield every normalized identifier a catalog record answers to.

    "family" is deliberately excluded. It is a grouping attribute rather than an
    identifier, and members of one family disagree on capabilities -- "phi-4"
    covers both the multimodal and the text-only Phi models, and the "gpt-5.x"
    families each contain a non-vision "-chat" member. Matching on it would let a
    model inherit a sibling's capabilities.
    """
    for field_name in ("id", "displayName"):
        normalized = _normalize_model_identifier(record.get(field_name))
        if normalized:
            yield normalized
    aliases = record.get("aliases")
    if isinstance(aliases, (list, tuple)):
        for alias in aliases:
            normalized = _normalize_model_identifier(alias)
            if normalized:
                yield normalized


def _is_variant_suffix_match(requested_identifier, record_identifier):
    """Return whether requested is a variant of record rather than a later version.

    Identifier normalization collapses "." and "-" to the same separator, so
    "gpt-5.3" becomes "gpt-5-3" and would otherwise look like a suffixed variant of
    "gpt-5". A remainder that starts with a digit is a version continuation, not a
    variant, so it is rejected. A remainder starting with a letter -- the "eastus"
    in "gpt-5.6-sol-eastus", or the "mini" in "gpt-4o-mini" -- is a real variant.
    """
    prefix = f"{record_identifier}-"
    if not requested_identifier.startswith(prefix):
        return False
    remainder = requested_identifier[len(prefix):]
    return bool(remainder) and not remainder[0].isdigit()


def find_model_catalog_record(model):
    """Return the catalog record naming this model, or None when it is unknown.

    An exact identifier match always wins. Otherwise the longest matching
    identifier prefix wins, so a deployment named "gpt-5.6-sol-eastus" resolves to
    "gpt-5.6-sol", and "gpt-5.1-chat-v2" resolves to "gpt-5.1-chat" rather than to
    the shorter, and differently capable, "gpt-5.1".
    """
    requested_identifiers = list(_iter_model_identifiers(model))
    if not requested_identifiers:
        return None

    requested_identifier_set = set(requested_identifiers)
    best_prefix_match = None
    best_prefix_length = 0
    for record in get_model_capability_catalog_records():
        record_identifiers = list(_iter_catalog_record_identifiers(record))
        if requested_identifier_set.intersection(record_identifiers):
            return record
        for record_identifier in record_identifiers:
            if len(record_identifier) <= best_prefix_length:
                continue
            for requested_identifier in requested_identifiers:
                if _is_variant_suffix_match(requested_identifier, record_identifier):
                    best_prefix_match = record
                    best_prefix_length = len(record_identifier)
                    break
    return best_prefix_match


def _read_declared_capabilities(source):
    """Return the explicit capability map declared on a model or endpoint record."""
    if source is None:
        return {}
    capabilities = _get_record_field(source, "capabilities")
    if not isinstance(capabilities, Mapping):
        return {}
    declared = {}
    for capability_name, capability_value in capabilities.items():
        if isinstance(capability_value, bool):
            declared[str(capability_name)] = capability_value
    return declared


def _heuristic_capability(capability_name, model):
    """Return the legacy name-based answer for the capabilities that have one."""
    if capability_name == CAPABILITY_PROCESSES_IMAGES:
        return _heuristic_is_vision_capable(model)
    if capability_name == CAPABILITY_REASONING:
        return _heuristic_is_reasoning_model(model)
    return None


def _heuristic_is_vision_capable(model):
    for normalized_name in _iter_model_identifiers(model):
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


def _heuristic_is_reasoning_model(model):
    for normalized_name in _iter_model_identifiers(model):
        if REASONING_MODEL_PATTERN.search(normalized_name) or "gpt-5" in normalized_name:
            return True
    return False


def resolve_model_capability(capability_name, model=None, endpoint=None, default=None):
    """Resolve one capability through the override, catalog, then heuristic chain."""
    declared_model_capabilities = _read_declared_capabilities(model)
    if capability_name in declared_model_capabilities:
        return declared_model_capabilities[capability_name]

    declared_endpoint_capabilities = _read_declared_capabilities(endpoint)
    if capability_name in declared_endpoint_capabilities:
        return declared_endpoint_capabilities[capability_name]

    catalog_record = find_model_catalog_record(model)
    if catalog_record is not None:
        catalog_capabilities = catalog_record.get("capabilities")
        if isinstance(catalog_capabilities, Mapping):
            catalog_value = catalog_capabilities.get(capability_name)
            if isinstance(catalog_value, bool):
                return catalog_value

    heuristic_value = _heuristic_capability(capability_name, model)
    if heuristic_value is not None:
        return heuristic_value
    return default


def resolve_model_capabilities(model=None, endpoint=None):
    """Return every known capability for a model as a name to boolean-or-None map."""
    return {
        capability_name: resolve_model_capability(capability_name, model, endpoint)
        for capability_name in CAPABILITY_FIELD_NAMES
    }


def _read_token_limit(record, field_names):
    for field_name in field_names:
        value = _get_record_field(record, field_name)
        try:
            normalized_value = int(value)
        except (TypeError, ValueError):
            continue
        if normalized_value > 0:
            return normalized_value
    return None


def resolve_model_token_limits(model=None, endpoint=None):
    """Return the (context, output) token limits for a model, or None when unknown."""
    for source in (model, endpoint):
        if source is None or isinstance(source, str):
            continue
        context_limit = _read_token_limit(source, CATALOG_CONTEXT_LIMIT_FIELDS)
        output_limit = _read_token_limit(source, CATALOG_OUTPUT_LIMIT_FIELDS)
        if context_limit or output_limit:
            return context_limit, output_limit

    catalog_record = find_model_catalog_record(model)
    if catalog_record is None:
        return None, None
    return (
        _read_token_limit(catalog_record, CATALOG_CONTEXT_LIMIT_FIELDS),
        _read_token_limit(catalog_record, CATALOG_OUTPUT_LIMIT_FIELDS),
    )


def resolve_model_output_token_limit(model=None, endpoint=None, default=None):
    """Return the output token limit for a model, falling back to the supplied default."""
    _, output_limit = resolve_model_token_limits(model, endpoint)
    return output_limit or default


def is_vision_capable_model_name(*model_names):
    """Return whether any supplied identifier names a supported vision model."""
    for model_name in model_names:
        if model_name in (None, ""):
            continue
        if resolve_model_capability(CAPABILITY_PROCESSES_IMAGES, model_name, default=False):
            return True

    return False


def is_vision_capable_model(model, endpoint=None):
    """Return whether a model record or identifier names a supported vision model."""
    return bool(
        resolve_model_capability(
            CAPABILITY_PROCESSES_IMAGES,
            model,
            endpoint,
            default=False,
        )
    )


def is_reasoning_model(model, endpoint=None):
    """Return whether a model uses reasoning-style response length parameters."""
    return bool(
        resolve_model_capability(
            CAPABILITY_REASONING,
            model,
            endpoint,
            default=False,
        )
    )


def supports_streaming(model=None, endpoint=None):
    """Return whether a model can stream. Unknown models are assumed to stream."""
    return bool(
        resolve_model_capability(
            CAPABILITY_SUPPORTS_STREAMING,
            model,
            endpoint,
            default=True,
        )
    )


def supports_tool_calling(model=None, endpoint=None, default=True):
    """Return whether a model supports tool or function calling."""
    return bool(
        resolve_model_capability(
            CAPABILITY_TOOL_CALLING,
            model,
            endpoint,
            default=default,
        )
    )
