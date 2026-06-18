# test_dlp_presidio_endpoint.py
#!/usr/bin/env python3
"""
Functional test for external Presidio endpoint DLP adapter.
Version: 0.242.075
Implemented in: 0.242.071

This test ensures SimpleChat can call a configured Presidio-compatible analyzer
endpoint without embedding Presidio packages or leaking raw scanned text.
"""

import os
import socket
import sys
from unittest.mock import Mock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
sys.path.insert(0, APP_DIR)


RAW_TEXT = "Contact me a@example.com"


def stub_dns_answers(monkeypatch, expected_host, addresses=None):
    """Return deterministic DNS answers for endpoint validation tests."""
    host_answers = expected_host if isinstance(expected_host, dict) else {expected_host: addresses}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        assert host in host_answers
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port or 443))
            for address in host_answers[host]
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_validate_presidio_endpoint_allows_https_and_localhost(monkeypatch):
    """Public HTTPS and explicitly allowlisted local HTTP endpoint URLs should be accepted."""
    from functions_dlp_presidio import validate_presidio_endpoint_url

    stub_dns_answers(
        monkeypatch,
        {
            "presidio.example.com": ["93.184.216.34"],
            "localhost": ["127.0.0.1"],
        },
    )

    assert validate_presidio_endpoint_url("https://presidio.example.com/analyze") == "https://presidio.example.com/analyze"
    assert (
        validate_presidio_endpoint_url("http://localhost:5002/analyze", "localhost")
        == "http://localhost:5002/analyze"
    )
    assert (
        validate_presidio_endpoint_url("http://127.0.0.1:5002/analyze", "127.0.0.1")
        == "http://127.0.0.1:5002/analyze"
    )
    assert validate_presidio_endpoint_url("http://[::1]:5002/analyze", "::1") == "http://[::1]:5002/analyze"


def test_validate_presidio_endpoint_rejects_private_hosts_without_allowlist():
    """Private, link-local, and loopback endpoints should require an explicit allowlist."""
    from functions_dlp_presidio import PresidioEndpointConfigurationError, validate_presidio_endpoint_url

    blocked_urls = [
        "https://127.0.0.1:5002/analyze",
        "https://[::1]:5002/analyze",
        "https://10.1.2.3/analyze",
        "https://172.16.0.10/analyze",
        "https://192.168.1.20/analyze",
        "https://169.254.169.254/metadata",
    ]

    for blocked_url in blocked_urls:
        try:
            validate_presidio_endpoint_url(blocked_url)
        except PresidioEndpointConfigurationError as exc:
            assert "allowlist" in str(exc).lower()
            continue

        raise AssertionError(f"Expected private endpoint to be rejected: {blocked_url}")


def test_validate_presidio_endpoint_rejects_public_hostname_resolving_to_private_ip(monkeypatch):
    """Public-looking hostnames should be rejected when DNS resolves to non-global addresses."""
    from functions_dlp_presidio import PresidioEndpointConfigurationError, validate_presidio_endpoint_url

    stub_dns_answers(monkeypatch, "presidio.example.com", ["169.254.169.254"])

    try:
        validate_presidio_endpoint_url("https://presidio.example.com/analyze")
    except PresidioEndpointConfigurationError as exc:
        assert "allowlist" in str(exc).lower()
        return

    raise AssertionError("Expected DNS-resolved metadata endpoint address to be rejected.")


def test_validate_presidio_endpoint_rejects_any_private_dns_answer(monkeypatch):
    """Any non-global DNS answer should fail unless the endpoint host is explicitly allowlisted."""
    from functions_dlp_presidio import PresidioEndpointConfigurationError, validate_presidio_endpoint_url

    stub_dns_answers(monkeypatch, "presidio.example.com", ["93.184.216.34", "10.0.0.5"])

    try:
        validate_presidio_endpoint_url("https://presidio.example.com/analyze")
    except PresidioEndpointConfigurationError as exc:
        assert "allowlist" in str(exc).lower()
        return

    raise AssertionError("Expected hostname with mixed public/private DNS answers to be rejected.")


