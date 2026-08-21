# functions_outbound_http.py
"""Outbound HTTP policy for user-configured public API destinations."""

import ipaddress
import socket
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import requests


OUTBOUND_HTTP_MAX_URL_LENGTH = 4096
OUTBOUND_HTTP_MAX_REDIRECTS = 5
OUTBOUND_HTTP_ALLOWED_METHODS = {"DELETE", "GET", "HEAD", "PATCH", "POST", "PUT"}
OUTBOUND_HTTP_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
}
OUTBOUND_HTTP_BLOCKED_HOSTNAME_SUFFIXES = (
    ".internal",
    ".local",
    ".localhost",
)


class OutboundHttpPolicyError(ValueError):
    """Raised when an outbound destination violates the public HTTPS policy."""


def _normalize_public_hostname(hostname: Any) -> str:
    normalized_hostname = str(hostname or "").strip().lower().rstrip(".")
    if not normalized_hostname:
        raise OutboundHttpPolicyError("Outbound API URLs require a hostname.")
    try:
        normalized_hostname = normalized_hostname.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise OutboundHttpPolicyError("Outbound API URLs require a valid hostname.") from error

    if (
        normalized_hostname in OUTBOUND_HTTP_BLOCKED_HOSTNAMES
        or any(normalized_hostname.endswith(suffix) for suffix in OUTBOUND_HTTP_BLOCKED_HOSTNAME_SUFFIXES)
        or "." not in normalized_hostname
    ):
        raise OutboundHttpPolicyError("Outbound API URLs cannot target local or internal hostnames.")

    try:
        ipaddress.ip_address(normalized_hostname.strip("[]"))
    except ValueError:
        return normalized_hostname
    raise OutboundHttpPolicyError("Outbound API URLs cannot use IP address literals.")


def _assert_public_hostname_resolution(hostname: str) -> None:
    try:
        address_info = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise OutboundHttpPolicyError("The outbound API hostname could not be resolved.") from error
    if not address_info:
        raise OutboundHttpPolicyError("The outbound API hostname did not resolve to an address.")

    for address in address_info:
        try:
            resolved_address = ipaddress.ip_address(address[4][0])
        except ValueError as error:
            raise OutboundHttpPolicyError("The outbound API hostname resolved to an invalid address.") from error
        if not resolved_address.is_global:
            raise OutboundHttpPolicyError(
                "Outbound API URLs cannot resolve to private, local, reserved, or metadata addresses."
            )


def _url_origin(url: str) -> str:
    parsed_url = urlsplit(url)
    return f"{parsed_url.scheme}://{parsed_url.hostname}"


def normalize_public_https_url(
    value: Any,
    *,
    resolve_dns: bool = True,
    required_origin: Optional[str] = None,
) -> str:
    """Return a canonical public HTTPS URL, or raise ``OutboundHttpPolicyError``."""
    raw_url = str(value or "").strip()
    if not raw_url or len(raw_url) > OUTBOUND_HTTP_MAX_URL_LENGTH:
        raise OutboundHttpPolicyError("Outbound API URLs must be between 1 and 4096 characters.")

    parsed_url = urlsplit(raw_url)
    try:
        parsed_port = parsed_url.port
    except ValueError as error:
        raise OutboundHttpPolicyError("Outbound API URLs contain an invalid port.") from error

    hostname = _normalize_public_hostname(parsed_url.hostname)
    if (
        parsed_url.scheme.lower() != "https"
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_port not in (None, 443)
        or parsed_url.fragment
    ):
        raise OutboundHttpPolicyError(
            "Outbound API URLs must use HTTPS port 443 without credentials or fragments."
        )

    if "\\" in raw_url or any(character in raw_url for character in ("\r", "\n", "\x00")):
        raise OutboundHttpPolicyError("Outbound API URLs contain unsafe characters.")

    path_parts = [part for part in parsed_url.path.split("/") if part]
    decoded_path_parts = []
    for path_part in path_parts:
        decoded_part = path_part
        for _ in range(3):
            next_decoded_part = unquote(decoded_part)
            if next_decoded_part == decoded_part:
                break
            decoded_part = next_decoded_part
        decoded_path_parts.append(decoded_part)
    if any(part in {".", ".."} for part in decoded_path_parts):
        raise OutboundHttpPolicyError("Outbound API URLs cannot contain traversal path segments.")

    normalized_url = urlunsplit(("https", hostname, parsed_url.path or "/", parsed_url.query, ""))
    normalized_origin = _url_origin(normalized_url)
    if required_origin and normalized_origin != required_origin:
        raise OutboundHttpPolicyError("Outbound API redirects cannot change destination origin.")
    if resolve_dns:
        _assert_public_hostname_resolution(hostname)
    return normalized_url


