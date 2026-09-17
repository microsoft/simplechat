# functions_model_endpoint_validation.py
"""Configuration and outbound-address validation for Custom model endpoints."""

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlparse, urlunparse

from functions_model_endpoint_providers import (
    AUTH_TYPE_API_KEY,
    AUTH_TYPE_BEARER,
    AUTH_TYPE_OAUTH2_CLIENT_CREDENTIALS,
    CUSTOM_ENDPOINT_URL_MODES,
    get_model_endpoint_provider,
    normalize_custom_endpoint_auth_type,
)
from functions_model_endpoint_types import (
    MODEL_ENDPOINT_PROVIDER_CUSTOM,
    ModelEndpointValidationError,
    custom_endpoint_validation_view,
    get_model_endpoint_api_type,
    resolve_model_endpoint_request_model,
)


CUSTOM_ENDPOINT_MAX_URL_LENGTH = 2048
CUSTOM_ENDPOINT_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
CUSTOM_ENDPOINT_HEADER_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
CUSTOM_ENDPOINT_BLOCKED_HEADERS = {
    "host", "content-length", "connection", "transfer-encoding",
    "cookie", "set-cookie", "upgrade", "trailer", "te",
}
CUSTOM_ENDPOINT_BLOCKED_HOSTNAMES = {
    "instance-data.ec2.internal", "localhost", "localhost.localdomain",
    "metadata.azure.com", "metadata.google.internal",
}
CUSTOM_ENDPOINT_BLOCKED_IPS = {
    ipaddress.ip_address(value)
    for value in ("168.63.129.16", "169.254.169.254", "169.254.169.250", "169.254.169.251")
}
CUSTOM_ENDPOINT_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)


class ModelEndpointUnresolvableError(ModelEndpointValidationError):
    """DNS is unavailable; saving is allowed, but a request must fail closed."""


def custom_endpoint_setting_enabled(settings: dict | None, key: str) -> bool:
    """Do not treat a serialized false value as permission to widen network access."""
    return (settings or {}).get(key) is True


def validate_custom_model_endpoint_address(address: str, *, allow_private: bool = False) -> None:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise ModelEndpointValidationError("Custom endpoint resolved to an invalid address.") from exc
    if isinstance(parsed, ipaddress.IPv6Address) and (parsed.ipv4_mapped or parsed.sixtofour or parsed.teredo):
        raise ModelEndpointValidationError("Custom endpoint must not use an IPv4 transition address.")
    if parsed in CUSTOM_ENDPOINT_BLOCKED_IPS:
        raise ModelEndpointValidationError("Custom endpoint resolves to a blocked platform address.")
    if parsed.is_loopback or parsed.is_link_local:
        raise ModelEndpointValidationError("Custom endpoint must not use a loopback or link-local address.")
    if parsed.is_multicast or parsed.is_reserved or parsed.is_unspecified:
        raise ModelEndpointValidationError("Custom endpoint must resolve to a usable network address.")
    if any(parsed in network for network in CUSTOM_ENDPOINT_PRIVATE_NETWORKS if network.version == parsed.version):
        if not allow_private:
            raise ModelEndpointValidationError("Private Custom endpoint hosts are not enabled by the administrator.")
        return
    if not parsed.is_global:
        raise ModelEndpointValidationError("Custom endpoint must resolve to a globally routable address.")


def resolve_custom_model_endpoint_addresses(
    hostname: str, port: int = 443, *, allow_private: bool = False,
) -> tuple[str, ...]:
    """Validate every answer, then return exactly the addresses a transport may use."""
    try:
        answers = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ModelEndpointUnresolvableError("Custom endpoint hostname could not be resolved.") from exc
    if not answers:
        raise ModelEndpointUnresolvableError("Custom endpoint hostname did not resolve to an address.")
    addresses = []
    for answer in answers:
        address = answer[4][0]
        validate_custom_model_endpoint_address(address, allow_private=allow_private)
        if address not in addresses:
            addresses.append(address)
    return tuple(addresses)


