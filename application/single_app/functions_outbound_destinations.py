# functions_outbound_destinations.py
"""Bootstrap-free destination rules for user-configurable action connections."""

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from functions_action_manifest import resolve_action_type


_SCHEME_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}
_METADATA_ADDRESSES = frozenset({
    ipaddress.ip_address("168.63.129.16"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("fd00:ec2::254"),
})
_THIS_NETWORK = ipaddress.ip_network("0.0.0.0/8")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_HOST_LABEL = re.compile(r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?")
_NUMERIC_HOST = re.compile(r"(?:[0-9.]+|0x[0-9a-f]+)", re.IGNORECASE)
_HTTP_ACTION_TYPES = {
    "openapi", "rocksdb", "yamcs", "tableau", "databricks", "azure_maps_openlayers", "azure_function", "mcp",
}


class OutboundDestinationError(ValueError):
    """A stable, non-secret action connection policy error."""

    def __init__(self, message):
        super().__init__(message)
        self.public_message = message


@dataclass(frozen=True)
class OutboundTarget:
    url: str
    scheme: str
    host: str
    port: int

    @property
    def origin(self):
        return self.scheme, self.host, self.port


def validate_outbound_address(value):
    """Allow enterprise private routing, but never local/infrastructure targets."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise OutboundDestinationError("The action destination has an invalid IP address.") from exc

    if address in _METADATA_ADDRESSES:
        raise OutboundDestinationError("Cloud infrastructure destinations are not permitted for actions.")
    if isinstance(address, ipaddress.IPv6Address):
        embedded = address.ipv4_mapped or address.sixtofour
        if address in _NAT64:
            embedded = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
        if address.teredo:
            for teredo_address in address.teredo:
                validate_outbound_address(str(teredo_address))
        if embedded is not None:
            validate_outbound_address(str(embedded))
            return
    if (
        address.is_loopback or address.is_link_local or address.is_unspecified
        or address.is_multicast or address.is_reserved
        or (isinstance(address, ipaddress.IPv4Address) and address in _THIS_NETWORK)
    ):
        raise OutboundDestinationError(
            "Localhost, loopback, link-local and reserved destinations are not permitted for actions."
        )


def _normalize_host(value):
    host = value.lower()
    if host.endswith("..") or "%" in host:
        raise OutboundDestinationError("The action destination has an invalid hostname.")
    host = host.removesuffix(".")
    if host == "localhost" or host.endswith(".localhost") or host == "localhost.localdomain":
        raise OutboundDestinationError("Localhost destinations are not permitted for actions.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if _NUMERIC_HOST.fullmatch(host):
            raise OutboundDestinationError("Noncanonical numeric action destinations are not permitted.")
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise OutboundDestinationError("The action destination has an invalid hostname.") from exc
        if len(host) > 253 or not all(_HOST_LABEL.fullmatch(label) for label in host.split(".")):
            raise OutboundDestinationError("The action destination has an invalid hostname.")
    else:
        validate_outbound_address(str(address))
        host = str(address)
    return host


def normalize_outbound_url(value):
    """Validate URL structure and literal destinations without performing DNS."""
    if not isinstance(value, str) or not value.strip() or len(value) > 8192:
        raise OutboundDestinationError("An HTTP or remote MCP service URL is required.")
    value = value.strip()
    if "\\" in value or any(ord(character) <= 32 or ord(character) == 127 for character in value):
        raise OutboundDestinationError("The action destination URL is invalid.")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() not in _SCHEME_PORTS or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
        ):
            raise OutboundDestinationError("The action destination URL or scheme is not permitted.")
        host = _normalize_host(parsed.hostname)
        scheme = parsed.scheme.lower()
        port = parsed.port if parsed.port is not None else _SCHEME_PORTS[scheme]
    except ValueError as exc:
        if isinstance(exc, OutboundDestinationError):
            raise
        raise OutboundDestinationError("The action destination URL is invalid.") from exc
    if not 1 <= port <= 65535:
        raise OutboundDestinationError("The action destination port is invalid.")
    authority = f"[{host}]" if ":" in host else host
    if port != _SCHEME_PORTS[scheme]:
        authority = f"{authority}:{port}"
    return OutboundTarget(
        urlunsplit((scheme, authority, parsed.path or "/", parsed.query, "")), scheme, host, port,
    )


def resolve_outbound_addresses(host, port):
    """Resolve all candidates once; callers must connect to a returned numeric IP."""
    host = _normalize_host(host)
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise OutboundDestinationError("The action destination could not be resolved.") from exc
    result = []
    for family, _, _, _, sockaddr in addresses:
        if family not in (socket.AF_INET, socket.AF_INET6):
            raise OutboundDestinationError("The action destination address family is not supported.")
        address = sockaddr[0]
        validate_outbound_address(address)
        if address not in result:
            result.append(address)
    if not result:
        raise OutboundDestinationError("The action destination did not resolve to a usable address.")
    return tuple(result)


def validate_outbound_redirect(source, location):
    """Permit same-origin redirects and default-port TLS upgrades, never retargeting."""
    before = normalize_outbound_url(source)
    after = normalize_outbound_url(urljoin(before.url, location))
    tls_upgrade = (
        before.scheme in {"http", "ws"} and after.scheme == f"{before.scheme}s"
        and before.host == after.host and before.port == 80 and after.port == 443
    )
    if before.origin != after.origin and not tls_upgrade:
        raise OutboundDestinationError(
            "Cross-origin action redirects are not permitted. Configure the final service URL."
        )
    return after.url


def validate_outbound_headers(url, headers):
    target = normalize_outbound_url(str(url))
    authority = f"[{target.host}]" if ":" in target.host else target.host
    if target.port != _SCHEME_PORTS[target.scheme]:
        authority = f"{authority}:{target.port}"
    for name, value in (headers or {}).items():
        if name.lower() == "host":
            if any(character in str(value) for character in "/?#@\\"):
                raise OutboundDestinationError("Action headers cannot override the destination authority.")
            supplied = normalize_outbound_url(f"{target.scheme}://{value}")
            if supplied.origin != target.origin or supplied.url != f"{target.scheme}://{authority}/":
                raise OutboundDestinationError("Action headers cannot override the destination authority.")
        if name.lower() == "proxy-authorization":
            raise OutboundDestinationError("Forward-proxy credentials cannot be supplied as action headers.")
    return target


def action_connection_signature(manifest):
    """Compare the effective connector and origin without resolving DNS or secrets."""
    plugin_type = resolve_action_type(manifest)
    fields = manifest.get("additionalFields", {})
    if not isinstance(fields, dict):
        raise OutboundDestinationError("Action additional fields must be an object.")
    endpoint = manifest.get("endpoint")
    if plugin_type == "rocksdb":
        endpoint = fields.get("base_url") or endpoint
    elif plugin_type == "openapi":
        endpoint = manifest.get("base_url") or endpoint or fields.get("base_url")
    elif plugin_type in {"yamcs", "tableau"}:
        endpoint = endpoint or fields.get("server_url") or fields.get("serverUrl")
        if endpoint and "://" not in endpoint:
            endpoint = f"https://{endpoint}"
    elif plugin_type in {"databricks", "databricks_table"}:
        endpoint = endpoint or fields.get("workspace_url") or fields.get("workspaceUrl")
        plugin_type = "databricks"
    elif plugin_type == "azure_maps_openlayers":
        endpoint = endpoint or "https://atlas.microsoft.com"
    if not endpoint:
        return plugin_type, None
    if not isinstance(endpoint, str):
        raise OutboundDestinationError("The action destination URL is invalid.")
    try:
        scheme = urlsplit(endpoint).scheme.lower()
    except ValueError as exc:
        raise OutboundDestinationError("The action destination URL is invalid.") from exc
    if scheme not in _SCHEME_PORTS:
        if plugin_type in _HTTP_ACTION_TYPES:
            raise OutboundDestinationError("This action requires an HTTP or remote MCP service URL.")
        return plugin_type, None
    return plugin_type, normalize_outbound_url(endpoint).origin