def test_analyze_with_presidio_endpoint_blocks_dns_rebinding_before_socket_connect(monkeypatch):
    """The request connection path should re-check DNS answers before opening a socket."""
    from functions_dlp_presidio import (
        PresidioEndpointConfigurationError,
        PresidioEndpointRequestError,
        analyze_with_presidio_endpoint,
    )

    dns_calls = []
    socket_attempts = {"count": 0}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        assert host == "presidio.example.com"
        dns_calls.append(host)
        address = "93.184.216.34" if len(dns_calls) == 1 else "169.254.169.254"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port or 443))]

    class BlockingSocket:
        def __init__(self, *args, **kwargs):
            socket_attempts["count"] += 1
            raise AssertionError("Unsafe rebinding address reached socket creation.")

    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("PRESIDIO_DLP_API_KEY", "unit-test-secret")
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "socket", BlockingSocket)

    try:
        analyze_with_presidio_endpoint(
            RAW_TEXT,
            {
                "dlp_presidio_analyzer_endpoint": "https://presidio.example.com/analyze",
                "dlp_presidio_auth_secret_env_var": "PRESIDIO_DLP_API_KEY",
            },
        )
    except (PresidioEndpointConfigurationError, PresidioEndpointRequestError):
        assert len(dns_calls) >= 2
        assert socket_attempts["count"] == 0
        return

    raise AssertionError("Expected rebinding request path to be blocked.")


def test_validate_presidio_endpoint_allows_private_dns_answer_for_exact_allowlisted_host(monkeypatch):
    """A private DNS answer should be accepted only for the exact endpoint host in the allowlist."""
    from functions_dlp_presidio import validate_presidio_endpoint_url

    stub_dns_answers(monkeypatch, "presidio.example.com", ["10.0.0.5"])

    assert (
        validate_presidio_endpoint_url(
            "https://presidio.example.com/analyze",
            "presidio.example.com",
        )
        == "https://presidio.example.com/analyze"
    )


def test_validate_presidio_endpoint_allows_private_hosts_with_explicit_allowlist():
    """Private endpoint URLs should be accepted only when their host is explicitly allowlisted."""
    from functions_dlp_presidio import validate_presidio_endpoint_url

    allowed_private_hosts = "10.1.2.3\nlocalhost, ::1"

    assert (
        validate_presidio_endpoint_url("https://10.1.2.3/analyze", allowed_private_hosts)
        == "https://10.1.2.3/analyze"
    )
    assert (
        validate_presidio_endpoint_url("https://localhost:5002/analyze", allowed_private_hosts)
        == "https://localhost:5002/analyze"
    )
    assert (
        validate_presidio_endpoint_url("https://[::1]:5002/analyze", allowed_private_hosts)
        == "https://[::1]:5002/analyze"
    )


def test_validate_presidio_endpoint_rejects_url_secret_persistence_vectors():
    """Endpoint URLs should reject userinfo, fragments, and credential-like query names."""
    from functions_dlp_presidio import PresidioEndpointConfigurationError, validate_presidio_endpoint_url

    blocked_urls = [
        "https://user:pass@presidio.example.com/analyze",
        "https://presidio.example.com/analyze#fragment",
        "https://presidio.example.com/analyze?key=abc",
        "https://presidio.example.com/analyze?api_key=abc",
        "https://presidio.example.com/analyze?apikey=abc",
        "https://presidio.example.com/analyze?secret=abc",
        "https://presidio.example.com/analyze?token=abc",
        "https://presidio.example.com/analyze?password=abc",
        "https://presidio.example.com/analyze?connection=abc",
        "https://presidio.example.com/analyze?sig=abc",
        "https://presidio.example.com/analyze?client_secret=abc",
        "https://presidio.example.com/analyze?access_token=abc",
        "https://presidio.example.com/analyze?subscription-key=abc",
    ]

    for blocked_url in blocked_urls:
        try:
            validate_presidio_endpoint_url(blocked_url)
        except PresidioEndpointConfigurationError:
            continue

        raise AssertionError(f"Expected unsafe endpoint URL to be rejected: {blocked_url}")


def test_validate_presidio_endpoint_rejects_insecure_remote_http():
    """Remote HTTP endpoint URLs should be rejected."""
    from functions_dlp_presidio import PresidioEndpointConfigurationError, validate_presidio_endpoint_url

    try:
        validate_presidio_endpoint_url("http://presidio.example.com/analyze")
    except PresidioEndpointConfigurationError as exc:
        assert "https" in str(exc).lower()
        return

    raise AssertionError("Expected insecure remote HTTP endpoint to be rejected.")


