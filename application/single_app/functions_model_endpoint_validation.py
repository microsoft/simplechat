# functions_model_endpoint_validation.py
"""Validation and outbound-network safety for Custom model endpoints."""

import ipaddress
import re
import socket
from typing import Any, Dict, Iterable
from urllib.parse import urlparse, urlunparse

from functions_model_endpoint_providers import get_model_endpoint_provider
from functions_model_endpoint_types import (
    DEFAULT_ANTHROPIC_VERSION,
    MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
    MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
    MODEL_ENDPOINT_PROVIDER_CUSTOM,
    get_model_endpoint_api_type,
    resolve_model_endpoint_request_model,
)


CUSTOM_ENDPOINT_MAX_URL_LENGTH = 2048
CUSTOM_ENDPOINT_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
CUSTOM_ENDPOINT_BLOCKED_HOSTNAMES = {
    "instance-data.ec2.internal",
    "localhost",
    "localhost.localdomain",
    "metadata.azure.com",
    "metadata.google.internal",
}
CUSTOM_ENDPOINT_BLOCKED_IPS = {
    ipaddress.ip_address("168.63.129.16"),
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.169.250"),
    ipaddress.ip_address("169.254.169.251"),
}
CUSTOM_ENDPOINT_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)


class ModelEndpointValidationError(ValueError):
    """Raised when a model endpoint configuration violates the saved policy."""


class ModelEndpointUnresolvableError(ModelEndpointValidationError):
    """Raised when a Custom endpoint hostname cannot be resolved right now.

    This is distinct from a policy violation. A name that does not resolve yet is
    tolerable when saving configuration -- the environment may not be reachable
    from the application tier at configuration time -- but a policy violation
    never is.
    """


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


def validate_custom_model_endpoint_address(
    address: str,
    *,
    allow_private: bool = False,
) -> None:
    """Validate one resolved Custom endpoint address against the outbound policy."""
    try:
        ip_address = ipaddress.ip_address(address)
    except ValueError as exc:
        raise ModelEndpointValidationError(
            "Custom endpoint hostname resolved to an invalid address."
        ) from exc

    if ip_address in CUSTOM_ENDPOINT_BLOCKED_IPS:
        raise ModelEndpointValidationError(
            "Custom endpoint hostname resolves to a blocked platform address."
        )
    if ip_address.is_loopback:
        raise ModelEndpointValidationError(
            "Custom endpoint hostname must not resolve to a loopback address."
        )
    if ip_address.is_link_local:
        raise ModelEndpointValidationError(
            "Custom endpoint hostname must not resolve to a link-local address."
        )
    if ip_address.is_multicast or ip_address.is_reserved or ip_address.is_unspecified:
        raise ModelEndpointValidationError(
            "Custom endpoint hostname must resolve to a usable network address."
        )
    is_allowed_private_address = any(
        ip_address in private_network
        for private_network in CUSTOM_ENDPOINT_PRIVATE_NETWORKS
        if ip_address.version == private_network.version
    )
    if is_allowed_private_address:
        if not allow_private:
            raise ModelEndpointValidationError(
                "Private Custom endpoint hosts are not enabled by the administrator."
            )
        return
    if not ip_address.is_global:
        raise ModelEndpointValidationError(
            "Custom endpoint hostname must resolve to a globally routable address."
        )


def resolve_custom_model_endpoint_addresses(
    hostname: str,
    port: int = 443,
    *,
    allow_private: bool = False,
) -> tuple[str, ...]:
    """Resolve and validate every address before a Custom endpoint connection."""
    try:
        resolved_addresses = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ModelEndpointUnresolvableError(
            "Custom endpoint hostname could not be resolved."
        ) from exc

    if not resolved_addresses:
        raise ModelEndpointUnresolvableError(
            "Custom endpoint hostname did not resolve to an address."
        )

    validated_addresses = []
    seen_addresses = set()
    for address_info in resolved_addresses:
        address = address_info[4][0]
        validate_custom_model_endpoint_address(
            address,
            allow_private=allow_private,
        )
        if address not in seen_addresses:
            seen_addresses.add(address)
            validated_addresses.append(address)
    return tuple(validated_addresses)