def validate_custom_model_endpoint_url(
    endpoint: Any,
    *,
    allow_private: bool = False,
    allow_insecure: bool = False,
    require_resolvable: bool = True,
) -> str:
    """Normalize an administrator URL; connect-time DNS pinning remains mandatory."""
    text = str(endpoint or "").strip()
    if not text or len(text) > CUSTOM_ENDPOINT_MAX_URL_LENGTH:
        raise ModelEndpointValidationError("Custom endpoint URL is required and must not exceed 2048 characters.")
    if any(ord(character) < 33 for character in text) or "\\" in text:
        raise ModelEndpointValidationError("Custom endpoint URL contains invalid characters.")
    try:
        parsed = urlparse(text)
        port = parsed.port
        hostname = str(parsed.hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise ModelEndpointValidationError("Custom endpoint URL is invalid.") from exc
    if parsed.scheme != "https":
        if parsed.scheme != "http" or not (allow_private and allow_insecure):
            raise ModelEndpointValidationError(
                "Custom endpoint URL must use HTTPS. HTTP requires both private-host and insecure-endpoint permission."
            )
    if not parsed.netloc or not hostname or port == 0:
        raise ModelEndpointValidationError("Custom endpoint URL must include a valid hostname and port.")
    if parsed.username is not None or parsed.password is not None:
        raise ModelEndpointValidationError("Custom endpoint URL must not contain credentials.")
    if parsed.query or parsed.fragment or parsed.params:
        raise ModelEndpointValidationError("Custom endpoint URL must not contain query parameters or a fragment.")
    if "%" in hostname:
        raise ModelEndpointValidationError("Custom endpoint hostname is invalid.")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ModelEndpointValidationError("Custom endpoint hostname is invalid.") from exc
    if hostname in CUSTOM_ENDPOINT_BLOCKED_HOSTNAMES or hostname.endswith(".localhost"):
        raise ModelEndpointValidationError("Custom endpoint hostname is blocked.")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not allow_private:
            raise ModelEndpointValidationError("Custom endpoint IP addresses require private-host permission.")
        validate_custom_model_endpoint_address(hostname, allow_private=allow_private)
    else:
        if not re.fullmatch(r"[a-z0-9.-]+", hostname) or ".." in hostname:
            raise ModelEndpointValidationError("Custom endpoint hostname is invalid.")
        if not allow_private and ("." not in hostname or hostname.endswith((".internal", ".local"))):
            raise ModelEndpointValidationError("Custom endpoint must use a public fully qualified hostname.")
        try:
            resolve_custom_model_endpoint_addresses(
                hostname, port or (443 if parsed.scheme == "https" else 80), allow_private=allow_private,
            )
        except ModelEndpointUnresolvableError:
            if require_resolvable:
                raise
    netloc = f"[{hostname}]" if literal is not None and literal.version == 6 else hostname
    if port and port != (443 if parsed.scheme == "https" else 80):
        netloc = f"{netloc}:{port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", "")).rstrip("/")


def validate_custom_api_key_header(auth: dict) -> None:
    """Prevent auth overrides from altering routing or HTTP message framing."""
    name = str(auth.get("api_key_header") or "").strip()
    prefix = str(auth.get("api_key_prefix") or "")
    if name and (
        not CUSTOM_ENDPOINT_HEADER_PATTERN.fullmatch(name)
        or name.lower() in CUSTOM_ENDPOINT_BLOCKED_HEADERS
        or name.lower().startswith("proxy-")
    ):
        raise ModelEndpointValidationError("Custom API key header is not an allowed authentication header.")
    if any(ord(character) < 32 or ord(character) > 126 for character in prefix):
        raise ModelEndpointValidationError("Custom API key prefix contains invalid characters.")