def test_validate_presidio_endpoint_rejects_relative_url():
    """Endpoint URLs must be absolute HTTP(S) URLs."""
    from functions_dlp_presidio import PresidioEndpointConfigurationError, validate_presidio_endpoint_url

    try:
        validate_presidio_endpoint_url("/analyze")
    except PresidioEndpointConfigurationError as exc:
        assert "absolute" in str(exc).lower()
        return

    raise AssertionError("Expected relative endpoint URL to be rejected.")


def test_analyze_with_presidio_endpoint_posts_safe_payload_and_auth_header(monkeypatch):
    """The endpoint adapter should post the Analyzer payload and env-backed auth header."""
    from functions_dlp_presidio import analyze_with_presidio_endpoint

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, allow_redirects=None, allowed_private_hosts=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["allow_redirects"] = allow_redirects
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {"entity_type": "EMAIL_ADDRESS", "start": 11, "end": 24, "score": 0.91}
        ]
        return response

    monkeypatch.setattr("functions_dlp_presidio._post_presidio_endpoint", fake_post)
    monkeypatch.setenv("PRESIDIO_DLP_API_KEY", "unit-test-secret")
    settings = {
        "dlp_presidio_analyzer_endpoint": "https://presidio.internal/analyze",
        "dlp_presidio_allowed_private_hosts": "presidio.internal",
        "dlp_presidio_auth_header_name": "X-DLP-API-Key",
        "dlp_presidio_auth_secret_env_var": "PRESIDIO_DLP_API_KEY",
        "dlp_presidio_entities": ["EMAIL_ADDRESS", "US_SSN"],
        "dlp_presidio_score_threshold": 0.7,
        "dlp_presidio_language": "en",
        "dlp_presidio_timeout_seconds": 3,
    }

    stub_dns_answers(monkeypatch, "presidio.internal", ["10.0.0.5"])
    results = analyze_with_presidio_endpoint(RAW_TEXT, settings)

    assert results == [{"entity_type": "EMAIL_ADDRESS", "start": 11, "end": 24, "score": 0.91}]
    assert captured["url"] == "https://presidio.internal/analyze"
    assert captured["json"] == {
        "text": RAW_TEXT,
        "language": "en",
        "entities": ["EMAIL_ADDRESS", "US_SSN"],
        "score_threshold": 0.7,
    }
    assert captured["headers"]["X-DLP-API-Key"] == "unit-test-secret"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["timeout"] == 3
    assert captured["allow_redirects"] is False


def test_analyze_with_presidio_endpoint_allows_localhost_without_env_secret(monkeypatch):
    """Local development endpoints may omit auth, but only on loopback hosts."""
    from functions_dlp_presidio import analyze_with_presidio_endpoint

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None, allow_redirects=None, allowed_private_hosts=None):
        captured["headers"] = headers
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = []
        return response

    monkeypatch.setattr("functions_dlp_presidio._post_presidio_endpoint", fake_post)
    monkeypatch.delenv("PRESIDIO_DLP_API_KEY", raising=False)
    stub_dns_answers(monkeypatch, "localhost", ["127.0.0.1"])

    analyze_with_presidio_endpoint(
        RAW_TEXT,
        {
            "dlp_presidio_analyzer_endpoint": "http://localhost:5002/analyze",
            "dlp_presidio_allowed_private_hosts": "localhost",
            "dlp_presidio_auth_header_name": "X-DLP-API-Key",
            "dlp_presidio_auth_secret_env_var": "PRESIDIO_DLP_API_KEY",
        },
    )

    assert "X-DLP-API-Key" not in captured["headers"]


def test_analyze_with_presidio_endpoint_requires_auth_secret_for_nonlocal_endpoint(monkeypatch):
    """Non-loopback endpoints should not receive raw text without env-backed auth."""
    from functions_dlp_presidio import PresidioEndpointConfigurationError, analyze_with_presidio_endpoint

    called = {"post": False}

    def fake_post(url, json=None, headers=None, timeout=None, allow_redirects=None, allowed_private_hosts=None):
        called["post"] = True
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = []
        return response

    monkeypatch.setattr("functions_dlp_presidio._post_presidio_endpoint", fake_post)
    monkeypatch.delenv("PRESIDIO_DLP_API_KEY", raising=False)
    stub_dns_answers(monkeypatch, "presidio.internal", ["10.0.0.5"])

    try:
        analyze_with_presidio_endpoint(
            RAW_TEXT,
            {
                "dlp_presidio_analyzer_endpoint": "https://presidio.internal/analyze",
                "dlp_presidio_allowed_private_hosts": "presidio.internal",
                "dlp_presidio_auth_header_name": "X-DLP-API-Key",
                "dlp_presidio_auth_secret_env_var": "PRESIDIO_DLP_API_KEY",
            },
        )
    except PresidioEndpointConfigurationError as exc:
        assert "auth secret" in str(exc).lower()
        assert called["post"] is False
        return

    raise AssertionError("Expected missing non-local auth secret to block the request.")


