# functions_model_capabilities.py
"""Decide whether a model can accept image input.

Multi-Modal Vision Analysis sends page images to a model, so it can only offer
models that actually read them. Working that out used to be a regular expression
over the model's name: anything containing "vision" or "gpt-4o", or matching
``gpt-[5-9]`` or ``o<digits>``, was assumed to see.

That guess is wrong in both directions. It admits ``gpt-5.3-chat``, which is a
text-only chat variant, and it has nothing to say about a model whose name does
not follow an OpenAI convention -- a self-hosted or on-premises deployment is
simply invisible to it. An administrator could correct neither case, because the
rule lived in the code.

``static/json/model_capabilities.json`` has shipped in this repository for some
time carrying real per-model capability data, including ``processesImages``, and
nothing read it. It does now, in three tiers:

1. **An explicit flag on the model record.** ``supportsVision`` on a model inside
   a ``model_endpoints`` entry. The Model Endpoints editor pre-fills this from
   the catalog when models are fetched, so the common case needs no work, and an
   administrator can correct it for a deployment the catalog does not know.

2. **The catalog.** Matched on model id and declared aliases, which is what lets
   a deployment named after a known model resolve without anyone saying so.

3. **The name heuristic.** Kept for a model in neither of the above, because
   refusing to guess at all would hide working models from an existing
   deployment. Reported as inferred rather than known, so a caller can say so.
"""

import json
import os
import re
import threading
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

# Fields an explicit administrator decision may be recorded under. The camelCase
# spelling is what the Model Endpoints editor writes; the snake_case one is
# accepted so a settings document edited by hand still resolves.
VISION_OVERRIDE_FIELDS = ("supportsVision", "supports_vision")

CATALOG_FILENAME = os.path.join("static", "json", "model_capabilities.json")

# How a decision was reached, most authoritative first.
VISION_SOURCE_DECLARED = "declared"
VISION_SOURCE_CATALOG = "catalog"
VISION_SOURCE_INFERRED = "inferred"

_CATALOG_LOCK = threading.Lock()
_CATALOG_CACHE = None


def _normalize_model_identifier(value):
    return MODEL_IDENTIFIER_SEPARATOR_PATTERN.sub(
        "-",
        str(value or "").strip().lower(),
    )


def load_model_capability_catalog(force_refresh=False):
    """Return ``{normalized identifier: capabilities}`` from the shipped catalog.

    Read once and cached. The file is part of the deployment rather than
    configuration, so re-reading it per lookup would cost disk access on a path
    that runs for every model in every dropdown.

    A missing or malformed catalog yields an empty mapping rather than raising.
    That degrades this to the name heuristic, which is what the application did
    before the catalog was consulted at all.
    """
    global _CATALOG_CACHE

    if _CATALOG_CACHE is not None and not force_refresh:
        return _CATALOG_CACHE

    with _CATALOG_LOCK:
        if _CATALOG_CACHE is not None and not force_refresh:
            return _CATALOG_CACHE

        catalog = {}
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CATALOG_FILENAME)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                document = json.load(handle)

            for model in document.get("models", []):
                if not isinstance(model, Mapping):
                    continue
                capabilities = model.get("capabilities")
                if not isinstance(capabilities, Mapping):
                    continue

                for identifier in [model.get("id")] + list(model.get("aliases") or []):
                    normalized = _normalize_model_identifier(identifier)
                    if normalized:
                        catalog[normalized] = capabilities
        except Exception:
            catalog = {}

        _CATALOG_CACHE = catalog
        return _CATALOG_CACHE


def _catalog_lookup(identifier):
    """Return catalog capabilities for one identifier, or None.

    A deployment is usually named after the model it serves, but not exactly:
    "gpt-4o-prod", "gpt-4o-2024-11-20". An exact match is tried first, then the
    longest catalog identifier the name starts with, so "gpt-4o-2024-11-20"
    resolves to "gpt-4o" rather than being swallowed by a shorter entry.
    """
    normalized = _normalize_model_identifier(identifier)
    if not normalized:
        return None

    catalog = load_model_capability_catalog()
    if normalized in catalog:
        return catalog[normalized]

    best = None
    best_length = 0
    for candidate, capabilities in catalog.items():
        if len(candidate) > best_length and normalized.startswith(f"{candidate}-"):
            best = capabilities
            best_length = len(candidate)
    return best


def _model_identifiers(model):
    """Return the names a model record might be known by."""
    if isinstance(model, str):
        return [model]
    if isinstance(model, Mapping):
        return [model.get(field) for field in MODEL_IDENTIFIER_FIELDS]
    return [getattr(model, field, None) for field in MODEL_IDENTIFIER_FIELDS]


def _declared_vision_support(model):
    """Return an administrator's explicit decision, or None if none was made."""
    if isinstance(model, str):
        return None

    for field in VISION_OVERRIDE_FIELDS:
        if isinstance(model, Mapping):
            value = model.get(field)
        else:
            value = getattr(model, field, None)

        if isinstance(value, bool):
            return value
        # A stored document may hold the form-shaped string instead.
        if isinstance(value, str) and value.strip():
            return value.strip().lower() in ("true", "on", "yes", "1")
    return None


def resolve_model_vision_support(model):
    """Return ``(supports_vision, source)`` for a model record or identifier.

    ``source`` is one of ``declared``, ``catalog`` or ``inferred``, so a caller
    can tell an administrator whether the answer is known or guessed. That
    matters in the Model Endpoints editor, where a guessed value is exactly the
    one worth reviewing.
    """
    declared = _declared_vision_support(model)
    if declared is not None:
        return declared, VISION_SOURCE_DECLARED

    identifiers = _model_identifiers(model)
    for identifier in identifiers:
        capabilities = _catalog_lookup(identifier)
        if capabilities is not None:
            return bool(capabilities.get("processesImages")), VISION_SOURCE_CATALOG

    return is_vision_capable_model_name(*identifiers), VISION_SOURCE_INFERRED


def is_vision_capable_model_name(*model_names):
    """Return whether any supplied identifier names a supported vision model.

    The name heuristic on its own. Kept as the last resort in
    ``resolve_model_vision_support`` and still exported, because a caller holding
    only a deployment string has nothing better to go on.
    """
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
    """Return whether a model record or identifier can accept image input."""
    supports_vision, _source = resolve_model_vision_support(model)
    return supports_vision
