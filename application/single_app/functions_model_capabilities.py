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
from dataclasses import dataclass, replace


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
CATALOG_FILENAME = os.path.join(*CATALOG_RELATIVE_PATH)
VISION_OVERRIDE_FIELDS = ("supportsVision", "supports_vision")
VISION_SOURCE_DECLARED = "declared"
VISION_SOURCE_CATALOG = "catalog"
VISION_SOURCE_INFERRED = "inferred"

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

MODEL_BUDGET_LIMIT_FIELDS = ("contextWindow", "inputTokenLimit", "outputTokenLimit")
MODEL_BUDGET_PROVIDERS = frozenset(
    ("azure", "openai", "anthropic", "google", "vertex", "xai", "publisher", "custom")
)
MODEL_OUTPUT_ACCOUNTING = frozenset(("total_generation", "visible_only", "unknown"))
MAX_DECLARED_TOKEN_LIMIT = 9007199254740991

_CATALOG_LOCK = threading.Lock()
_CATALOG_CACHE = None


def _normalize_model_identifier(value):
    return MODEL_IDENTIFIER_SEPARATOR_PATTERN.sub(
        "-",
        str(value or "").strip().lower(),
    )


def get_model_capability_catalog_path():
    """Return the absolute path of the shipped model capability catalog."""
    return os.path.join(os.path.dirname(__file__), CATALOG_FILENAME)


def reset_model_capability_catalog_cache():
    """Clear the cached catalog so a later read picks the file up again."""
    global _CATALOG_CACHE
    with _CATALOG_LOCK:
        _CATALOG_CACHE = None


def _load_model_capability_catalog_document(force_refresh=False):
    """Return the parsed catalog, caching it after the first successful read."""
    global _CATALOG_CACHE
    with _CATALOG_LOCK:
        if _CATALOG_CACHE is not None and not force_refresh:
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


def load_model_capability_catalog(force_refresh=False):
    """Return the identifier-indexed capability view used by the V2 model editors."""
    document = _load_model_capability_catalog_document(force_refresh)
    catalog = {}
    for record in document.get("models") or []:
        if not isinstance(record, Mapping):
            continue
        capabilities = record.get("capabilities")
        if not isinstance(capabilities, Mapping):
            continue
        for identifier in _iter_catalog_record_identifiers(record):
            catalog[identifier] = dict(capabilities)
    return catalog


def get_model_capability_catalog_records():
    """Return every model record defined by the catalog."""
    catalog = _load_model_capability_catalog_document()
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
        capabilities = {}
    declared = {}
    for capability_name, capability_value in capabilities.items():
        if isinstance(capability_value, bool):
            declared[str(capability_name)] = capability_value
    if CAPABILITY_PROCESSES_IMAGES not in declared:
        for field_name in VISION_OVERRIDE_FIELDS:
            value = _get_record_field(source, field_name)
            if isinstance(value, bool):
                declared[CAPABILITY_PROCESSES_IMAGES] = value
                break
            if isinstance(value, str) and value.strip():
                declared[CAPABILITY_PROCESSES_IMAGES] = value.strip().lower() in ("true", "on", "yes", "1")
                break
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


