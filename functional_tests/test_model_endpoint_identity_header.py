#!/usr/bin/env python3
# test_model_endpoint_identity_header.py
"""
Functional test for model endpoint identity headers.
Version: 0.250.203
Implemented in: 0.250.203

This test ensures configurable model endpoint identity headers produce stable,
non-reversible HMAC values and honor endpoint-level override behavior.
"""

import hashlib
import hmac
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "application", "single_app"))

from functions_model_endpoint_identity_header import (
    DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_NAME,
    build_model_endpoint_identity_headers,
    normalize_model_endpoint_identity_header_override,
    resolve_effective_model_endpoint_identity_header_config,
)
from test_support.versioning import assert_app_version_at_least


IMPLEMENTED_VERSION = "0.250.203"
TEST_SECRET = "test-secret-for-identity-header"


def _settings(**overrides):
    settings = {
        "model_endpoint_identity_header_enabled": True,
        "model_endpoint_identity_header_name": DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_NAME,
        "model_endpoint_identity_header_value_type": "user_oid_tenant_id",
        "model_endpoint_identity_header_hmac_secret": TEST_SECRET,
    }
    settings.update(overrides)
    return settings


def _expected_digest(canonical_identity):
    return hmac.new(
        TEST_SECRET.encode("utf-8"),
        canonical_identity.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def test_identity_header_stable_hmac_value():
    """Validate stable HMAC output without leaking raw identity values."""
    print("Testing model endpoint identity header HMAC generation...")

    identity_context = {
        "user_id": "User-OID-123",
        "tenant_id": "Tenant-456",
        "preferred_username": "user@example.com",
    }
    headers = build_model_endpoint_identity_headers(_settings(), identity_context=identity_context)
    header_value = headers[DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_NAME]

    assert header_value == _expected_digest("user_oid_tenant_id:user-oid-123|tenant-456")
    assert len(header_value) == 64
    assert "User-OID-123" not in header_value
    assert "Tenant-456" not in header_value
    assert "user@example.com" not in header_value

    equivalent_headers = build_model_endpoint_identity_headers(
        _settings(),
        identity_context={
            "oid": "user-oid-123",
            "tid": "tenant-456",
            "upn": "USER@EXAMPLE.COM",
        },
    )
    assert equivalent_headers == headers

    print("Model endpoint identity header HMAC generation passed.")
    return True


def test_identity_header_disable_and_missing_identity_behavior():
    """Validate disabled settings and incomplete identity values omit the header."""
    print("Testing disabled and incomplete identity behavior...")

    assert build_model_endpoint_identity_headers(
        _settings(model_endpoint_identity_header_enabled=False),
        identity_context={"user_id": "user-1", "tenant_id": "tenant-1"},
    ) == {}
    assert build_model_endpoint_identity_headers(
        _settings(model_endpoint_identity_header_value_type="user_oid_tenant_id"),
        identity_context={"user_id": "user-1"},
    ) == {}
    assert build_model_endpoint_identity_headers(
        _settings(model_endpoint_identity_header_hmac_secret=""),
        identity_context={"user_id": "user-1", "tenant_id": "tenant-1"},
    ) == {}

    print("Disabled and incomplete identity behavior passed.")
    return True


def test_identity_header_endpoint_override_behavior():
    """Validate per-endpoint override modes, value types, and header names."""
    print("Testing endpoint identity header override behavior...")

    global_settings = _settings(
        model_endpoint_identity_header_name="x-global-identity",
        model_endpoint_identity_header_value_type="user_upn_tenant_id",
    )
    identity_context = {
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "preferred_username": "person@example.com",
    }

    inherited_headers = build_model_endpoint_identity_headers(
        global_settings,
        endpoint_config={"identity_header": {"mode": "inherit"}},
        identity_context=identity_context,
    )
    assert inherited_headers == {
        "x-global-identity": _expected_digest("user_upn_tenant_id:person@example.com|tenant-1")
    }

    endpoint_headers = build_model_endpoint_identity_headers(
        global_settings,
        endpoint_config={
            "identity_header": {
                "mode": "enabled",
                "header_name": "x-endpoint-identity",
                "value_type": "user_oid",
            }
        },
        identity_context=identity_context,
    )
    assert endpoint_headers == {
        "x-endpoint-identity": _expected_digest("user_oid:user-1")
    }

    disabled_headers = build_model_endpoint_identity_headers(
        global_settings,
        endpoint_config={"identity_header": {"mode": "disabled"}},
        identity_context=identity_context,
    )
    assert disabled_headers == {}

    enabled_from_endpoint = build_model_endpoint_identity_headers(
        _settings(model_endpoint_identity_header_enabled=False),
        endpoint_config={"identity_header": {"mode": "enabled"}},
        identity_context={"user_id": "user-2", "tenant_id": "tenant-2"},
    )
    assert enabled_from_endpoint == {
        DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_NAME: _expected_digest("user_oid_tenant_id:user-2|tenant-2")
    }

    print("Endpoint identity header override behavior passed.")
    return True


def test_identity_header_normalization_guardrails():
    """Validate unsafe names are rejected and blank endpoint values inherit global settings."""
    print("Testing identity header normalization guardrails...")

    override = normalize_model_endpoint_identity_header_override({
        "mode": "inherit",
        "header_name": "Authorization",
        "value_type": "",
    })
    assert override == {
        "mode": "inherit",
        "header_name": "",
        "value_type": "",
    }

    effective_config = resolve_effective_model_endpoint_identity_header_config(
        _settings(
            model_endpoint_identity_header_name="Authorization",
            model_endpoint_identity_header_value_type="user_upn",
        ),
        endpoint_config={"identity_header": {"mode": "inherit", "value_type": ""}},
    )
    assert effective_config["header_name"] == DEFAULT_MODEL_ENDPOINT_IDENTITY_HEADER_NAME
    assert effective_config["value_type"] == "user_upn"

    print("Identity header normalization guardrails passed.")
    return True


def test_app_version_has_identity_header_feature():
    """Validate the app version is at least the implementation version."""
    print("Testing app version marker for model endpoint identity headers...")

    assert_app_version_at_least(IMPLEMENTED_VERSION)

    print("App version marker passed.")
    return True


if __name__ == "__main__":
    tests = [
        test_identity_header_stable_hmac_value,
        test_identity_header_disable_and_missing_identity_behavior,
        test_identity_header_endpoint_override_behavior,
        test_identity_header_normalization_guardrails,
        test_app_version_has_identity_header_feature,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as ex:
            print(f"Test failed: {ex}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
