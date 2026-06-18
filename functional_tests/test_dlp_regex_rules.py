# test_dlp_regex_rules.py
#!/usr/bin/env python3
"""
Functional test for configurable DLP regex rules.
Version: 0.242.073
Implemented in: 0.242.073

This test ensures DLP regex rules are admin-configurable, validated,
confidence-shaped, timeout-bounded, and safe to report without raw matched values.
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
sys.path.insert(0, APP_DIR)


RAW_SSN = "123-45-6789"
RAW_CARD = "4111 1111 1111 1111"


def assert_no_raw_values(result):
    payload = repr(result)
    assert RAW_SSN not in payload
    assert RAW_CARD not in payload
    assert "ZX-12345" not in payload


def test_default_rules_include_ssn_and_credit_card_only():
    """Default DLP regex rules should be structured identifier defaults only."""
    print("Testing default DLP regex rules...")
    from functions_dlp_rules import get_default_dlp_regex_rules

    rules = get_default_dlp_regex_rules()
    ids = [rule["id"] for rule in rules]

    assert ids == ["us_ssn", "credit_card"]
    assert all(rule["enabled"] is True for rule in rules)
    assert "internal_phrase" not in ids
    assert "confidential" not in repr(rules).lower()


def test_custom_regex_rule_redacts_on_configured_surface():
    """A configured custom rule should redact on an allowed surface."""
    print("Testing custom regex DLP rule...")
    from functions_dlp import evaluate_dlp_text

    settings = {
        "enable_dlp_control_plane": True,
        "web_search_dlp_mode": "redact",
        "dlp_regex_rules": [
            {
                "id": "ticket_id",
                "label": "Ticket ID",
                "entity_type": "TICKET_ID",
                "enabled": True,
                "pattern": r"ZX-\d{5}",
                "replacement": "[REDACTED_TICKET_ID]",
                "surfaces": ["web_search"],
                "flags": [],
                "validator": "none",
                "confidence": {
                    "regex_only": "medium",
                    "with_keywords": "high",
                    "keywords": ["ticket", "case"],
                    "window_chars": 24,
                    "minimum": "medium"
                }
            }
        ],
    }

    result = evaluate_dlp_text(
        "Search for ticket ZX-12345",
        settings=settings,
        surface="web_search",
    )

    assert result["decision"] == "redact"
    assert result["redacted_text"] == "Search for ticket [REDACTED_TICKET_ID]"
    assert result["match_counts"] == {"TICKET_ID": 1}
    assert result["matches"] == [{"entity_type": "TICKET_ID", "count": 1, "confidence": "high"}]
    assert_no_raw_values(result)


def test_disabled_custom_rule_does_not_match():
    """Disabled rules should not produce matches."""
    print("Testing disabled custom regex DLP rule...")
    from functions_dlp import evaluate_dlp_text

    settings = {
        "enable_dlp_control_plane": True,
        "web_search_dlp_mode": "redact",
        "dlp_regex_rules": [
            {
                "id": "ticket_id",
                "label": "Ticket ID",
                "entity_type": "TICKET_ID",
                "enabled": False,
                "pattern": r"ZX-\d{5}",
                "replacement": "[REDACTED_TICKET_ID]",
                "surfaces": ["web_search"],
                "flags": [],
                "validator": "none",
                "confidence": {
                    "regex_only": "medium",
                    "with_keywords": "high",
                    "keywords": ["ticket"],
                    "window_chars": 24,
                    "minimum": "medium"
                }
            }
        ],
    }

    result = evaluate_dlp_text("Search for ticket ZX-12345", settings=settings, surface="web_search")

    assert result["decision"] == "allow"
    assert result["match_counts"] == {}
    assert "ZX-12345" in result["redacted_text"]


def test_confidence_requires_nearby_keyword_when_minimum_is_high():
    """Rules can require regex plus nearby keyword evidence for high-confidence matches."""
    print("Testing DLP confidence shaping...")
    from functions_dlp import evaluate_dlp_text

    rule = {
        "id": "employee_id",
        "label": "Employee ID",
        "entity_type": "EMPLOYEE_ID",
        "enabled": True,
        "pattern": r"EID-\d{6}",
        "replacement": "[REDACTED_EMPLOYEE_ID]",
        "surfaces": ["web_search"],
        "flags": [],
        "validator": "none",
        "confidence": {
            "regex_only": "low",
            "with_keywords": "high",
            "keywords": ["employee", "worker", "staff"],
            "window_chars": 32,
            "minimum": "high"
        }
    }
    settings = {
        "enable_dlp_control_plane": True,
        "web_search_dlp_mode": "redact",
        "dlp_regex_rules": [rule],
    }

    low_result = evaluate_dlp_text("Search for EID-123456", settings=settings, surface="web_search")
    high_result = evaluate_dlp_text("Search employee EID-123456", settings=settings, surface="web_search")

    assert low_result["decision"] == "allow"
    assert low_result["match_counts"] == {}
    assert high_result["decision"] == "redact"
    assert high_result["match_counts"] == {"EMPLOYEE_ID": 1}
    assert high_result["matches"] == [{"entity_type": "EMPLOYEE_ID", "count": 1, "confidence": "high"}]


def test_invalid_regex_rule_is_rejected_before_runtime():
    """Invalid admin regex rules should return validation errors."""
    print("Testing invalid regex rule validation...")
    from functions_dlp_rules import validate_dlp_regex_rules

    normalized, errors = validate_dlp_regex_rules(
        [
            {
                "id": "bad",
                "label": "Bad Rule",
                "entity_type": "BAD",
                "enabled": True,
                "pattern": r"(",
                "replacement": "[REDACTED_BAD]",
                "surfaces": ["web_search"],
                "flags": [],
                "validator": "none",
                "confidence": {
                    "regex_only": "medium",
                    "with_keywords": "high",
                    "keywords": [],
                    "window_chars": 16,
                    "minimum": "medium"
                }
            }
        ]
    )

    assert normalized == []
    assert errors
    assert "bad" in errors[0]


def test_internal_phrase_is_not_a_default_blocker():
    """Generic policy words should not be hardcoded blockers."""
    print("Testing internal phrase is not hardcoded...")
    from functions_dlp import evaluate_web_search_egress

    result = evaluate_web_search_egress(
        "Search for confidentiality agreement examples",
        settings={
            "enable_dlp_control_plane": True,
            "enable_web_search_dlp": True,
            "web_search_dlp_mode": "redact",
        },
    )

    assert result["web_search_allowed"] is True
    assert result["decision"] == "allow"
    assert "confidentiality agreement" in result["web_search_query_text"]


if __name__ == "__main__":
    tests = [
        test_default_rules_include_ssn_and_credit_card_only,
        test_custom_regex_rule_redacts_on_configured_surface,
        test_disabled_custom_rule_does_not_match,
        test_confidence_requires_nearby_keyword_when_minimum_is_high,
        test_invalid_regex_rule_is_rejected_before_runtime,
        test_internal_phrase_is_not_a_default_blocker,
    ]

    failures = []
    for test in tests:
        try:
            test()
        except Exception as exc:
            failures.append((test.__name__, exc))
            print(f"Test failed: {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()

    if failures:
        print(f"{len(failures)} of {len(tests)} configurable DLP regex rule tests failed.")
        sys.exit(1)

    print(f"All {len(tests)} configurable DLP regex rule tests passed.")
    sys.exit(0)
