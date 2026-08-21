#!/usr/bin/env python3
# test_outbound_http_ssrf_policy.py
"""
Functional test for outbound HTTP SSRF prevention.
Version: 0.260.029
Implemented in: 0.260.029

This test ensures user-configured API requests only reach public HTTPS destinations,
revalidate DNS before each request, and never forward credentials across origins.
"""

import socket
import sys
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from functions_outbound_http import (  # noqa: E402
    OutboundHttpPolicyError,
    normalize_public_https_url,
    normalize_same_origin_https_url,
    request_public_https,
)


def _address_info(*addresses):
    return [
        (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
        for address in addresses
    ]


class _FakeResponse:
    def __init__(self, status_code=200, url="https://api.example.com/", location=""):
        self.status_code = status_code
        self.url = url
        self.headers = {"Location": location} if location else {}
        self.closed = False

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


def test_version_contract():
    assert_app_version_at_least("0.260.029")


def test_structural_url_policy():
    assert normalize_public_https_url(
        "https://api.example.com/v1?limit=2",
        resolve_dns=False,
    ) == "https://api.example.com/v1?limit=2"

    rejected_urls = (
        "http://api.example.com",
        "https://user:password@api.example.com",
        "https://api.example.com:8443",
        "https://127.0.0.1",
        "https://localhost",
        "https://metadata.google.internal",
        "https://api.example.com/%2e%2e/metadata",
        "https://api.example.com/%252e%252e/metadata",
        "https://api.example.com/\\metadata",
        "https://api.example.com/#fragment",
    )
    for rejected_url in rejected_urls:
        try:
            normalize_public_https_url(rejected_url, resolve_dns=False)
        except OutboundHttpPolicyError:
            continue
        raise AssertionError(f"Outbound URL should have been rejected: {rejected_url}")


def test_dns_policy_rejects_any_non_public_answer():
    with patch("functions_outbound_http.socket.getaddrinfo", return_value=_address_info("93.184.216.34")):
        normalize_public_https_url("https://api.example.com")

    for addresses in (
        ("127.0.0.1",),
        ("169.254.169.254",),
        ("10.1.2.3",),
        ("93.184.216.34", "10.1.2.3"),
        ("::1",),
    ):
        with patch("functions_outbound_http.socket.getaddrinfo", return_value=_address_info(*addresses)):
            try:
                normalize_public_https_url("https://api.example.com")
            except OutboundHttpPolicyError:
                continue
        raise AssertionError(f"DNS answers should have been rejected: {addresses}")


def test_same_origin_service_policy():
    trusted_graph_base = "https://graph.microsoft.com/v1.0"
    assert normalize_same_origin_https_url(
        "https://graph.microsoft.com/v1.0/users?$top=5",
        trusted_graph_base,
    ) == "https://graph.microsoft.com/v1.0/users?$top=5"

    for rejected_url in (
        "https://attacker.example/v1.0/users",
        "https://graph.microsoft.com/beta/users",
        "http://graph.microsoft.com/v1.0/users",
        "https://user:password@graph.microsoft.com/v1.0/users",
    ):
        try:
            normalize_same_origin_https_url(rejected_url, trusted_graph_base)
        except OutboundHttpPolicyError:
            continue
        raise AssertionError(f"Cross-origin service URL should have been rejected: {rejected_url}")


def test_request_policy_allows_same_origin_redirects():
    fake_session = _FakeSession([
        _FakeResponse(302, "https://api.example.com/start", "/v2"),
        _FakeResponse(200, "https://api.example.com/v2"),
    ])
    with patch("functions_outbound_http.socket.getaddrinfo", return_value=_address_info("93.184.216.34")):
        response = request_public_https(
            "GET",
            "https://api.example.com/start",
            headers={"Authorization": "Bearer secret"},
            session=fake_session,
        )

    assert response.status_code == 200
    assert len(fake_session.requests) == 2
    assert fake_session.requests[1][1] == "https://api.example.com/v2"
    assert fake_session.requests[1][2]["headers"]["Authorization"] == "Bearer secret"
    assert all(request[2]["allow_redirects"] is False for request in fake_session.requests)


def test_request_policy_blocks_cross_origin_redirects_before_credentials_are_sent():
    fake_session = _FakeSession([
        _FakeResponse(302, "https://api.example.com/start", "https://attacker.example/steal"),
    ])
    with patch("functions_outbound_http.socket.getaddrinfo", return_value=_address_info("93.184.216.34")):
        try:
            request_public_https(
                "GET",
                "https://api.example.com/start",
                headers={"Authorization": "Bearer secret"},
                session=fake_session,
            )
        except OutboundHttpPolicyError:
            pass
        else:
            raise AssertionError("Cross-origin redirect should have been rejected.")

    assert len(fake_session.requests) == 1


if __name__ == "__main__":
    tests = [
        test_version_contract,
        test_structural_url_policy,
        test_dns_policy_rejects_any_non_public_answer,
        test_same_origin_service_policy,
        test_request_policy_allows_same_origin_redirects,
        test_request_policy_blocks_cross_origin_redirects_before_credentials_are_sent,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as error:
            print(f"FAIL {test.__name__}: {error}")
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
