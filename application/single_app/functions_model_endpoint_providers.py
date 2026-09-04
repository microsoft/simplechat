# functions_model_endpoint_providers.py
"""Registry of Custom model endpoint API types.

Custom endpoints used to support exactly three API types, hard-coded in five
places: the api-type allowlist, the request-model resolver, the protocol
inference if-chain, the admin template's option list, and the admin JavaScript.
Adding a provider meant editing all five and hoping none were missed.

This module makes an API type a single declarative record. A provider entry
carries everything the rest of the application needs to know: which wire protocol
to speak, which field names the model identifier, how to turn the configured URL
into a request URL, which auth types are accepted, and which optional version
field applies.

Transport tiers
---------------
Providers are tiered by whether SimpleChat can control the outbound connection:

  Tier A  reached through an OpenAI-compatible or Anthropic HTTP surface, so the
          request goes through the validated-DNS pinned transport.
  Tier B  would require a vendor SDK with its own transport (gRPC or botocore),
          which the pinned transport cannot wrap.

Only Tier A providers are registered here. Google Gemini is reachable at Tier A
through its OpenAI-compatible surface, so it does not need a Tier B entry.

Only stdlib imports are used so this module can sit below the client, runtime,
validation, and route layers without creating import cycles.
"""

from typing import Any, Dict, Tuple

MODEL_ENDPOINT_PROVIDER_CUSTOM = "custom"

MODEL_ENDPOINT_API_TYPE_OPENAI = "openai"
MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI = "azure_openai"
MODEL_ENDPOINT_API_TYPE_ANTHROPIC = "anthropic"
MODEL_ENDPOINT_API_TYPE_GEMINI = "gemini"

# Wire protocols. These mirror the MODEL_ENDPOINT_PROTOCOL_* values in
# model_endpoint_clients, which imports them from here to keep one definition.
MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI = "azure_openai"
MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE = "openai_style"
MODEL_ENDPOINT_PROTOCOL_ANTHROPIC = "anthropic"

# How the configured endpoint URL becomes a request URL.
URL_POLICY_APPEND_V1_IF_MISSING = "append_v1_if_missing"
URL_POLICY_AS_GIVEN = "as_given"
URL_POLICY_AZURE_DEPLOYMENT = "azure_deployment"
URL_POLICY_ANTHROPIC_MESSAGES = "anthropic_messages"

# An administrator can override the provider's URL policy per endpoint. "auto"
# uses the provider policy; "exact" forces the URL to be used exactly as entered,
# which covers gateways that mount the API at a path SimpleChat cannot infer.
CUSTOM_ENDPOINT_URL_MODE_AUTO = "auto"
CUSTOM_ENDPOINT_URL_MODE_EXACT = "exact"
CUSTOM_ENDPOINT_URL_MODES = (CUSTOM_ENDPOINT_URL_MODE_AUTO, CUSTOM_ENDPOINT_URL_MODE_EXACT)


def normalize_custom_endpoint_url_mode(url_mode: Any) -> str:
    """Return a supported URL mode, defaulting to the provider's own policy."""
    normalized = str(url_mode or "").strip().lower()
    return normalized if normalized in CUSTOM_ENDPOINT_URL_MODES else CUSTOM_ENDPOINT_URL_MODE_AUTO

# Which model record field carries the identifier sent on the wire.
MODEL_IDENTIFIER_MODEL_NAME = "model_name"
MODEL_IDENTIFIER_DEPLOYMENT_NAME = "deployment_name"

DEFAULT_ANTHROPIC_VERSION = "2023-06-01"

AUTH_TYPE_API_KEY = "api_key"


