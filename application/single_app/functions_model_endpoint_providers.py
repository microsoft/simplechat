# functions_model_endpoint_providers.py
"""Dependency-light registry of the protocols supported by Custom connections.

These descriptors describe a transport contract, not a model's capabilities.
In particular, an OpenAI-compatible endpoint does not imply image support.
"""

from dataclasses import dataclass
from typing import Any


MODEL_ENDPOINT_PROVIDER_CUSTOM = "custom"
MODEL_ENDPOINT_API_TYPE_OPENAI = "openai"
MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI = "azure_openai"
MODEL_ENDPOINT_API_TYPE_ANTHROPIC = "anthropic"
MODEL_ENDPOINT_API_TYPE_GEMINI = "gemini"
MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI = "azure_openai"
MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE = "openai_style"
MODEL_ENDPOINT_PROTOCOL_ANTHROPIC = "anthropic"

URL_POLICY_APPEND_V1_IF_MISSING = "append_v1_if_missing"
URL_POLICY_AS_GIVEN = "as_given"
URL_POLICY_AZURE_DEPLOYMENT = "azure_deployment"
URL_POLICY_ANTHROPIC_MESSAGES = "anthropic_messages"
CUSTOM_ENDPOINT_URL_MODE_AUTO = "auto"
CUSTOM_ENDPOINT_URL_MODE_EXACT = "exact"
CUSTOM_ENDPOINT_URL_MODES = (CUSTOM_ENDPOINT_URL_MODE_AUTO, CUSTOM_ENDPOINT_URL_MODE_EXACT)
MODEL_IDENTIFIER_MODEL_NAME = "model_name"
MODEL_IDENTIFIER_DEPLOYMENT_NAME = "deployment_name"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"

AUTH_TYPE_API_KEY = "api_key"
AUTH_TYPE_KEY = "key"
AUTH_TYPE_BEARER = "bearer"
AUTH_TYPE_OAUTH2_CLIENT_CREDENTIALS = "oauth2_client_credentials"
DEFAULT_CUSTOM_AUTH_TYPES = (
    AUTH_TYPE_API_KEY,
    AUTH_TYPE_BEARER,
    AUTH_TYPE_OAUTH2_CLIENT_CREDENTIALS,
)


def normalize_custom_endpoint_url_mode(url_mode: Any) -> str:
    """Return a supported URL policy override."""
    normalized = str(url_mode or "").strip().lower()
    return normalized if normalized in CUSTOM_ENDPOINT_URL_MODES else CUSTOM_ENDPOINT_URL_MODE_AUTO


def normalize_custom_endpoint_auth_type(auth_type: Any) -> str:
    """Return the canonical auth type, or an empty string for unsupported types."""
    normalized = str(auth_type or "").strip().lower()
    if normalized == AUTH_TYPE_KEY:
        return AUTH_TYPE_API_KEY
    return normalized if normalized in DEFAULT_CUSTOM_AUTH_TYPES else ""


@dataclass(frozen=True)
class ModelEndpointProvider:
    """An API type's wire protocol, URL, credential, and model identity contract."""

    api_type: str
    display_name: str
    protocol: str
    model_identifier: str
    url_policy: str
    auth_types: tuple[str, ...] = DEFAULT_CUSTOM_AUTH_TYPES
    default_api_key_header: str = "Authorization"
    default_api_key_prefix: str = "Bearer"
    requires_api_version: bool = False
    version_field: str = ""
    default_version: str = ""
    supports_streaming: bool = True
    supports_tools: bool = True
    supports_stream_options: bool = False
    description: str = ""

    @property
    def uses_model_name(self) -> bool:
        return self.model_identifier == MODEL_IDENTIFIER_MODEL_NAME

    def to_ui_option(self) -> dict:
        """Return non-secret configuration metadata for the global editors."""
        return {
            "value": self.api_type,
            "label": self.display_name,
            "protocol": self.protocol,
            "urlPolicy": self.url_policy,
            "usesModelName": self.uses_model_name,
            "requiresApiVersion": self.requires_api_version,
            "versionField": self.version_field,
            "defaultVersion": self.default_version,
            "authTypes": list(self.auth_types),
            "defaultApiKeyHeader": self.default_api_key_header,
            "defaultApiKeyPrefix": self.default_api_key_prefix,
            "description": self.description,
        }


MODEL_ENDPOINT_PROVIDERS = (
    ModelEndpointProvider(
        api_type=MODEL_ENDPOINT_API_TYPE_OPENAI,
        display_name="OpenAI API",
        protocol=MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
        model_identifier=MODEL_IDENTIFIER_MODEL_NAME,
        url_policy=URL_POLICY_APPEND_V1_IF_MISSING,
        supports_stream_options=True,
        description="OpenAI or an OpenAI-compatible gateway. Compatibility alone does not grant image capabilities.",
    ),
    ModelEndpointProvider(
        api_type=MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
        display_name="Azure OpenAI API",
        protocol=MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
        model_identifier=MODEL_IDENTIFIER_DEPLOYMENT_NAME,
        url_policy=URL_POLICY_AZURE_DEPLOYMENT,
        default_api_key_header="api-key",
        default_api_key_prefix="",
        requires_api_version=True,
        version_field="api_version",
        description="Azure OpenAI addressed by deployment name and an explicit API version.",
    ),
    ModelEndpointProvider(
        api_type=MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
        display_name="Anthropic",
        protocol=MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
        model_identifier=MODEL_IDENTIFIER_MODEL_NAME,
        url_policy=URL_POLICY_ANTHROPIC_MESSAGES,
        default_api_key_header="x-api-key",
        default_api_key_prefix="",
        version_field="anthropic_version",
        default_version=DEFAULT_ANTHROPIC_VERSION,
        description="Anthropic's messages API, direct or through a compatible gateway.",
    ),
    ModelEndpointProvider(
        api_type=MODEL_ENDPOINT_API_TYPE_GEMINI,
        display_name="Google Gemini (OpenAI-compatible)",
        protocol=MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
        model_identifier=MODEL_IDENTIFIER_MODEL_NAME,
        url_policy=URL_POLICY_AS_GIVEN,
        description="Gemini's OpenAI-compatible base, normally https://generativelanguage.googleapis.com/v1beta/openai/.",
    ),
)
MODEL_ENDPOINT_PROVIDERS_BY_API_TYPE = {
    provider.api_type: provider for provider in MODEL_ENDPOINT_PROVIDERS
}
MODEL_ENDPOINT_CUSTOM_API_TYPES = frozenset(MODEL_ENDPOINT_PROVIDERS_BY_API_TYPE)


def normalize_api_type_value(api_type: Any) -> str:
    return str(api_type or "").strip().lower().replace("-", "_")


def get_model_endpoint_provider(api_type: Any) -> ModelEndpointProvider | None:
    return MODEL_ENDPOINT_PROVIDERS_BY_API_TYPE.get(normalize_api_type_value(api_type))


def get_model_endpoint_provider_ui_options() -> list[dict]:
    return [provider.to_ui_option() for provider in MODEL_ENDPOINT_PROVIDERS]


def is_supported_custom_api_type(api_type: Any) -> bool:
    return normalize_api_type_value(api_type) in MODEL_ENDPOINT_CUSTOM_API_TYPES