def validate_custom_model_endpoint(
    endpoint: Any, settings: dict | None = None, *, require_api_key: bool = True,
) -> None:
    """Validate a normalized record without requiring the deployment to be reachable."""
    if not isinstance(endpoint, dict):
        raise ModelEndpointValidationError("Custom endpoint configuration must be an object.")
    endpoint = custom_endpoint_validation_view(endpoint)
    if str(endpoint.get("provider") or "").strip().lower() != MODEL_ENDPOINT_PROVIDER_CUSTOM:
        return
    if not str(endpoint.get("name") or "").strip():
        raise ModelEndpointValidationError("Custom endpoint name is required.")
    provider = get_model_endpoint_provider(get_model_endpoint_api_type(endpoint))
    if provider is None:
        raise ModelEndpointValidationError("Custom endpoint API type is not supported.")
    auth = endpoint.get("auth") or {}
    connection = endpoint.get("connection") or {}
    if not isinstance(auth, dict) or not isinstance(connection, dict):
        raise ModelEndpointValidationError("Custom endpoint authentication and connection must be objects.")
    auth_type = normalize_custom_endpoint_auth_type(auth.get("type"))
    if auth_type not in provider.auth_types:
        raise ModelEndpointValidationError("Custom endpoints require API key, bearer token, or OAuth2 authentication.")
    validate_custom_api_key_header(auth)
    if require_api_key:
        required_fields = {
            AUTH_TYPE_API_KEY: ("api_key",),
            AUTH_TYPE_BEARER: ("bearer_token",),
            AUTH_TYPE_OAUTH2_CLIENT_CREDENTIALS: ("token_url", "client_id", "client_secret"),
        }[auth_type]
        if not all(str(auth.get(field) or "").strip() for field in required_fields):
            raise ModelEndpointValidationError("The selected Custom authentication scheme requires its credentials.")
    allow_private = custom_endpoint_setting_enabled(settings, "allow_private_custom_model_endpoints")
    allow_insecure = custom_endpoint_setting_enabled(settings, "allow_insecure_custom_model_endpoints")
    connection["endpoint"] = validate_custom_model_endpoint_url(
        connection.get("endpoint"), allow_private=allow_private,
        allow_insecure=allow_insecure, require_resolvable=False,
    )
    embedding_operation = (connection.get("operation_settings") or {}).get("embeddings") or {}
    if isinstance(embedding_operation, dict) and embedding_operation.get("endpoint"):
        validate_custom_model_endpoint_url(
            embedding_operation["endpoint"], allow_private=allow_private,
            allow_insecure=allow_insecure, require_resolvable=False,
        )
    endpoint["connection"] = connection
    if connection.get("url_mode", "auto") not in CUSTOM_ENDPOINT_URL_MODES:
        raise ModelEndpointValidationError("Custom endpoint URL mode must be auto or exact.")
    if connection.get("client_key_path") and not connection.get("client_cert_path"):
        raise ModelEndpointValidationError("A Custom client key requires a client certificate.")
    for field in ("client_cert_path", "client_key_path"):
        if field in connection and not isinstance(connection[field], str):
            raise ModelEndpointValidationError("Custom certificate paths must be text.")
    if auth_type == AUTH_TYPE_OAUTH2_CLIENT_CREDENTIALS:
        if not auth.get("token_url") or not auth.get("client_id"):
            raise ModelEndpointValidationError("Custom OAuth2 requires a token URL and client ID.")
        validate_custom_model_endpoint_url(
            auth["token_url"], allow_private=allow_private,
            allow_insecure=allow_insecure, require_resolvable=False,
        )
    if provider.version_field:
        version = connection.get(provider.version_field) or provider.default_version
        if provider.requires_api_version or version:
            if not CUSTOM_ENDPOINT_VERSION_PATTERN.fullmatch(str(version or "")):
                raise ModelEndpointValidationError("Custom API version must contain letters, numbers, dots, underscores, or hyphens.")
    models = endpoint.get("models")
    if not isinstance(models, list) or not models:
        raise ModelEndpointValidationError("Custom endpoints require at least one manually configured model.")
    seen = set()
    for model in models:
        request_model = resolve_model_endpoint_request_model(endpoint, model)
        if not isinstance(model, dict) or not request_model:
            field = "Model Name" if provider.uses_model_name else "Deployment Name"
            raise ModelEndpointValidationError(f"Custom endpoint models require {field}.")
        if len(request_model) > 512 or any(ord(character) < 32 for character in request_model):
            raise ModelEndpointValidationError("Custom request model identifier is invalid.")
        if request_model.casefold() in seen:
            raise ModelEndpointValidationError("Custom request model identifiers must be unique.")
        seen.add(request_model.casefold())


def validate_custom_model_endpoints(
    endpoints: Any, settings: dict | None = None, *, require_api_key: bool = True,
) -> None:
    if not isinstance(endpoints, list):
        raise ModelEndpointValidationError("Model endpoints must be a list.")
    for endpoint in endpoints:
        validate_custom_model_endpoint(endpoint, settings, require_api_key=require_api_key)
