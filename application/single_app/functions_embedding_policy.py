# functions_embedding_policy.py
"""Pure embedding limits and input semantics, separate from endpoint transport.

Catalog entries describe models, not successful inference probes. A gateway
declaration attests that it implements the OpenAI operation and handles any
native task/dimension translation; it never enables a vendor-native adapter.
"""

from collections.abc import Mapping

from functions_model_capabilities import get_model_catalog_capabilities


_INTEGER_LIMITS = {
    "dimensions": 65536,
    "default_dimensions": 65536,
    "min_dimensions": 65536,
    "max_dimensions": 65536,
    "max_input_tokens": 1048576,
    "model_context_tokens": 1048576,
    "max_batch_size": 2048,
    "max_batch_tokens": 16777216,
}
_CONFIG_INTEGER_FIELDS = (
    "dimensions", "max_input_tokens", "max_batch_size", "max_batch_tokens",
)
_TEXT_LIMITS = {"model_revision": 256, "document_prefix": 8192, "query_prefix": 8192}
_CONFIG_FIELDS = frozenset((*_CONFIG_INTEGER_FIELDS, *_TEXT_LIMITS, "openai_compatible"))
_CATALOG_REQUIRED_FIELDS = frozenset((
    "default_dimensions", "supports_dimensions", "min_dimensions", "max_dimensions",
    "max_input_tokens", "max_batch_size", "max_batch_tokens", "tokenizer",
    "model_revision", "document_prefix", "query_prefix", "api", "requires_input_type",
))
_CATALOG_OPTIONAL_FIELDS = frozenset((
    "allowed_dimensions", "model_context_tokens", "hosting_limits", "versions",
))
_LEGACY_CONTEXT_FIELDS = (
    "context_window", "contextWindow", "maxContextTokens",
    "context_length", "contextLength", "maxTokens",
)


class EmbeddingPolicyError(ValueError):
    """A stable validation error whose message contains no configuration values."""

    def __init__(self, message):
        super().__init__(message)
        self.public_message = message