def normalize_same_origin_https_url(value: Any, trusted_base_url: Any) -> str:
    """Return an HTTPS URL constrained to a trusted service origin and base path."""
    raw_url = str(value or "").strip()
    raw_base_url = str(trusted_base_url or "").strip().rstrip("/")
    if not raw_url or not raw_base_url:
        raise OutboundHttpPolicyError("Service URLs and their trusted base URL are required.")

    parsed_url = urlsplit(raw_url)
    parsed_base_url = urlsplit(raw_base_url)
    try:
        url_port = parsed_url.port
        base_port = parsed_base_url.port
    except ValueError as error:
        raise OutboundHttpPolicyError("Service URLs contain an invalid port.") from error

    if (
        parsed_base_url.scheme.lower() != "https"
        or parsed_url.scheme.lower() != "https"
        or not parsed_base_url.hostname
        or not parsed_url.hostname
        or parsed_url.hostname.lower() != parsed_base_url.hostname.lower()
        or (url_port or 443) != (base_port or 443)
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.fragment
    ):
        raise OutboundHttpPolicyError("Service URLs must remain on the configured HTTPS origin.")

    base_path = parsed_base_url.path.rstrip("/")
    candidate_path = parsed_url.path or "/"
    if base_path and candidate_path != base_path and not candidate_path.startswith(f"{base_path}/"):
        raise OutboundHttpPolicyError("Service URLs must remain under the configured API base path.")

    canonical_host = parsed_base_url.hostname.lower()
    canonical_netloc = canonical_host if (base_port or 443) == 443 else f"{canonical_host}:{base_port}"
    return urlunsplit(("https", canonical_netloc, candidate_path, parsed_url.query, ""))


def request_public_https(
    method: Any,
    url: Any,
    *,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    auth: Any = None,
    data: Any = None,
    json: Any = None,
    timeout: Any = 30,
    stream: bool = False,
    max_redirects: int = OUTBOUND_HTTP_MAX_REDIRECTS,
    session: Any = None,
):
    """Send an HTTP request after validating the destination and every redirect hop."""
    normalized_method = str(method or "GET").strip().upper()
    if normalized_method not in OUTBOUND_HTTP_ALLOWED_METHODS:
        raise OutboundHttpPolicyError("The outbound API request method is not supported.")

    current_url = normalize_public_https_url(url)
    required_origin = _url_origin(current_url)
    request_session = session or requests.Session()
    owns_session = session is None
    if owns_session:
        request_session.trust_env = False

    current_params = params
    current_data = data
    current_json = json
    try:
        for redirect_count in range(max(0, int(max_redirects)) + 1):
            # The destination and redirect chain are validated immediately before this sink.
            # codeql[py/full-ssrf]
            response = request_session.request(
                normalized_method,
                current_url,
                headers=headers,
                params=current_params,
                auth=auth,
                data=current_data,
                json=current_json,
                timeout=timeout,
                stream=stream,
                allow_redirects=False,
            )
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            if redirect_count >= max_redirects:
                raise OutboundHttpPolicyError("The outbound API exceeded the redirect limit.")

            redirect_location = str(response.headers.get("Location") or "").strip()
            response_url = str(response.url or current_url)
            response.close()
            if not redirect_location:
                raise OutboundHttpPolicyError("The outbound API returned a redirect without a location.")
            redirect_url = urljoin(response_url, redirect_location)
            current_url = normalize_public_https_url(
                redirect_url,
                required_origin=required_origin,
            )
            current_params = None
            if response.status_code == 303 or (
                response.status_code in {301, 302} and normalized_method == "POST"
            ):
                normalized_method = "GET"
                current_data = None
                current_json = None
    finally:
        if owns_session:
            request_session.close()

    raise OutboundHttpPolicyError("The outbound API request could not be completed.")
