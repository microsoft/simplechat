#!/usr/bin/env python3
"""
Functional test for Custom model endpoint failure diagnostics.
Version: 0.261.015
Implemented in: 0.261.015

Custom endpoint errors are sanitized before reaching the browser, because an
upstream error body can echo back a URL, a header, or an API key. The original
implementation achieved that by discarding the cause entirely:

    raise RuntimeError("Custom model request failed.") from None

An administrator then saw the same sentence for a wrong path, a wrong key, a
wrong model name, a TLS failure, and a blocked address, with nothing in the log
to tell them apart.

These tests ensure that:
  * credentials are redacted from anything written to the log,
  * the sanitized browser message leaks no secret, internal URL, or upstream body,
  * the browser message carries a correlation id that appears in the log entry,
  * no Custom endpoint failure path discards its cause any more,
  * a logging failure never replaces the original error.
"""

import os
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "application",
    "single_app",
)
sys.path.append(APP_DIR)

from test_support.versioning import assert_app_version_at_least

import functions_model_endpoint_diagnostics as diagnostics

build_sanitized_model_endpoint_error = diagnostics.build_sanitized_model_endpoint_error
log_custom_model_endpoint_failure = diagnostics.log_custom_model_endpoint_failure
redact_model_endpoint_secrets = diagnostics.redact_model_endpoint_secrets


SECRET_SAMPLES = [
    ("api_key: sk-abcdef1234567890xyz", "sk-abcdef1234567890xyz"),
    ('{"api-key": "secret-value-123"}', "secret-value-123"),
    ("https://gen.example.com/v1?key=AIzaSyABCDEF123456", "AIzaSyABCDEF123456"),
    ("x-goog-api-key: AIzaSyTOPSECRET", "AIzaSyTOPSECRET"),
    ("x-api-key: sk-ant-api03-longsecret", "sk-ant-api03-longsecret"),
]


def test_credentials_are_redacted():
    """Anything credential-shaped must be redacted before it is logged."""
    print("Testing credential redaction...")
    try:
        for sample, secret in SECRET_SAMPLES:
            redacted = redact_model_endpoint_secrets(sample)
            assert secret not in redacted, f"{secret!r} survived redaction in {redacted!r}"
            assert "[REDACTED]" in redacted, f"No redaction marker in {redacted!r}"

        # Ordinary diagnostic text must survive intact so the log stays useful.
        ordinary = "connection reset while reading the response body"
        assert redact_model_endpoint_secrets(ordinary) == ordinary

        # Oversized detail is truncated rather than flooding the log.
        long_detail = "x" * 5000
        assert len(redact_model_endpoint_secrets(long_detail)) < 5000

        print(f"Redaction passed for {len(SECRET_SAMPLES)} credential shapes")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_sanitized_error_leaks_nothing():
    """The browser message must contain no secret, internal URL, or upstream body."""
    print("Testing sanitized browser message...")
    try:
        cause = ValueError(
            "upstream said: invalid api_key: sk-supersecret123456 "
            "at https://internal.corp.example/v1"
        )
        error = build_sanitized_model_endpoint_error(
            "Custom model request failed.",
            cause,
            api_type="gemini",
            request_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            status_code=401,
            detail='{"error":{"message":"API key not valid"}}',
        )

        message = str(error)
        assert isinstance(error, RuntimeError)
        assert "sk-supersecret123456" not in message
        assert "internal.corp.example" not in message
        assert "API key not valid" not in message
        assert message.startswith("Custom model request failed.")

        print(f"Browser message is safe: {message}")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_correlation_id_links_message_to_log():
    """The id shown to the user must be the id recorded in the log."""
    print("Testing correlation id linkage...")
    try:
        captured = {}

        def fake_log_event(message, extra=None, **kwargs):
            captured["message"] = message
            captured["extra"] = extra or {}

        original_log_event = diagnostics.log_event
        diagnostics.log_event = fake_log_event
        try:
            error = build_sanitized_model_endpoint_error(
                "Custom model request failed.",
                ValueError("boom"),
                api_type="openai",
                request_url="https://api.gen.ai.mil/v1/",
                status_code=404,
            )
        finally:
            diagnostics.log_event = original_log_event

        match = re.search(r"\(reference ([0-9a-f]{8})\)$", str(error))
        assert match, f"No correlation id in {str(error)!r}"
        correlation_id = match.group(1)

        assert captured["extra"].get("correlation_id") == correlation_id
        assert correlation_id in captured["message"]

        # The log must carry the diagnostics an administrator actually needs.
        assert captured["extra"].get("api_type") == "openai"
        assert captured["extra"].get("status_code") == 404
        assert captured["extra"].get("request_url") == "https://api.gen.ai.mil/v1/"
        assert captured["extra"].get("error_type") == "ValueError"

        print(f"Correlation id {correlation_id} links message and log entry")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_logging_failure_does_not_mask_the_error():
    """A broken logger must never replace the original failure."""
    print("Testing logging resilience...")
    try:
        def exploding_log_event(*args, **kwargs):
            raise RuntimeError("app insights is down")

        original_log_event = diagnostics.log_event
        diagnostics.log_event = exploding_log_event
        try:
            correlation_id = log_custom_model_endpoint_failure(
                "Custom model request failed.",
                ValueError("boom"),
            )
        finally:
            diagnostics.log_event = original_log_event

        assert re.fullmatch(r"[0-9a-f]{8}", correlation_id), correlation_id
        print("Logging failure handled without masking the original error")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_no_failure_path_discards_its_cause():
    """No Custom endpoint failure path may raise a bare sanitized error any more."""
    print("Testing that no failure path discards its cause...")
    try:
        with open(
            os.path.join(APP_DIR, "model_endpoint_clients.py"), encoding="utf-8"
        ) as source_file:
            source = source_file.read()

        discarded = re.findall(
            r'raise RuntimeError\(\s*\n?\s*"Custom[^"]*"\s*\n?\s*\) from None',
            source,
        )
        assert not discarded, (
            f"{len(discarded)} Custom failure path(s) still discard the cause: {discarded}"
        )

        # Every sanitized Custom error must go through the diagnostics helper.
        assert "build_sanitized_model_endpoint_error" in source
        assert source.count("build_sanitized_model_endpoint_error(") >= 7, (
            "Expected every sanitized Custom failure path to use the diagnostics helper."
        )

        print("All Custom failure paths route through the diagnostics helper")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_version_bumped():
    """Diagnostics ship at or after their implementation version."""
    print("Testing config version...")
    try:
        assert_app_version_at_least("0.261.015")
        print("Config version check passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_credentials_are_redacted,
        test_sanitized_error_leaks_nothing,
        test_correlation_id_links_message_to_log,
        test_logging_failure_does_not_mask_the_error,
        test_no_failure_path_discards_its_cause,
        test_version_bumped,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
