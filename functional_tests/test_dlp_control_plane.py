# test_dlp_control_plane.py
#!/usr/bin/env python3
"""
Functional test for DLP control plane core behavior.
Version: 0.241.018
Implemented in: 0.241.008

This test ensures the shared DLP core supports disabled, regex, Luhn-validated
credit-card, counts-only metadata, ReDoS-resistant scanning, and optional
Presidio service normalization without persisting raw matched values.
"""

import os
import sys
import time
from unittest.mock import patch


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
sys.path.insert(0, APP_DIR)


RAW_SSN = "123-45-6789"
RAW_CARD = "4111 1111 1111 1111"
INVALID_CARD = "4111 1111 1111 1112"


def assert_no_raw_values(payload):
    """Assert a nested DLP payload does not include raw sensitive values."""
    serialized = repr(payload)
    forbidden_values = [RAW_SSN, RAW_CARD, INVALID_CARD, "Alice Example"]
    for value in forbidden_values:
        assert value not in serialized, f"Raw value leaked into payload: {value}"


def test_disabled_dlp_allows_original_text():
    """Disabled DLP should return the original text and an allow decision."""
    print("Testing disabled DLP behavior...")
    from functions_dlp import evaluate_dlp_text

    text = f"Please search for {RAW_SSN}"
    result = evaluate_dlp_text(
        text,
        settings={"enable_dlp_control_plane": False},
        surface="web_search",
    )

    assert result["decision"] == "allow"
    assert result["text"] == text
    assert result["redacted_text"] == text
    assert result["total_replacements"] == 0
    assert result["match_counts"] == {}
    assert result["matches"] == []


def test_regex_redacts_ssn_and_counts_only_metadata():
    """Regex mode should redact SSNs and return counts-only metadata."""
    print("Testing SSN redaction and safe metadata...")
    from functions_dlp import evaluate_dlp_text

    result = evaluate_dlp_text(
        f"Customer SSN is {RAW_SSN}.",
        settings={
            "enable_dlp_control_plane": True,
            "dlp_default_engine": "regex",
            "web_search_dlp_mode": "redact",
        },
        surface="web_search",
    )

    assert result["decision"] == "redact"
    assert "[REDACTED_US_SSN]" in result["redacted_text"]
    assert result["match_counts"] == {"US_SSN": 1}
    assert result["total_replacements"] == 1
    assert_no_raw_values(result)


def test_credit_card_requires_luhn_validation():
    """Credit-card-like values should redact only when Luhn-valid."""
    print("Testing credit card Luhn validation...")
    from functions_dlp import evaluate_dlp_text

    valid_result = evaluate_dlp_text(
        f"Use card {RAW_CARD} for the vendor.",
        settings={"enable_dlp_control_plane": True, "web_search_dlp_mode": "redact"},
        surface="web_search",
    )
    invalid_result = evaluate_dlp_text(
        f"Ignore fake card {INVALID_CARD}.",
        settings={"enable_dlp_control_plane": True, "web_search_dlp_mode": "redact"},
        surface="web_search",
    )

    assert valid_result["match_counts"] == {"CREDIT_CARD": 1}
    assert "[REDACTED_CREDIT_CARD]" in valid_result["redacted_text"]
    assert invalid_result["decision"] == "allow"
    assert invalid_result["redacted_text"].endswith(f"{INVALID_CARD}.")
    assert invalid_result["match_counts"] == {}
    assert_no_raw_values(valid_result)


def test_regex_scan_is_bounded_on_long_non_matching_input():
    """Regex recognizers should avoid catastrophic backtracking."""
    print("Testing regex performance on long non-matching input...")
    from functions_dlp import evaluate_dlp_text

    long_text = ("not-sensitive " * 20000) + "done"
    started = time.perf_counter()
    result = evaluate_dlp_text(
        long_text,
        settings={
            "enable_dlp_control_plane": True,
            "web_search_dlp_mode": "redact",
            "dlp_max_scan_chars": 500000,
        },
        surface="web_search",
    )
    elapsed = time.perf_counter() - started

    assert result["decision"] == "allow"
    assert elapsed < 2.0, f"Regex scan took too long: {elapsed:.3f}s"


def test_enforced_dlp_blocks_when_text_exceeds_scan_limit():
    """Enforced DLP must not append unscanned text into sanitized output."""
    from functions_dlp import evaluate_dlp_text

    settings = {
        "enable_dlp_control_plane": True,
        "dlp_default_engine": "regex",
        "dlp_max_scan_chars": 20,
        "web_search_dlp_mode": "redact",
        "enable_web_search_dlp": True,
    }
    text = "public prefix only " + ("x" * 25) + " SSN 123-45-6789"

    result = evaluate_dlp_text(text, settings=settings, surface="web_search")

    assert result["decision"] == "block"
    assert result["scanner_status"] == "truncated"
    assert result["text"] == ""
    assert "123-45-6789" not in repr(result)


def test_enforced_truncation_blocks_before_scanner_error_fail_open():
    """Protected enforced surfaces should block truncated text before scanner errors."""
    import functions_dlp

    def fail_scan(text, settings, surface="generic"):
        raise RuntimeError("scanner unavailable")

    settings = {
        "enable_dlp_control_plane": True,
        "dlp_fail_closed_on_scanner_error": False,
        "dlp_max_scan_chars": 12,
        "web_search_dlp_mode": "redact",
        "enable_web_search_dlp": True,
    }
    text = "safe prefix " + ("x" * 25) + f" tail {RAW_SSN}"

    with patch.object(functions_dlp, "_apply_regex_engine", fail_scan):
        result = functions_dlp.evaluate_dlp_text(text, settings=settings, surface="web_search")

    assert result["decision"] == "block"
    assert result["scanner_status"] == "truncated"
    assert result["text"] == ""
    assert result["redacted_text"] == ""
    assert result["metadata"]["skipped_chars"] > 0
    assert RAW_SSN not in repr(result)
    assert "tail" not in repr(result)


def test_presidio_service_shape_normalizes_counts_without_raw_values():
    """Optional Presidio service results should normalize into the shared shape."""
    print("Testing Presidio service adapter normalization...")
    from functions_dlp import normalize_presidio_results

    normalized = normalize_presidio_results(
        text=f"Alice Example has SSN {RAW_SSN}.",
        recognizer_results=[
            {"entity_type": "PERSON", "start": 0, "end": 13, "score": 0.88},
            {"entity_type": "US_SSN", "start": 22, "end": 33, "score": 0.99},
        ],
        mode="redact",
        engine="presidio_service",
    )

    assert normalized["decision"] == "redact"
    assert normalized["match_counts"] == {"PERSON": 1, "US_SSN": 1}
    assert "[REDACTED_PERSON]" in normalized["redacted_text"]
    assert "[REDACTED_US_SSN]" in normalized["redacted_text"]
    assert_no_raw_values(normalized)


if __name__ == "__main__":
    tests = [
        test_disabled_dlp_allows_original_text,
        test_regex_redacts_ssn_and_counts_only_metadata,
        test_credit_card_requires_luhn_validation,
        test_regex_scan_is_bounded_on_long_non_matching_input,
        test_enforced_dlp_blocks_when_text_exceeds_scan_limit,
        test_enforced_truncation_blocks_before_scanner_error_fail_open,
        test_presidio_service_shape_normalizes_counts_without_raw_values,
    ]

    try:
        for test in tests:
            test()
        print(f"All {len(tests)} DLP control plane tests passed.")
        sys.exit(0)
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