def test_analyze_with_presidio_endpoint_raises_safe_error_without_raw_text(monkeypatch):
    """Endpoint exceptions should not retain raw scanned text in messages or exception chains."""
    from functions_dlp_presidio import PresidioEndpointRequestError, analyze_with_presidio_endpoint

    def fake_post(url, json=None, headers=None, timeout=None, allow_redirects=None, allowed_private_hosts=None):
        raise RuntimeError(f"upstream included {RAW_TEXT}")

    monkeypatch.setattr("functions_dlp_presidio._post_presidio_endpoint", fake_post)
    monkeypatch.setenv("PRESIDIO_DLP_API_KEY", "unit-test-secret")
    stub_dns_answers(monkeypatch, "presidio.internal", ["10.0.0.5"])

    try:
        analyze_with_presidio_endpoint(
            RAW_TEXT,
            {
                "dlp_presidio_analyzer_endpoint": "https://presidio.internal/analyze",
                "dlp_presidio_allowed_private_hosts": "presidio.internal",
                "dlp_presidio_auth_secret_env_var": "PRESIDIO_DLP_API_KEY",
            },
        )
    except PresidioEndpointRequestError as exc:
        assert RAW_TEXT not in str(exc)
        assert RAW_TEXT not in repr(exc)
        assert "RuntimeError" in str(exc)
        assert exc.__cause__ is None
        assert exc.__context__ is None
        return

    raise AssertionError("Expected endpoint request error.")


def test_analyze_with_presidio_endpoint_normalizes_response_items(monkeypatch):
    """Recognizer responses should be filtered and normalized deterministically."""
    from functions_dlp_presidio import analyze_with_presidio_endpoint

    def fake_post(url, json=None, headers=None, timeout=None, allow_redirects=None, allowed_private_hosts=None):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {"entity_type": "EMAIL_ADDRESS", "start": "11", "end": "24", "score": "0.91"},
            {"entity_type": "US_SSN", "start": -3, "end": "bad", "score": 0.99},
            {"entity_type": "", "start": 1, "end": 2, "score": 0.4},
            "ignored",
        ]
        return response

    monkeypatch.setattr("functions_dlp_presidio._post_presidio_endpoint", fake_post)
    monkeypatch.setenv("PRESIDIO_DLP_API_KEY", "unit-test-secret")
    stub_dns_answers(monkeypatch, "presidio.internal", ["10.0.0.5"])

    results = analyze_with_presidio_endpoint(
        RAW_TEXT,
        {
            "dlp_presidio_analyzer_endpoint": "https://presidio.internal/analyze",
            "dlp_presidio_allowed_private_hosts": "presidio.internal",
            "dlp_presidio_auth_secret_env_var": "PRESIDIO_DLP_API_KEY",
        },
    )

    assert results == [
        {"entity_type": "EMAIL_ADDRESS", "start": 11, "end": 24, "score": 0.91},
        {"entity_type": "", "start": 1, "end": 2, "score": 0.4},
    ]


def test_analyze_with_presidio_endpoint_treats_redirect_as_endpoint_error(monkeypatch):
    """Redirect responses should not be followed or parsed as analyzer results."""
    from functions_dlp_presidio import PresidioEndpointRequestError, analyze_with_presidio_endpoint

    captured = {"calls": 0}

    def fake_post(url, json=None, headers=None, timeout=None, allow_redirects=None, allowed_private_hosts=None):
        captured["calls"] += 1
        captured["allow_redirects"] = allow_redirects
        response = Mock()
        response.status_code = 302
        response.headers = {"Location": "https://attacker.example/analyze"}
        response.raise_for_status.return_value = None
        response.json.side_effect = AssertionError("Redirect responses must not be parsed.")
        return response

    monkeypatch.setattr("functions_dlp_presidio._post_presidio_endpoint", fake_post)
    monkeypatch.setenv("PRESIDIO_DLP_API_KEY", "unit-test-secret")
    stub_dns_answers(monkeypatch, "presidio.example.com", ["93.184.216.34"])

    try:
        analyze_with_presidio_endpoint(
            RAW_TEXT,
            {
                "dlp_presidio_analyzer_endpoint": "https://presidio.example.com/analyze",
                "dlp_presidio_auth_secret_env_var": "PRESIDIO_DLP_API_KEY",
            },
        )
    except PresidioEndpointRequestError as exc:
        assert "redirect" in str(exc).lower()
        assert captured["allow_redirects"] is False
        assert captured["calls"] == 1
        return

    raise AssertionError("Expected redirect response to be handled as an endpoint error.")