def validate_custom_model_endpoint_url(
    endpoint: Any,
    *,
    allow_private: bool = False,
    allow_insecure: bool = False,
    require_resolvable: bool = True,
) -> str:
    """Validate and normalize a Custom endpoint URL before an outbound request.

    ``allow_private`` is the administrator's on-premises gate. With it enabled, an
    endpoint may be an IP literal, a single-label host, or a private-range
    address, because those are how on-premises inference is normally addressed.
    Connect-time address validation still applies on every request.

    ``require_resolvable`` is set to False on the configuration save path so that
    an endpoint can be configured, seeded, or restored from backup before the
    application tier can resolve it. The connect-time check is what actually
    protects the request, and it always runs.
    """
    endpoint_text = str(endpoint or "").strip()
    if not endpoint_text:
        raise ModelEndpointValidationError("Custom endpoint URL is required.")
    if len(endpoint_text) > CUSTOM_ENDPOINT_MAX_URL_LENGTH:
        raise ModelEndpointValidationError("Custom endpoint URL is too long.")

    try:
        parsed_endpoint = urlparse(endpoint_text)
        port = parsed_endpoint.port
    except ValueError as exc:
        raise ModelEndpointValidationError("Custom endpoint URL is invalid.") from exc

    scheme = parsed_endpoint.scheme.lower()
    if scheme == "http":
        if not (allow_private and allow_insecure):
            raise ModelEndpointValidationError(
                "Custom endpoint URL must use HTTPS. Plaintext HTTP requires the "
                "administrator to enable both private hosts and insecure endpoints."
            )
    elif scheme != "https":
        raise ModelEndpointValidationError("Custom endpoint URL must use HTTPS.")

    if not parsed_endpoint.netloc or not parsed_endpoint.hostname:
        raise ModelEndpointValidationError(
            "Custom endpoint URL must include a host name."
        )
    if parsed_endpoint.username or parsed_endpoint.password:
        raise ModelEndpointValidationError(
            "Custom endpoint URL must not include embedded credentials."
        )
    if parsed_endpoint.query or parsed_endpoint.fragment:
        raise ModelEndpointValidationError(
            "Custom endpoint URL must not include a query string or fragment."
        )

    hostname = parsed_endpoint.hostname.strip().lower().rstrip(".")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ModelEndpointValidationError(
            "Custom endpoint hostname is invalid."
        ) from exc

    if (
        hostname in CUSTOM_ENDPOINT_BLOCKED_HOSTNAMES
        or hostname.endswith(".localhost")
    ):
        raise ModelEndpointValidationError("Custom endpoint hostname is blocked.")

    is_ip_literal = _is_ip_literal(hostname)
    is_single_label = not is_ip_literal and "." not in hostname

    if is_ip_literal:
        if not allow_private:
            raise ModelEndpointValidationError(
                "Custom endpoint URL must use a fully qualified domain name. "
                "Enable private Custom endpoint hosts to use an IP address."
            )
        # An IP literal skips DNS entirely, so validate the address directly.
        validate_custom_model_endpoint_address(hostname, allow_private=True)
    elif is_single_label:
        if not allow_private:
            raise ModelEndpointValidationError(
                "Custom endpoint URL must use a fully qualified domain name. "
                "Enable private Custom endpoint hosts to use a short host name."
            )
    elif not allow_private and hostname.endswith((".internal", ".local")):
        raise ModelEndpointValidationError(
            "Private Custom endpoint hosts are not enabled by the administrator."
        )

    if not is_ip_literal:
        default_port = 80 if scheme == "http" else 443
        try:
            resolve_custom_model_endpoint_addresses(
                hostname,
                port or default_port,
                allow_private=allow_private,
            )
        except ModelEndpointUnresolvableError:
            # A name that does not resolve yet is only fatal when the caller needs
            # it resolvable now. Policy violations are a different exception and
            # always propagate. The connect-time check re-resolves on every
            # request, so nothing is skipped by tolerating this here.
            if require_resolvable:
                raise

    default_port = 80 if scheme == "http" else 443
    normalized_netloc = hostname
    if port and port != default_port:
        normalized_netloc = f"{hostname}:{port}"
    return urlunparse((
        scheme,
        normalized_netloc,
        parsed_endpoint.path or "",
        "",
        "",
        "",
    )).rstrip("/")