def _positive_integer(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _INTEGER_LIMITS[field]:
        raise EmbeddingPolicyError(
            f"Embedding {field} must be an integer between 1 and {_INTEGER_LIMITS[field]}."
        )
    return value


def _text(value, field, *, allow_empty=False):
    if not isinstance(value, str) or len(value) > _TEXT_LIMITS[field]:
        raise EmbeddingPolicyError(
            f"Embedding {field} must be text of at most {_TEXT_LIMITS[field]} characters."
        )
    if field == "model_revision":
        value = value.strip()
    if (not allow_empty and not value) or any(
        (ord(character) < 32 and (field == "model_revision" or character not in "\t\n\r"))
        or ord(character) == 127
        for character in value
    ):
        raise EmbeddingPolicyError(f"Embedding {field} contains invalid text.")
    return value


def normalize_embedding_config(value):
    """Validate administrator overrides without treating malformed values as absent."""
    if not isinstance(value, Mapping):
        raise EmbeddingPolicyError("Embedding configuration must be an object.")
    if any(not isinstance(key, str) or key not in _CONFIG_FIELDS for key in value):
        raise EmbeddingPolicyError("Embedding configuration contains unsupported fields.")

    normalized = {}
    for field, item in value.items():
        if field in _CONFIG_INTEGER_FIELDS:
            normalized[field] = _positive_integer(item, field)
        elif field in _TEXT_LIMITS:
            normalized[field] = _text(item, field, allow_empty=field != "model_revision")
        else:
            if not isinstance(item, bool):
                raise EmbeddingPolicyError("Embedding openai_compatible must be true or false.")
            normalized[field] = item
    if (
        "max_input_tokens" in normalized and "max_batch_tokens" in normalized
        and normalized["max_batch_tokens"] < normalized["max_input_tokens"]
    ):
        raise EmbeddingPolicyError("Embedding max_batch_tokens must allow at least one maximum-length input.")
    return normalized


def _catalog_policy(value):
    if (
        not isinstance(value, Mapping)
        or not _CATALOG_REQUIRED_FIELDS.issubset(value)
        or any(key not in _CATALOG_REQUIRED_FIELDS | _CATALOG_OPTIONAL_FIELDS for key in value)
    ):
        raise EmbeddingPolicyError("The catalog embedding policy is incomplete or invalid.")
    policy = dict(value)
    for field in _INTEGER_LIMITS:
        if field in policy:
            policy[field] = _positive_integer(policy[field], field)
    for field in ("supports_dimensions", "requires_input_type"):
        if not isinstance(policy[field], bool):
            raise EmbeddingPolicyError("The catalog embedding policy contains an invalid capability flag.")
    if policy["api"] not in ("openai", "unsupported"):
        raise EmbeddingPolicyError("The catalog embedding policy requires an unsupported API.")
    if policy["tokenizer"] not in ("cl100k_base", "conservative"):
        raise EmbeddingPolicyError("The catalog embedding policy contains an unsupported tokenizer.")
    for field in _TEXT_LIMITS:
        policy[field] = _text(policy[field], field, allow_empty=field != "model_revision")
    if not policy["min_dimensions"] <= policy["default_dimensions"] <= policy["max_dimensions"]:
        raise EmbeddingPolicyError("The catalog embedding dimensions are inconsistent.")
    if not policy["supports_dimensions"] and not (
        policy["min_dimensions"] == policy["default_dimensions"] == policy["max_dimensions"]
    ):
        raise EmbeddingPolicyError("The catalog fixed embedding dimensions are inconsistent.")
    if "allowed_dimensions" in policy:
        allowed = policy["allowed_dimensions"]
        if not isinstance(allowed, list) or not allowed or len(allowed) > 128:
            raise EmbeddingPolicyError("The catalog allowed embedding dimensions are invalid.")
        allowed = [_positive_integer(item, "dimensions") for item in allowed]
        if (
            len(set(allowed)) != len(allowed)
            or policy["default_dimensions"] not in allowed
            or any(not policy["min_dimensions"] <= item <= policy["max_dimensions"] for item in allowed)
        ):
            raise EmbeddingPolicyError("The catalog allowed embedding dimensions are inconsistent.")
        policy["allowed_dimensions"] = sorted(allowed)
    if policy["max_batch_tokens"] < policy["max_input_tokens"]:
        raise EmbeddingPolicyError("The catalog embedding batch budget is smaller than one input.")
    context_limit = policy.get("model_context_tokens", policy["max_input_tokens"])
    if context_limit < policy["max_input_tokens"]:
        raise EmbeddingPolicyError("The catalog embedding hosting limit exceeds the model context.")
    if "hosting_limits" in policy:
        hosts = policy["hosting_limits"]
        if not isinstance(hosts, Mapping) or not hosts:
            raise EmbeddingPolicyError("The catalog embedding hosting limits are invalid.")
        for host, limits in hosts.items():
            if (
                not isinstance(host, str) or not host or len(host) > 64
                or not isinstance(limits, Mapping) or set(limits) != {"max_input_tokens"}
                or _positive_integer(limits["max_input_tokens"], "max_input_tokens") > context_limit
            ):
                raise EmbeddingPolicyError("The catalog embedding hosting limits are invalid.")
    if "versions" in policy:
        versions = policy["versions"]
        if not isinstance(versions, Mapping) or not versions:
            raise EmbeddingPolicyError("The catalog embedding version policies are invalid.")
        normalized_versions = {}
        for version, limits in versions.items():
            if (
                not isinstance(version, str) or not version.strip() or len(version) > 64
                or not isinstance(limits, Mapping)
                or set(limits) != {"max_input_tokens", "model_revision"}
            ):
                raise EmbeddingPolicyError("The catalog embedding version policies are invalid.")
            normalized_versions[version] = {
                "max_input_tokens": _positive_integer(limits["max_input_tokens"], "max_input_tokens"),
                "model_revision": _text(limits["model_revision"], "model_revision"),
            }
        policy["versions"] = normalized_versions
    return policy


def _model_version(model):
    if not isinstance(model, Mapping):
        return ""
    for field in ("modelVersion", "model_version", "version"):
        value = model.get(field)
        if value is None or value == "":
            continue
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            value = str(value)
        if not isinstance(value, str) or not value.strip() or len(value) > 64:
            raise EmbeddingPolicyError("Embedding model version must be a nonempty version identifier.")
        return _text(value, "model_revision")
    return ""


def get_legacy_embedding_context_tokens(model):
    """Prefer a strict canonical limit, then the legacy first-positive alias conversion."""
    if not isinstance(model, Mapping):
        return None
    config = model.get("embedding_config")
    if isinstance(config, Mapping) and "max_input_tokens" in config:
        return _positive_integer(config["max_input_tokens"], "max_input_tokens")
    for field in _LEGACY_CONTEXT_FIELDS:
        value = model.get(field)
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if parsed > 0:
            return _positive_integer(parsed, "max_input_tokens")
    return None


def resolve_embedding_policy(model, *, legacy=False):
    """Return validated model limits and semantics, without credentials or SDK state.

    Unknown models need explicit dimensions and per-input limits. ``legacy`` is
    reserved for importing historical Azure configurations; its fallback must
    not be used to publish newly declared custom embedding models. Legacy
    context aliases retain their configured budget unless a canonical
    embedding_config.max_input_tokens override is explicitly supplied.
    """
    if not isinstance(legacy, bool) or not isinstance(model, (str, Mapping)):
        raise EmbeddingPolicyError("Embedding model configuration is invalid.")
    config = normalize_embedding_config(model["embedding_config"]) if (
        isinstance(model, Mapping) and "embedding_config" in model
    ) else {}
    legacy_context = get_legacy_embedding_context_tokens(model) if legacy and "max_input_tokens" not in config else None
    capabilities = get_model_catalog_capabilities(model, strict_identity=True)
    known = capabilities is not None and "embeddingPolicy" in capabilities
    version = _model_version(model)

    if known:
        policy = _catalog_policy(capabilities["embeddingPolicy"])
        versions = policy.get("versions", {})
        if version and versions:
            if version in versions:
                policy.update(versions[version])
            elif "max_input_tokens" in config and "model_revision" in config:
                policy.update(
                    max_input_tokens=config["max_input_tokens"],
                    model_revision=config["model_revision"],
                )
            else:
                raise EmbeddingPolicyError(
                    "This embedding model version is not cataloged. Declare verified max_input_tokens and model_revision."
                )
        elif version and not policy["model_revision"].endswith(f":{version}"):
            policy["model_revision"] = _text(f"{policy['model_revision']}:{version}", "model_revision")
    else:
        if not legacy and not {"dimensions", "max_input_tokens"}.issubset(config):
            raise EmbeddingPolicyError(
                "Unknown embedding models require explicit dimensions and max_input_tokens in embedding_config."
            )
        dimensions = config.get("dimensions", 1536)
        input_tokens = config.get("max_input_tokens", legacy_context if legacy_context is not None else 8192)
        policy = {
            "default_dimensions": dimensions,
            "supports_dimensions": False,
            "min_dimensions": dimensions,
            "max_dimensions": dimensions,
            "max_input_tokens": input_tokens,
            "max_batch_size": 16,
            "max_batch_tokens": input_tokens * 16,
            "tokenizer": "cl100k_base" if legacy else "conservative",
            "model_revision": version,
            "document_prefix": "",
            "query_prefix": "",
            "api": "openai",
            "requires_input_type": False,
        }

    dimensions = config.get("dimensions", policy["default_dimensions"])
    if (
        not policy["min_dimensions"] <= dimensions <= policy["max_dimensions"]
        or ("allowed_dimensions" in policy and dimensions not in policy["allowed_dimensions"])
    ):
        raise EmbeddingPolicyError("Embedding dimensions are not supported by this model.")
    input_tokens = config.get(
        "max_input_tokens", legacy_context if legacy_context is not None else policy["max_input_tokens"]
    )
    batch_size = config.get("max_batch_size", policy["max_batch_size"])
    # A verified larger hosting limit can allow one larger input without
    # automatically multiplying the batch budget by the model's full context.
    batch_tokens = config.get("max_batch_tokens", max(policy["max_batch_tokens"], input_tokens))
    if known:
        if legacy_context is None and input_tokens > policy.get("model_context_tokens", policy["max_input_tokens"]):
            raise EmbeddingPolicyError("Embedding max_input_tokens exceeds this model's documented limit.")
        if batch_size > policy["max_batch_size"]:
            raise EmbeddingPolicyError("Embedding max_batch_size exceeds this model's documented limit.")
        if (
            policy["api"] == "openai" and batch_tokens > policy["max_batch_tokens"]
            and (legacy_context is None or "max_batch_tokens" in config)
        ):
            raise EmbeddingPolicyError("Embedding max_batch_tokens exceeds this model's documented limit.")
    if batch_tokens < input_tokens:
        raise EmbeddingPolicyError("Embedding max_batch_tokens must allow at least one maximum-length input.")

    api = policy["api"]
    if config.get("openai_compatible") is False:
        api = "unsupported"
    elif config.get("openai_compatible") is True:
        api = "openai"
    elif policy["requires_input_type"]:
        api = "unsupported"

    result = {
        "default_dimensions": policy["default_dimensions"],
        "dimensions": dimensions,
        "supports_dimensions": policy["supports_dimensions"],
        "request_dimensions": dimensions if (
            "dimensions" in config and policy["supports_dimensions"] and api == "openai"
        ) else None,
        "min_dimensions": policy["min_dimensions"],
        "max_dimensions": policy["max_dimensions"],
        "max_input_tokens": input_tokens,
        "max_batch_size": batch_size,
        "max_batch_tokens": batch_tokens,
        "tokenizer": policy["tokenizer"],
        "model_revision": config.get("model_revision", policy["model_revision"]),
        "document_prefix": config.get("document_prefix", policy["document_prefix"]),
        "query_prefix": config.get("query_prefix", policy["query_prefix"]),
        "api": api,
        "requires_input_type": policy["requires_input_type"],
    }
    if "allowed_dimensions" in policy:
        result["allowed_dimensions"] = list(policy["allowed_dimensions"])
    return result