def test_presidio_auth_secret_env_var_name_validation(monkeypatch):
    """Only the dedicated Presidio DLP secret env var namespace should be read."""
    from functions_dlp_presidio import _get_auth_headers, normalize_presidio_secret_env_var_name

    monkeypatch.setenv("AZURE_OPENAI_KEY", "must-not-leak")
    monkeypatch.setenv("COSMOS_CONNECTION_STRING", "must-not-leak")
    monkeypatch.setenv("PRESIDIO_DLP_API_KEY", "presidio-secret")
    monkeypatch.setenv("DLP_PRESIDIO_TOKEN", "prefixed-secret")

    assert normalize_presidio_secret_env_var_name("") == ""
    assert normalize_presidio_secret_env_var_name("PRESIDIO_DLP_API_KEY") == "PRESIDIO_DLP_API_KEY"
    assert normalize_presidio_secret_env_var_name("DLP_PRESIDIO_TOKEN") == "DLP_PRESIDIO_TOKEN"
    assert normalize_presidio_secret_env_var_name("AZURE_OPENAI_KEY") == ""
    assert normalize_presidio_secret_env_var_name("COSMOS_CONNECTION_STRING") == ""
    assert _get_auth_headers(
        {
            "dlp_presidio_auth_header_name": "X-DLP-API-Key",
            "dlp_presidio_auth_secret_env_var": "AZURE_OPENAI_KEY",
        }
    ) == {}
    assert _get_auth_headers(
        {
            "dlp_presidio_auth_header_name": "X-DLP-API-Key",
            "dlp_presidio_auth_secret_env_var": "PRESIDIO_DLP_API_KEY",
        }
    ) == {"X-DLP-API-Key": "presidio-secret"}
    assert _get_auth_headers(
        {
            "dlp_presidio_auth_header_name": "X-DLP-API-Key",
            "dlp_presidio_auth_secret_env_var": "DLP_PRESIDIO_TOKEN",
        }
    ) == {"X-DLP-API-Key": "prefixed-secret"}


def test_presidio_auth_header_name_validation(monkeypatch):
    """Auth header names should reject reserved HTTP headers and malformed names."""
    from functions_dlp_presidio import (
        PresidioEndpointConfigurationError,
        _get_auth_headers,
        normalize_presidio_auth_header_name,
    )

    monkeypatch.setenv("PRESIDIO_DLP_API_KEY", "presidio-secret")

    assert normalize_presidio_auth_header_name("") == "X-DLP-API-Key"
    assert normalize_presidio_auth_header_name("X-DLP-API-Key") == "X-DLP-API-Key"
    assert normalize_presidio_auth_header_name("Authorization") == "Authorization"
    assert normalize_presidio_auth_header_name("Content-Type") == ""
    assert normalize_presidio_auth_header_name("Host") == ""
    assert normalize_presidio_auth_header_name("Connection") == ""
    assert normalize_presidio_auth_header_name("Bad Header") == ""
    assert normalize_presidio_auth_header_name("X-DLP-API-Key\r\nX-Injected") == ""
    assert _get_auth_headers(
        {
            "dlp_presidio_auth_header_name": "Authorization",
            "dlp_presidio_auth_secret_env_var": "PRESIDIO_DLP_API_KEY",
        }
    ) == {"Authorization": "presidio-secret"}

    try:
        _get_auth_headers(
            {
                "dlp_presidio_auth_header_name": "Content-Type",
                "dlp_presidio_auth_secret_env_var": "PRESIDIO_DLP_API_KEY",
            }
        )
    except PresidioEndpointConfigurationError as exc:
        assert "header" in str(exc).lower()
        return

    raise AssertionError("Expected reserved auth header name to be rejected.")