def _validate_version(value: Any, field_label: str) -> str:
    normalized_value = str(value or "").strip()
    if not CUSTOM_ENDPOINT_VERSION_PATTERN.fullmatch(normalized_value):
        raise ModelEndpointValidationError(
            f"{field_label} must contain only letters, numbers, dots, underscores, or hyphens."
        )
    return normalized_value


def validate_custom_model_endpoint(
    endpoint: Any,
    settings: Dict[str, Any] | None = None,
    *,
    require_api_key: bool = True,
) -> None:
    """Validate a normalized Custom endpoint record."""
    if not isinstance(endpoint, dict):
        raise ModelEndpointValidationError("Custom endpoint configuration is invalid.")
    if str(endpoint.get("provider") or "").strip().lower() != MODEL_ENDPOINT_PROVIDER_CUSTOM:
        return

    endpoint_name = str(endpoint.get("name") or "").strip()
    if not endpoint_name:
        raise ModelEndpointValidationError("Custom endpoint name is required.")

    api_type = get_model_endpoint_api_type(endpoint)
    if not api_type:
        raise ModelEndpointValidationError("Custom endpoint API type is not supported.")
    registered_provider = get_model_endpoint_provider(api_type)

    auth = endpoint.get("auth") if isinstance(endpoint.get("auth"), dict) else {}
    auth_type = str(auth.get("type") or "").strip().lower()
    if auth_type not in {"api_key", "key"}:
        raise ModelEndpointValidationError(
            "Custom endpoints support API key authentication only."
        )
    if require_api_key and not auth.get("api_key"):
        raise ModelEndpointValidationError("Custom endpoint API key is required.")

    connection = (
        endpoint.get("connection")
        if isinstance(endpoint.get("connection"), dict)
        else {}
    )
    endpoint_settings = settings or {}
    allow_private = bool(endpoint_settings.get("allow_private_custom_model_endpoints", False))
    allow_insecure = bool(endpoint_settings.get("allow_insecure_custom_model_endpoints", False))
    connection["endpoint"] = validate_custom_model_endpoint_url(
        connection.get("endpoint"),
        allow_private=allow_private,
        allow_insecure=allow_insecure,
        # Configuration may be saved before the application tier can resolve the
        # host, so saving does not require the name to resolve right now.
        require_resolvable=False,
    )

    if registered_provider is not None and registered_provider.version_field:
        version_value = connection.get(registered_provider.version_field)
        if registered_provider.default_version:
            version_value = version_value or registered_provider.default_version
        if registered_provider.requires_api_version or version_value:
            _validate_version(version_value, f"{registered_provider.display_name} version")

    seen_model_names = set()
    models: Iterable[Any] = endpoint.get("models") or []
    if not isinstance(models, list):
        raise ModelEndpointValidationError("Custom endpoint models must be a list.")
    if not models:
        raise ModelEndpointValidationError(
            "Custom endpoints require at least one manually configured model."
        )
    for model in models:
        if not isinstance(model, dict):
            raise ModelEndpointValidationError("Custom endpoint model configuration is invalid.")
        request_model = resolve_model_endpoint_request_model(endpoint, model)
        if not request_model:
            model_field = (
                "Model Name"
                if registered_provider is not None and registered_provider.uses_model_name
                else "Deployment Name"
            )
            raise ModelEndpointValidationError(
                f"Custom endpoint models require {model_field}."
            )
        normalized_model_name = request_model.casefold()
        if normalized_model_name in seen_model_names:
            raise ModelEndpointValidationError(
                "Custom endpoint model names must be unique."
            )
        seen_model_names.add(normalized_model_name)


def validate_custom_model_endpoints(
    endpoints: Any,
    settings: Dict[str, Any] | None = None,
    *,
    require_api_key: bool = True,
) -> None:
    """Validate every Custom endpoint in an endpoint list."""
    if not isinstance(endpoints, list):
        raise ModelEndpointValidationError("Model endpoints must be a list.")
    for endpoint in endpoints:
        validate_custom_model_endpoint(
            endpoint,
            settings,
            require_api_key=require_api_key,
        )