class ModelTokenBudgetError(ValueError):
    """A user-safe, explicit configuration error, not an authentication failure."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.public_message = message

    @property
    def payload(self):
        return {"error": self.public_message, "error_code": self.code}


def normalize_token_limit(value, field_name="token limit"):
    """Accept explicit integer counts without truncating floats or coercing bools."""
    if isinstance(value, str):
        value = value.strip()
    if value is None or value == "":
        return None
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        digits = value.lstrip("0") or "0"
        if len(digits) <= len(str(MAX_DECLARED_TOKEN_LIMIT)):
            value = int(digits)
    if type(value) is not int or not 1 <= value <= MAX_DECLARED_TOKEN_LIMIT:
        raise ModelTokenBudgetError(
            "model_context_invalid",
            f"{field_name} must be a positive whole number of tokens.",
        )
    return value


def normalize_model_budget_overrides(record):
    """Normalize only present allowlisted metadata; never copy endpoint secrets."""
    if not isinstance(record, Mapping):
        return {}
    normalized = {}
    for field_name in MODEL_BUDGET_LIMIT_FIELDS:
        if field_name in record:
            normalized[field_name] = normalize_token_limit(record[field_name], field_name)
    for field_name in ("catalogModelId", "modelVersion", "tokenLimitProvider", "outputTokenAccounting"):
        if field_name not in record:
            continue
        value = record[field_name]
        if value is not None and not isinstance(value, str):
            raise ModelTokenBudgetError("model_context_invalid", f"{field_name} must be text.")
        value = value.strip() if value else None
        if value and (len(value) > 256 or any(ord(character) < 32 for character in value)):
            raise ModelTokenBudgetError("model_context_invalid", f"{field_name} is invalid.")
        if field_name == "tokenLimitProvider" and value not in (None, *MODEL_BUDGET_PROVIDERS):
            raise ModelTokenBudgetError("model_context_invalid", "Select a supported token-limit provider.")
        if field_name == "outputTokenAccounting" and value not in (None, *MODEL_OUTPUT_ACCOUNTING):
            raise ModelTokenBudgetError("model_context_invalid", "Select a supported output-token accounting mode.")
        normalized[field_name] = value
    return normalized


@dataclass(frozen=True)
class ModelTokenBudget:
    """Secret-free model capacity and request allowance, safe to attach to an agent."""

    model_id: str = ""
    provider: str = ""
    protocol: str = "chat_completions"
    model_version: str = ""
    context_window: int | None = None
    input_limit: int | None = None
    output_limit: int | None = None
    effective_context_window: int | None = None
    request_output_limit: int | None = None
    output_accounting: str = "unknown"
    output_accounting_source: str = "unresolved"
    applicability: str = "text"
    tool_reasoning_efforts: tuple[str, ...] = ()
    provenance: tuple[tuple[str, str], ...] = ()

    def with_request_limit(self, value):
        return replace(self, request_output_limit=normalize_token_limit(value, "Response Length"))

    def remaining_input(self, input_tokens=0):
        """Apply independent ceilings without subtracting output from input-only limits."""
        if type(input_tokens) is not int or input_tokens < 0:
            raise ModelTokenBudgetError("model_context_invalid", "The input token count is invalid.")
        if self.applicability != "text":
            raise ModelTokenBudgetError(
                "model_context_unavailable", "Select a text-generation model for file evidence."
            )
        if self.output_accounting != "total_generation":
            raise ModelTokenBudgetError(
                "model_generation_unbounded",
                "This endpoint needs a verified total-generation token allowance, including reasoning, before file evidence can be added.",
            )
        output = self.request_output_limit or self.output_limit
        if output is None or not (self.context_window or self.input_limit):
            raise ModelTokenBudgetError(
                "model_context_unavailable",
                "Configure the selected model's published token limits and Response Length in Model Endpoints before using file evidence.",
            )
        if self.output_limit is not None and output > self.output_limit:
            raise ModelTokenBudgetError(
                "model_context_invalid", "Response Length exceeds this model's documented output limit."
            )
        bounds = []
        if self.input_limit is not None:
            bounds.append(self.input_limit)
        for window in (self.context_window, self.effective_context_window):
            if window is not None:
                bounds.append(window - output)
        return max(0, min(bounds) - input_tokens)


def _numeric_catalog_record(model, records=None):
    if isinstance(model, str):
        identifier = model
    else:
        identifier = next((
            _get_record_field(model, field_name)
            for field_name in ("catalogModelId", "modelName", "deploymentName", "deployment", "name")
            if _get_record_field(model, field_name)
        ), "")
    normalized = _normalize_model_identifier(identifier)
    if not normalized:
        return None
    for record in get_model_capability_catalog_records() if records is None else records:
        identifiers = (record["id"], *(record.get("verifiedAliases") or ()))
        if any(normalized == _normalize_model_identifier(value) for value in identifiers):
            return record
    return None


def _budget_provider(model, endpoint, record, provider):
    override = (
        _get_record_field(model, "tokenLimitProvider")
        or _get_record_field(endpoint, "tokenLimitProvider")
    )
    if override:
        return override
    selected = str(provider or _get_record_field(endpoint, "provider") or "").strip().lower()
    if selected in ("aoai", "aifoundry", "new_foundry", "foundry_workflow", "azure_openai"):
        return "azure"
    if selected == "claude":
        return "anthropic"
    if selected in MODEL_BUDGET_PROVIDERS and selected != "custom":
        return selected
    return (record or {}).get("provider") or selected


def _catalog_budget_profile(record, provider, protocol, model_version):
    if record is None:
        return {}
    profile = dict(record)
    profile["tokenLimitEvidence"] = dict(record.get("tokenLimitEvidence") or {})
    matches = []
    for candidate in record.get("tokenLimitProfiles") or ():
        if candidate.get("provider") != provider:
            continue
        if candidate.get("protocol") and candidate["protocol"] != protocol:
            continue
        versions = candidate.get("modelVersions") or ()
        if versions and model_version not in versions:
            continue
        specificity = bool(candidate.get("protocol")) + 2 * bool(versions)
        matches.append((specificity, candidate))
    applied = {}
    for specificity, candidate in sorted(matches, key=lambda item: item[0]):
        for field_name in (
            *MODEL_BUDGET_LIMIT_FIELDS, "effectiveContextWindow", "outputTokenAccounting",
            "toolReasoningEfforts",
        ):
            if field_name not in candidate:
                continue
            if (specificity, field_name) in applied and applied[(specificity, field_name)] != candidate[field_name]:
                raise ModelTokenBudgetError("model_context_invalid", "The model's token-limit profiles are ambiguous.")
            applied[(specificity, field_name)] = candidate[field_name]
            profile[field_name] = candidate[field_name]
        profile["tokenLimitEvidence"].update(candidate.get("tokenLimitEvidence") or {})
    return profile


def resolve_model_token_budget(
    model=None, endpoint=None, *, provider=None, protocol="chat_completions",
    model_version=None, request_output_limit=None, catalog_records=None,
):
    """Resolve each numeric field independently, with exact, scoped catalog identity."""
    if isinstance(model, ModelTokenBudget):
        return model if request_output_limit is None else model.with_request_limit(request_output_limit)
    model_overrides = normalize_model_budget_overrides(model)
    endpoint_overrides = normalize_model_budget_overrides(endpoint)
    record = _numeric_catalog_record(model, catalog_records)
    provider = _budget_provider(
        model_overrides, endpoint_overrides, record, provider or _get_record_field(endpoint, "provider"),
    )
    version = str(
        model_version or model_overrides.get("modelVersion")
        or _get_record_field(model, "version")
        or endpoint_overrides.get("modelVersion") or ""
    )
    profile = _catalog_budget_profile(record, provider, protocol, version)
    evidence = profile.get("tokenLimitEvidence") or {}
    provenance = []
    values = {}
    for field_name in (*MODEL_BUDGET_LIMIT_FIELDS, "effectiveContextWindow"):
        value = None
        for name, source in (("model", model_overrides), ("endpoint", endpoint_overrides), ("catalog", profile)):
            candidate = source.get(field_name)
            if candidate is None:
                continue
            if name == "catalog" and evidence.get(field_name, {}).get("status") in (
                "configuration-only", "unknown", "not-applicable", "hosting-dependent",
            ):
                continue
            value = normalize_token_limit(candidate, field_name)
            provenance.append((field_name, name))
            break
        values[field_name] = value
    output_accounting = "unknown"
    accounting_source = "unresolved"
    for name, source in (("model", model_overrides), ("endpoint", endpoint_overrides), ("catalog", profile)):
        if source.get("outputTokenAccounting"):
            output_accounting = source["outputTokenAccounting"]
            accounting_source = name
            break
    return ModelTokenBudget(
        model_id=(record or {}).get("id") or str(
            model_overrides.get("catalogModelId") or _get_record_field(model, "modelName")
            or _get_record_field(model, "deploymentName") or (model if isinstance(model, str) else "")
        ),
        provider=provider,
        protocol=protocol,
        model_version=version,
        context_window=values["contextWindow"],
        input_limit=values["inputTokenLimit"],
        output_limit=values["outputTokenLimit"],
        effective_context_window=values["effectiveContextWindow"],
        request_output_limit=normalize_token_limit(request_output_limit, "Response Length"),
        output_accounting=output_accounting,
        output_accounting_source=accounting_source,
        applicability=profile.get("tokenLimitsApplicability", "text"),
        tool_reasoning_efforts=tuple(profile.get("toolReasoningEfforts") or ()),
        provenance=tuple(provenance),
    )


def project_model_budget_metadata(record):
    """Copy identifiers/capacities only; callers retain ownership of all credentials."""
    if not isinstance(record, Mapping):
        return {}
    normalized = normalize_model_budget_overrides(record)
    fields = (
        *MODEL_BUDGET_LIMIT_FIELDS, "catalogModelId", "modelVersion", "tokenLimitProvider",
        "outputTokenAccounting", "modelName", "deploymentName", "deployment", "name", "version",
        "responseLength", "reasoning_effort", "reasoningEffort", "provider",
    )
    projection = {
        field: record[field] for field in fields
        if field in record and isinstance(record[field], (str, int, type(None)))
    }
    projection.update(normalized)
    return projection


def resolve_model_token_limits(model=None, endpoint=None):
    """Compatibility view; new callers use the separate fields on ModelTokenBudget."""
    budget = resolve_model_token_budget(model, endpoint)
    bounds = [
        value for value in (budget.context_window, budget.input_limit, budget.effective_context_window)
        if value is not None
    ]
    return min(bounds) if bounds else None, budget.output_limit


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


def resolve_model_vision_support(model, endpoint=None):
    """Return the shared vision decision and its source for model-editor controls."""
    supports_vision = bool(
        resolve_model_capability(
            CAPABILITY_PROCESSES_IMAGES,
            model,
            endpoint,
            default=False,
        )
    )
    for source in (model, endpoint):
        if CAPABILITY_PROCESSES_IMAGES in _read_declared_capabilities(source):
            return supports_vision, VISION_SOURCE_DECLARED
    record = find_model_catalog_record(model)
    if record is not None:
        capabilities = record.get("capabilities")
        if isinstance(capabilities, Mapping) and isinstance(
            capabilities.get(CAPABILITY_PROCESSES_IMAGES), bool
        ):
            return supports_vision, VISION_SOURCE_CATALOG
    return supports_vision, VISION_SOURCE_INFERRED


def is_vision_capable_model(model, endpoint=None):
    """Return whether a model record or identifier can accept image input."""
    supports_vision, _source = resolve_model_vision_support(model, endpoint)
    return supports_vision


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
