# test_dlp_presidio_endpoint.py
#!/usr/bin/env python3
"""
Functional test for external Presidio endpoint DLP adapter.
Version: 0.242.044
Implemented in: 0.242.044

This test ensures SimpleChat can call a configured Presidio-compatible analyzer
endpoint without embedding Presidio packages or leaking raw scanned text.
"""

import os
import sys
from unittest.mock import Mock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
sys.path.insert(0, APP_DIR)


RAW_TEXT = "Contact me a@example.com"


def test_validate_presidio_endpoint_allows_https_and_localhost():
    """HTTPS and local HTTP endpoint URLs should be accepted."""
    from functions_dlp_presidio import validate_presidio_endpoint_url

    assert validate_presidio_endpoint_url("https://presidio.internal/analyze") == "https://presidio.internal/analyze"
    assert validate_presidio_endpoint_url("http://localhost:5002/analyze") == "http://localhost:5002/analyze"
    assert validate_presidio_endpoint_url("http://127.0.0.1:5002/analyze") == "http://127.0.0.1:5002/analyze"
    assert validate_presidio_endpoint_url("http://[::1]:5002/analyze") == "http://[::1]:5002/analyze"


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

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {"entity_type": "EMAIL_ADDRESS", "start": 11, "end": 24, "score": 0.91}
        ]
        return response

    monkeypatch.setattr("functions_dlp_presidio.requests.post", fake_post)
    monkeypatch.setenv("PRESIDIO_DLP_API_KEY", "unit-test-secret")
    settings = {
        "dlp_presidio_analyzer_endpoint": "https://presidio.internal/analyze",
        "dlp_presidio_auth_header_name": "X-DLP-API-Key",
        "dlp_presidio_auth_secret_env_var": "PRESIDIO_DLP_API_KEY",
        "dlp_presidio_entities": ["EMAIL_ADDRESS", "US_SSN"],
        "dlp_presidio_score_threshold": 0.7,
        "dlp_presidio_language": "en",
        "dlp_presidio_timeout_seconds": 3,
    }

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


def test_analyze_with_presidio_endpoint_omits_auth_header_without_env_secret(monkeypatch):
    """Raw API keys should come only from the configured environment variable."""
    from functions_dlp_presidio import analyze_with_presidio_endpoint

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["headers"] = headers
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = []
        return response

    monkeypatch.setattr("functions_dlp_presidio.requests.post", fake_post)
    monkeypatch.delenv("PRESIDIO_DLP_API_KEY", raising=False)

    analyze_with_presidio_endpoint(
        RAW_TEXT,
        {
            "dlp_presidio_analyzer_endpoint": "https://presidio.internal/analyze",
            "dlp_presidio_auth_header_name": "X-DLP-API-Key",
            "dlp_presidio_auth_secret_env_var": "PRESIDIO_DLP_API_KEY",
        },
    )

    assert "X-DLP-API-Key" not in captured["headers"]


def test_analyze_with_presidio_endpoint_raises_safe_error_without_raw_text(monkeypatch):
    """Endpoint exceptions should not retain raw scanned text in messages or exception chains."""
    from functions_dlp_presidio import PresidioEndpointRequestError, analyze_with_presidio_endpoint

    def fake_post(url, json=None, headers=None, timeout=None):
        raise RuntimeError(f"upstream included {RAW_TEXT}")

    monkeypatch.setattr("functions_dlp_presidio.requests.post", fake_post)

    try:
        analyze_with_presidio_endpoint(
            RAW_TEXT,
            {"dlp_presidio_analyzer_endpoint": "https://presidio.internal/analyze"},
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

    def fake_post(url, json=None, headers=None, timeout=None):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {"entity_type": "EMAIL_ADDRESS", "start": "11", "end": "24", "score": "0.91"},
            {"entity_type": "US_SSN", "start": -3, "end": "bad", "score": 0.99},
            {"entity_type": "", "start": 1, "end": 2, "score": 0.4},
            "ignored",
        ]
        return response

    monkeypatch.setattr("functions_dlp_presidio.requests.post", fake_post)

    results = analyze_with_presidio_endpoint(
        RAW_TEXT,
        {"dlp_presidio_analyzer_endpoint": "https://presidio.internal/analyze"},
    )

    assert results == [{"entity_type": "EMAIL_ADDRESS", "start": 11, "end": 24, "score": 0.91}]
