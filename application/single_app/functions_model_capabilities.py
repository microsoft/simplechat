# functions_model_capabilities.py
"""Resolve catalog-backed model capabilities, reasoning effort, and token limits.

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

Token limits deliberately do not use that heuristic. Only exact catalog
identities, declared snapshots, and authorized deployment constraints establish
capacity; unknown limits stay unknown.
"""

import copy
import json
import os
import re
import threading
from collections.abc import Mapping
from datetime import date


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
REASONING_IDENTIFIER_FIELDS = ("modelName", "behavior_name", "deploymentName", "deployment")
REASONING_EFFORTS = frozenset(("none", "minimal", "low", "medium", "high", "xhigh"))
TOKEN_LIMIT_IDENTIFIER_FIELDS = (
    "modelName", "behavior_name", "model_name", "model",
    "deploymentName", "deployment_name", "model_deployment", "deployment", "name",
)
TOKEN_LIMIT_FIELDS = {
    "context_window_tokens": (
        "contextWindow", "context_window", "context_window_tokens",
        "maxContextTokens", "max_context_tokens", "contextLength", "context_length",
    ),
    "max_input_tokens": (
        "maxInputTokens", "max_input_tokens", "inputTokenLimit", "input_token_limit",
    ),
    "max_output_tokens": (
        "maxOutputTokens", "max_output_tokens", "outputTokenLimit", "output_token_limit",
        "responseLength", "response_length", "maxCompletionTokens", "max_completion_tokens",
        "maxTokens", "max_tokens",
    ),
}
TOKEN_LIMIT_CONTAINER_FIELDS = ("tokenLimits", "token_limits", "limits")

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
_IMAGE_OPERATION_PROFILES = {}


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
    Vision keeps its legacy heuristic; reasoning support remains unknown.
    """
    global _CATALOG_CACHE, _IMAGE_OPERATION_PROFILES

    if _CATALOG_CACHE is not None and not force_refresh:
        return _CATALOG_CACHE

    with _CATALOG_LOCK:
        if _CATALOG_CACHE is not None and not force_refresh:
            return _CATALOG_CACHE

        catalog = {}
        image_profiles = {}
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CATALOG_FILENAME)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                document = json.load(handle)

            image_profiles = document.get("imageOperationProfiles") or {}
            if not isinstance(image_profiles, Mapping):
                raise ValueError("Image operation profiles must be an object.")
            for model in document.get("models", []):
                if not isinstance(model, Mapping):
                    continue
                capabilities = model.get("capabilities") or {}
                if not isinstance(capabilities, Mapping):
                    continue
                capabilities = dict(capabilities)
                if isinstance(model.get("reasoningPolicy"), Mapping):
                    capabilities["reasoningPolicy"] = model["reasoningPolicy"]
                if isinstance(model.get("tokenLimits"), Mapping):
                    capabilities["tokenLimits"] = model["tokenLimits"]
                if "embeddingPolicy" in model:
                    capabilities["embeddingPolicy"] = copy.deepcopy(model["embeddingPolicy"])
                for field_name in ("imageProfiles", "imageLifecycle"):
                    if isinstance(model.get(field_name), Mapping):
                        capabilities[field_name] = copy.deepcopy(model[field_name])
                if model.get("provider"):
                    capabilities["publisher"] = model["provider"]
                if not capabilities:
                    continue
                capabilities["_model_id"] = model.get("id")
                capabilities["_provider"] = model.get("provider")

                for identifier in [model.get("id")] + list(model.get("aliases") or []):
                    normalized = _normalize_model_identifier(identifier)
                    if normalized:
                        catalog[normalized] = capabilities
        except (OSError, ValueError, TypeError, AttributeError):
            catalog = {}
            image_profiles = {}

        _IMAGE_OPERATION_PROFILES = copy.deepcopy(image_profiles)
        _CATALOG_CACHE = catalog
        return _CATALOG_CACHE


def get_image_operation_profile(profile_id):
    """Return an isolated provider operation profile from the same cached catalog."""
    load_model_capability_catalog()
    profile = _IMAGE_OPERATION_PROFILES.get(profile_id)
    return copy.deepcopy(profile) if isinstance(profile, Mapping) else None


def _catalog_lookup(identifier, *, capability=None, reject_version_suffix=False):
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
        record = catalog[normalized]
        return record if capability is None or capability in record else None

    best = None
    best_length = 0
    for candidate, capabilities in catalog.items():
        if len(candidate) <= best_length or not normalized.startswith(f"{candidate}-"):
            continue
        if reject_version_suffix and re.match(
            r"^\d{1,3}(?:-|$)", normalized[len(candidate) + 1:]
        ):
            # A new version is not a deployment suffix (dated snapshots still match).
            continue
        best = capabilities
        best_length = len(candidate)
    if best is not None and capability is not None and capability not in best:
        return None
    return best


def resolve_model_reasoning_policy(model_name):
    """Return an allowlisted Chat Completions reasoning policy, never a name guess.

    Records must already be authorized by the caller. Prefer their canonical model
    name to a deployment alias; configuration UUIDs and display labels are not
    capability identities. ``default_effort`` is the application's fallback for an
    invalid selection, not the provider's default for an omitted parameter.
    """
    if not isinstance(model_name, str):
        model = model_name
        model_name = ""
        for field in REASONING_IDENTIFIER_FIELDS:
            value = model.get(field) if isinstance(model, Mapping) else getattr(model, field, None)
            if isinstance(value, str) and value.strip():
                model_name = value
                break
    capabilities = _catalog_lookup(model_name, reject_version_suffix=True) or {}
    policy = capabilities.get("reasoningPolicy") or {}
    unknown = {"status": "unknown", "efforts": [], "default_effort": None}
    if not isinstance(policy, Mapping):
        return unknown
    if policy.get("status") == "unsupported":
        return {"status": "unsupported", "efforts": [], "default_effort": None}
    efforts = policy.get("efforts")
    if (
        policy.get("status") != "supported" or not isinstance(efforts, list) or not efforts
        or any(not isinstance(effort, str) or effort not in REASONING_EFFORTS for effort in efforts)
        or len(set(efforts)) != len(efforts) or policy.get("default_effort") not in efforts
    ):
        return unknown
    return {
        "status": "supported",
        "efforts": list(efforts),
        "default_effort": policy["default_effort"],
    }


def resolve_model_reasoning_effort(model_name, requested_effort):
    """Keep absent, explicit ``none``, and a corrected unsupported choice distinct."""
    requested = requested_effort.strip().lower() if isinstance(requested_effort, str) else None
    requested = requested or None
    resolution = {
        "requested_effort": requested,
        "effective_effort": None,
        "mode": "model_default",
        "adjustment_reason": None,
    }
    if requested is None:
        return resolution
    policy = resolve_model_reasoning_policy(model_name)
    if policy["status"] == "supported":
        effective = requested
        if requested not in policy["efforts"]:
            effective = "low" if "low" in policy["efforts"] else policy["default_effort"]
            resolution["adjustment_reason"] = "reasoning_effort_unsupported"
        resolution.update(effective_effort=effective, mode="explicit")
    else:
        resolution["adjustment_reason"] = (
            "reasoning_parameter_unsupported" if policy["status"] == "unsupported"
            else "reasoning_capability_unknown"
        )
    return resolution


def _model_identifiers(model, fields=MODEL_IDENTIFIER_FIELDS):
    """Return the names a model record might be known by."""
    if isinstance(model, str):
        return [model]
    if isinstance(model, Mapping):
        return [model.get(field) for field in fields]
    return [getattr(model, field, None) for field in fields]


def get_model_catalog_capabilities(model, *, strict_identity=False):
    """Look up an actual model, declared alias, or dated snapshot, not an arbitrary variant.

    Vision retains its legacy deployment-name heuristic separately. Image tool
    support must not flow from gpt-4o to gpt-4o-transcribe merely by prefix.
    Strict identity uses only a canonical/deployment name and exact catalog
    aliases, never display labels, configuration ids, or unverified snapshots.
    """
    underlying = ""
    for field_name in ("modelName", "behavior_name"):
        value = model.get(field_name) if isinstance(model, Mapping) else getattr(model, field_name, None)
        if isinstance(value, str) and value.strip():
            underlying = value
            break
    identifiers = [underlying] if underlying else _model_identifiers(model)
    if strict_identity and not underlying and not isinstance(model, str):
        identifiers = []
        for field_name in ("deploymentName", "deployment", "name"):
            value = model.get(field_name) if isinstance(model, Mapping) else getattr(model, field_name, None)
            if isinstance(value, str) and value.strip():
                identifiers = [value]
                break
    catalog = load_model_capability_catalog()
    for identifier in identifiers:
        normalized = _normalize_model_identifier(identifier)
        if normalized in catalog:
            return copy.deepcopy(catalog[normalized])
        if strict_identity:
            continue
        snapshot = re.fullmatch(r"(.+)-(\d{4})-(\d{2})-(\d{2})", normalized)
        if snapshot and snapshot.group(1) in catalog:
            try:
                date(*(int(value) for value in snapshot.groups()[1:]))
            except ValueError:
                continue
            return copy.deepcopy(catalog[snapshot.group(1)])
    return None


def _model_field(record, field):
    return record.get(field) if isinstance(record, Mapping) else getattr(record, field, None)


def _positive_token_limit(value):
    """Accept integers and decimal form values without truncating floats or bools."""
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r"[0-9]+", value):
            return None
        try:
            value = int(value)
        except ValueError:
            return None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _token_limit_containers(record):
    if record is None or isinstance(record, (str, bytes)):
        return []
    containers = [record]
    for field in TOKEN_LIMIT_CONTAINER_FIELDS:
        nested = _model_field(record, field)
        if isinstance(nested, Mapping):
            containers.append(nested)
    return containers


def _token_limit_provider(provider):
    normalized = _normalize_model_identifier(provider) if isinstance(provider, str) else ""
    if normalized in ("aoai", "azure-openai", "azureopenai"):
        return "azure-openai"
    if normalized in (
        "azure", "aifoundry", "new-foundry", "foundry", "azure-ai-foundry", "microsoft-foundry",
    ):
        return "azure"
    return "anthropic" if normalized == "claude" else normalized


def _token_limit_catalog_record(identifier):
    """Resolve declared snapshots only; a plausible date is not verified metadata."""
    normalized = _normalize_model_identifier(identifier)
    if not normalized:
        return {}
    catalog = load_model_capability_catalog()
    if normalized in catalog:
        return catalog[normalized]
    for record in catalog.values():
        limits = record.get("tokenLimits")
        snapshots = limits.get("snapshots") if isinstance(limits, Mapping) else None
        if not isinstance(snapshots, Mapping):
            continue
        for snapshot, overrides in snapshots.items():
            if (
                isinstance(snapshot, str) and _normalize_model_identifier(snapshot) == normalized
                and isinstance(overrides, Mapping)
            ):
                return {
                    **record,
                    "_model_id": snapshot,
                    "tokenLimits": {**limits, **overrides},
                }
    return {}


def resolve_model_token_limits(model, *, provider=None, deployment_limits=None):
    """Return independent, bounded token limits without invoking a model or tokenizer.

    Version: 0.261.106
    Implemented in: 0.261.106

    The caller must authorize model records and deployment metadata first.
    Canonical names take precedence even when unknown; configuration IDs and
    display labels are never identities. A deployment name must itself exactly
    match a catalog ID, declared alias, or explicitly documented snapshot.
    ``modelVersion``/``model_version`` may pin a named model to a snapshot.

    Positive integers and decimal strings are accepted in the record or the
    ``deployment_limits`` argument, directly or under tokenLimits/token_limits/
    limits. Every valid constraint can shrink, but never enlarge, a catalog or
    provider ceiling. maxTokens/max_tokens are output limits, never context.
    Input/output caps are bounded by a known context window, but neither is
    subtracted from it or used to invent a missing context/input cap.

    ``known`` means context and output ceilings are present; ``partial`` means
    at least one limit or tokenizer is present; otherwise status is ``unknown``.
    Input caps and tokenizer names are independently optional. Source is
    catalog, configured, catalog+configured, or unknown. model_id is the
    resolved catalog identity (including a pinned snapshot), otherwise None.
    Deployment SKU, endpoint, beta-header, and request-specific restrictions
    still apply; these ceilings do not promise live capacity or availability.
    """
    identifier = next((
        value.strip() for value in _model_identifiers(model, TOKEN_LIMIT_IDENTIFIER_FIELDS)
        if isinstance(value, str) and value.strip()
    ), "")
    version = next((
        value.strip() for value in (
            _model_field(model, "modelVersion"), _model_field(model, "model_version"),
        ) if isinstance(value, str) and value.strip()
    ), "")
    if version and identifier and not identifier.endswith(f"-{version}"):
        identifier = f"{identifier}-{version}"
    record = _token_limit_catalog_record(identifier)
    provider = (
        _token_limit_provider(provider) or _token_limit_provider(_model_field(model, "provider"))
    )
    publisher = _token_limit_provider(record.get("_provider"))
    if provider and publisher and not (
        provider == publisher or provider == "azure"
        or (provider == "azure-openai" and publisher == "openai")
    ):
        record = {}

    catalog_limits = record.get("tokenLimits")
    catalog_limits = catalog_limits if isinstance(catalog_limits, Mapping) else {}
    catalog_containers = [catalog_limits]
    provider_limits = catalog_limits.get("providerLimits")
    if isinstance(provider_limits, Mapping):
        provider_key = "azure" if provider == "azure-openai" else provider
        if isinstance(provider_limits.get(provider_key), Mapping):
            catalog_containers.append(provider_limits[provider_key])
    configured_containers = (
        _token_limit_containers(model) + _token_limit_containers(deployment_limits)
    )
    result = {field: None for field in TOKEN_LIMIT_FIELDS}
    sources = set()
    for field, spellings in TOKEN_LIMIT_FIELDS.items():
        for source, containers in (
            ("catalog", catalog_containers), ("configured", configured_containers),
        ):
            for container in containers:
                for spelling in spellings:
                    value = _positive_token_limit(_model_field(container, spelling))
                    if value is not None:
                        sources.add(source)
                        result[field] = min(result[field], value) if result[field] else value

    context = result["context_window_tokens"]
    if context is not None:
        for field in ("max_input_tokens", "max_output_tokens"):
            if result[field] is not None:
                result[field] = min(result[field], context)

    result["tokenizer"] = None
    for source, containers in (
        ("catalog", catalog_containers), ("configured", configured_containers),
    ):
        for container in containers:
            tokenizer = _model_field(container, "tokenizer")
            if result["tokenizer"] is None and isinstance(tokenizer, str) and tokenizer.strip():
                result["tokenizer"] = tokenizer.strip()
                sources.add(source)
    result["source"] = "+".join(
        source for source in ("catalog", "configured") if source in sources
    ) or "unknown"
    result["model_id"] = record.get("_model_id")
    result["status"] = (
        "known" if context is not None and result["max_output_tokens"] is not None
        else "partial" if sources else "unknown"
    )
    return result


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
    one worth reviewing. Embedding-only models cannot produce the text needed
    for vision analysis, even when the model itself accepts image input.
    """
    catalog = get_model_catalog_capabilities(model)
    if catalog and catalog.get("generatesEmbeddings") is True and catalog.get("generatesText") is False:
        return False, VISION_SOURCE_CATALOG

    declared = _declared_vision_support(model)
    if declared is not None:
        return declared, VISION_SOURCE_DECLARED

    identifiers = _model_identifiers(model)
    for identifier in identifiers:
        capabilities = _catalog_lookup(identifier, capability="processesImages")
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
