# test_admin_support_export_privacy.py
"""
Functional tests for complete support-bundle privacy processing.
Version: 0.261.426
Implemented in: 0.261.426

Exercise real deterministic PII inspection and grounded AI span application,
including credentials, Unicode, aliases, and fail-closed coverage.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from content_screening.contracts import DetectorResult, Finding
from support_export_contracts import SupportExportError
from support_export_privacy import BundleRedactor, scrub_credentials


def test_credentials_and_multiline_diagnostics_are_preserved_safely():
    text = 'email user@example.org password=not-a-real-password\ntrace line'
    redactor = BundleRedactor("11" * 32)
    result = redactor.deterministic({"message": text, "api_key": "test-key-not-a-secret"})
    serialized = json.dumps(result)
    assert "not-a-real-password" not in serialized
    assert "test-key-not-a-secret" not in serialized
    assert "user@example.org" not in serialized
    assert "\ntrace line" in result["message"]
    assert redactor.report()["deterministic"] == "complete"
    assert "user@example.org" not in json.dumps(redactor.report())


@pytest.mark.parametrize("value,secret", [
    ('{"password": "test-password"}', "test-password"),
    ("password%3Dencoded-secret%26safe%3D1", "encoded-secret"),
    ("Bearer eyJtest.abcd.signature", "eyJtest.abcd.signature"),
    ("AccountKey=fake-account-key;EndpointSuffix=core.windows.net", "fake-account-key"),
    ("-----BEGIN PRIVATE KEY-----\nnot-a-real-private-key\n-----END PRIVATE KEY-----", "not-a-real-private-key"),
])
def test_credential_shapes(value, secret):
    cleaned = scrub_credentials(value)
    assert secret not in cleaned


def test_stable_bundle_aliases_and_nested_pii_keys():
    user_id = "11111111-1111-4111-8111-111111111111"
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()
    first = BundleRedactor("22" * 32)
    snapshot = first.deterministic({"user": user_id, "email": "same@example.org"}, identifiers=[user_id])
    second = BundleRedactor("22" * 32)
    logs = second.deterministic({"user_hash": user_hash, "same@example.org": "same@example.org"}, identifiers=[user_id])
    assert snapshot["user"] == logs["user_hash"]
    assert snapshot["email"] == next(value for key, value in logs.items() if key != "user_hash")
    assert "same@example.org" not in json.dumps(logs)
    different = BundleRedactor("33" * 32).deterministic({"user": user_id}, identifiers=[user_id])
    assert snapshot["user"] != different["user"]


def test_real_deterministic_pii_and_ip_patterns():
    result = BundleRedactor().deterministic({
        "message": "Call +1 212-555-1212; SSN 123-45-6789; card 4111 1111 1111 1111; hosts 10.1.2.3 and 2001:db8::1",
    })
    text = result["message"]
    for original in ("212-555-1212", "123-45-6789", "4111 1111", "10.1.2.3", "2001:db8::1"):
        assert original not in text


def test_ai_validated_spans_replace_only_grounded_text():
    def inspect(units, selection, progress, budget):
        target = next(unit for unit in units if "Hello Jane Doe." in unit.text)
        start = target.text.index("Jane Doe")
        return DetectorResult(
            status="findings", required_units=len(units), completed_units=len(units),
            required_windows=1, completed_windows=1,
            findings=[Finding(
                rule_id="privacy", unit_id=target.unit_id, category="pii", severity="high",
                reason="Name", start=start, end=start + 8, evidence="Jane Doe",
            )],
        )

    redactor = BundleRedactor()
    cleaned, report = redactor.inspect_ai({"message": "Hello Jane Doe."}, selection={}, inspect=inspect)
    assert "Jane Doe" not in cleaned["message"]
    assert cleaned["message"].startswith("Hello ")
    assert report["status"] == "complete"


def test_partial_ai_inspection_never_becomes_a_reviewed_bundle():
    def inspect(units, selection, progress, budget):
        return DetectorResult(status="incomplete", required_units=len(units), completed_units=0)

    with pytest.raises(SupportExportError, match="did not complete"):
        BundleRedactor().inspect_ai({"message": "Hello"}, selection={}, inspect=inspect)


def test_known_ids_do_not_break_email_detection_and_numeric_diagnostics_survive():
    redactor = BundleRedactor()
    result = redactor.deterministic({
        "message": "owner@example.test", "user_id": "owner",
        "sc_api_key_present": True, "prompt_tokens": 123, "api_key": "test-key",
    }, identifiers=["owner"])
    assert result["message"].startswith("[EMAIL_")
    assert result["user_id"].startswith("[IDENTIFIER_")
    assert result["sc_api_key_present"] is True and result["prompt_tokens"] == 123
    assert result["api_key"] == "[REDACTED_CREDENTIAL]"
    assert redactor.report()["redaction_counts"]["credential_fields"] == 1


def test_all_users_exports_mask_semantic_identifiers_without_guid_formats():
    result = BundleRedactor().deterministic({
        "user_id": "employee-one", "conversation_id": "conversation-example", "owner_id": 12345,
    })
    assert all(str(value).startswith("[IDENTIFIER_") for value in result.values())


@pytest.mark.parametrize("email", ["10.1.2.3@example.test", "11111111-1111-4111-8111-111111111111@example.test"])
def test_email_detection_precedes_ip_and_guid_substitution(email):
    cleaned = BundleRedactor().deterministic({"message": email})
    assert cleaned["message"].startswith("[EMAIL_") and "@example" not in cleaned["message"]


def test_numeric_and_named_pii_fields_do_not_bypass_text_inspection():
    cleaned = BundleRedactor().deterministic({
        "credit_card": 4111111111111111, "ssn": 123456789, "display_name": "Example Person",
    })
    assert all(isinstance(value, str) and value.startswith("[") for value in cleaned.values())
    assert "Example Person" not in json.dumps(cleaned)
