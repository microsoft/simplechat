# test_dlp_presidio_engine_integration.py
#!/usr/bin/env python3
"""
Functional test for Presidio endpoint engine integration.
Version: 0.242.075
Implemented in: 0.242.075

This test ensures the external Presidio endpoint engine reuses SimpleChat's
existing DLP decision, redaction, and fail-closed behavior.
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
sys.path.insert(0, APP_DIR)


RAW_TEXT = "Contact me a@example.com"


def presidio_settings(mode="redact", fail_closed=True):
    """Build deterministic settings for Presidio endpoint engine tests."""
    return {
        "enable_dlp_control_plane": True,
        "dlp_default_engine": "presidio_endpoint",
        "dlp_presidio_analyzer_endpoint": "https://presidio.internal/analyze",
        "dlp_presidio_allowed_private_hosts": "presidio.internal",
        "dlp_presidio_timeout_seconds": 3,
        "dlp_presidio_score_threshold": 0.7,
        "dlp_presidio_entities": ["EMAIL_ADDRESS"],
        "dlp_fail_closed_on_scanner_error": fail_closed,
        "enable_web_search_dlp": True,
        "web_search_dlp_mode": mode,
        "enable_upload_dlp": True,
        "upload_dlp_mode": mode,
    }


def test_presidio_endpoint_redacts_with_existing_result_shape(monkeypatch):
    """Presidio endpoint matches should redact using the shared DLP result shape."""
    import functions_dlp

    monkeypatch.setattr(
        functions_dlp,
        "analyze_with_presidio_endpoint",
        lambda text, settings: [{"entity_type": "EMAIL_ADDRESS", "start": 11, "end": 24, "score": 0.92}],
    )

    result = functions_dlp.evaluate_dlp_text(
        RAW_TEXT,
        settings=presidio_settings("redact"),
        surface="web_search",
    )

    assert result["engine"] == "presidio_endpoint"
    assert result["decision"] == "redact"
    assert result["text"] == "Contact me [REDACTED_EMAIL_ADDRESS]"
    assert result["redacted_text"] == "Contact me [REDACTED_EMAIL_ADDRESS]"
    assert result["match_counts"] == {"EMAIL_ADDRESS": 1}
    assert result["scanner_status"] == "ok"


def test_presidio_endpoint_blocks_with_existing_result_shape(monkeypatch):
    """Block mode should blank text fields while keeping safe counts."""
    import functions_dlp

    monkeypatch.setattr(
        functions_dlp,
        "analyze_with_presidio_endpoint",
        lambda text, settings: [{"entity_type": "EMAIL_ADDRESS", "start": 11, "end": 24, "score": 0.92}],
    )

    result = functions_dlp.evaluate_dlp_text(
        RAW_TEXT,
        settings=presidio_settings("block"),
        surface="upload",
    )

    assert result["engine"] == "presidio_endpoint"
    assert result["decision"] == "block"
    assert result["text"] == ""
    assert result["redacted_text"] == ""
    assert result["match_counts"] == {"EMAIL_ADDRESS": 1}
    assert result["scanner_status"] == "ok"


def test_presidio_endpoint_scanner_error_fails_closed_without_raw_text(monkeypatch):
    """Endpoint scanner errors should reuse fail-closed handling and avoid raw text."""
    import functions_dlp

    def fail_scan(text, settings):
        raise RuntimeError(f"endpoint failed while scanning {RAW_TEXT}")

    monkeypatch.setattr(functions_dlp, "analyze_with_presidio_endpoint", fail_scan)

    result = functions_dlp.evaluate_dlp_text(
        RAW_TEXT,
        settings=presidio_settings("redact", fail_closed=True),
        surface="web_search",
    )

    assert result["engine"] == "presidio_endpoint"
    assert result["decision"] == "block"
    assert result["text"] == ""
    assert result["redacted_text"] == ""
    assert result["scanner_status"] == "error"
    assert RAW_TEXT not in repr(result)


def test_presidio_endpoint_sanitizes_untrusted_entity_labels(monkeypatch):
    """Remote entity labels must not be copied into redaction output or count keys."""
    import functions_dlp

    malicious_label = "EMAIL_ADDRESS_a@example.com"
    monkeypatch.setattr(
        functions_dlp,
        "analyze_with_presidio_endpoint",
        lambda text, settings: [{"entity_type": malicious_label, "start": 11, "end": 24, "score": 0.92}],
    )

    result = functions_dlp.evaluate_dlp_text(
        RAW_TEXT,
        settings=presidio_settings("redact"),
        surface="web_search",
    )
    telemetry = functions_dlp.build_dlp_telemetry_properties(result, "web_search")

    assert result["redacted_text"] == "Contact me [REDACTED_UNKNOWN_ENTITY]"
    assert result["match_counts"] == {"UNKNOWN_ENTITY": 1}
    assert result["matches"] == [{"entity_type": "UNKNOWN_ENTITY", "count": 1}]
    assert telemetry["dlp_entity_counts"] == {"UNKNOWN_ENTITY": 1}
    assert malicious_label not in repr(result)
    assert "a@example.com" not in repr(result)
    assert malicious_label not in repr(telemetry)
    assert "a@example.com" not in repr(telemetry)


def test_external_analyzer_normalizes_empty_and_too_long_entity_labels():
    """Invalid external analyzer labels should collapse to a fixed safe entity name."""
    import functions_dlp

    long_label = "A" * 65
    results = [
        {"entity_type": "", "start": 0, "end": 7},
        {"entity_type": long_label, "start": 11, "end": 24},
    ]

    normalized = functions_dlp.normalize_external_analyzer_results(RAW_TEXT, results, mode="redact")

    assert normalized["redacted_text"] == "[REDACTED_UNKNOWN_ENTITY] me [REDACTED_UNKNOWN_ENTITY]"
    assert normalized["match_counts"] == {"UNKNOWN_ENTITY": 2}
    assert normalized["matches"] == [{"entity_type": "UNKNOWN_ENTITY", "count": 2}]
    assert long_label not in repr(normalized)


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__]))