class ModelEndpointProvider:
    """One Custom endpoint API type and everything the app needs to know about it."""

    def __init__(
        self,
        api_type: str,
        display_name: str,
        protocol: str,
        model_identifier: str,
        url_policy: str,
        *,
        auth_types: Tuple[str, ...] = (AUTH_TYPE_API_KEY,),
        requires_api_version: bool = False,
        version_field: str = "",
        default_version: str = "",
        supports_streaming: bool = True,
        supports_tools: bool = True,
        supports_stream_options: bool = False,
        description: str = "",
    ):
        self.api_type = api_type
        self.display_name = display_name
        self.protocol = protocol
        self.model_identifier = model_identifier
        self.url_policy = url_policy
        self.auth_types = auth_types
        self.requires_api_version = requires_api_version
        self.version_field = version_field
        self.default_version = default_version
        self.supports_streaming = supports_streaming
        self.supports_tools = supports_tools
        self.supports_stream_options = supports_stream_options
        self.description = description

    @property
    def uses_model_name(self) -> bool:
        """Return whether this API type names models rather than deployments."""
        return self.model_identifier == MODEL_IDENTIFIER_MODEL_NAME

    def to_ui_option(self) -> Dict[str, Any]:
        """Return the descriptor the admin UI needs to render and drive this type."""
        return {
            "value": self.api_type,
            "label": self.display_name,
            "usesModelName": self.uses_model_name,
            "requiresApiVersion": self.requires_api_version,
            "versionField": self.version_field,
            "defaultVersion": self.default_version,
            "authTypes": list(self.auth_types),
            "description": self.description,
        }


MODEL_ENDPOINT_PROVIDERS: Tuple[ModelEndpointProvider, ...] = (
    ModelEndpointProvider(
        api_type=MODEL_ENDPOINT_API_TYPE_OPENAI,
        display_name="OpenAI API",
        protocol=MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
        model_identifier=MODEL_IDENTIFIER_MODEL_NAME,
        url_policy=URL_POLICY_APPEND_V1_IF_MISSING,
        # OpenAI accepts stream_options.include_usage, which is how a streaming
        # response reports token usage. Providers that reject it keep the default.
        supports_stream_options=True,
        description=(
            "OpenAI and any OpenAI-compatible surface, including gateways, "
            "vLLM, and LiteLLM."
        ),
    ),
    ModelEndpointProvider(
        api_type=MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
        display_name="Azure OpenAI API",
        protocol=MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
        model_identifier=MODEL_IDENTIFIER_DEPLOYMENT_NAME,
        url_policy=URL_POLICY_AZURE_DEPLOYMENT,
        requires_api_version=True,
        version_field="api_version",
        description="An Azure OpenAI resource addressed by deployment name.",
    ),
    ModelEndpointProvider(
        api_type=MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
        display_name="Anthropic",
        protocol=MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
        model_identifier=MODEL_IDENTIFIER_MODEL_NAME,
        url_policy=URL_POLICY_ANTHROPIC_MESSAGES,
        version_field="anthropic_version",
        default_version=DEFAULT_ANTHROPIC_VERSION,
        description="Anthropic's messages API, direct or through a gateway.",
    ),
    ModelEndpointProvider(
        api_type=MODEL_ENDPOINT_API_TYPE_GEMINI,
        display_name="Google Gemini (OpenAI-compatible)",
        protocol=MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
        model_identifier=MODEL_IDENTIFIER_MODEL_NAME,
        # Gemini's compatible surface already ends in /v1beta/openai/, so appending
        # /v1 would produce a 404. The URL is used exactly as configured.
        url_policy=URL_POLICY_AS_GIVEN,
        description=(
            "Google Gemini through its OpenAI-compatible surface, normally "
            "https://generativelanguage.googleapis.com/v1beta/openai/."
        ),
    ),
)

MODEL_ENDPOINT_PROVIDERS_BY_API_TYPE: Dict[str, ModelEndpointProvider] = {
    provider.api_type: provider for provider in MODEL_ENDPOINT_PROVIDERS
}

MODEL_ENDPOINT_CUSTOM_API_TYPES = frozenset(MODEL_ENDPOINT_PROVIDERS_BY_API_TYPE)


def normalize_api_type_value(api_type: Any) -> str:
    """Return an api_type string in canonical form."""
    return str(api_type or "").strip().lower().replace("-", "_")


def get_model_endpoint_provider(api_type: Any) -> ModelEndpointProvider | None:
    """Return the registered provider for an api_type, or None when unsupported."""
    return MODEL_ENDPOINT_PROVIDERS_BY_API_TYPE.get(normalize_api_type_value(api_type))


def get_model_endpoint_provider_ui_options() -> list:
    """Return every registered API type as an admin UI descriptor."""
    return [provider.to_ui_option() for provider in MODEL_ENDPOINT_PROVIDERS]


def is_supported_custom_api_type(api_type: Any) -> bool:
    """Return whether an api_type names a registered provider."""
    return normalize_api_type_value(api_type) in MODEL_ENDPOINT_CUSTOM_API_TYPES
