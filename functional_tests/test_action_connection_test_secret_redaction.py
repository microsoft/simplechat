#!/usr/bin/env python3
# test_action_connection_test_secret_redaction.py
"""
Functional test for action connection test error sanitization.
Version: 0.250.217
Implemented in: 0.250.217

This test ensures that action Test Connection failures never echo stored
credentials back to the browser. It covers manifest-sourced secrets, generic
credential patterns in driver error text, base64-encoded secrets, and the
timeout clamp applied to every outbound connection test.

Refs microsoft/simplechat#1267
"""

import base64
import importlib.util
import os
import sys
import traceback
import types


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

TESTER_FILE = os.path.join(
    REPO_ROOT,
    "application",
    "single_app",
    "functions_action_connection_tests.py",
)


def _install_test_stubs():
    """Stub the Azure-backed modules the tester module imports at load time."""
    config_module = types.ModuleType("config")
    config_module.SECRET_KEY = "functional-test-secret"
    sys.modules["config"] = config_module

    appinsights_module = types.ModuleType("functions_appinsights")
    appinsights_module.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = appinsights_module

    mcp_operations_module = types.ModuleType("functions_mcp_operations")
    mcp_operations_module.MCP_CUSTOM_HEADERS_FIELD = "custom_headers"
    sys.modules["functions_mcp_operations"] = mcp_operations_module

    azure_maps_module = types.ModuleType("functions_azure_maps")
    azure_maps_module.AZURE_MAPS_DEFAULT_ENDPOINT = "https://atlas.microsoft.com"
    azure_maps_module.AZURE_MAPS_DEFAULT_LANGUAGE = "en-US"
    azure_maps_module.AZURE_MAPS_DEFAULT_TILESET_ID = "microsoft.base.road"
    azure_maps_module.AZURE_MAPS_DEFAULT_VIEW = "Auto"
    azure_maps_module.AZURE_MAPS_TILE_API_VERSION = "2024-04-01"
    sys.modules["functions_azure_maps"] = azure_maps_module


def _load_tester_module():
    """Load functions_action_connection_tests.py without the full app config."""
    _install_test_stubs()
    spec = importlib.util.spec_from_file_location("functions_action_connection_tests", TESTER_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the action connection test module.")

    module = importlib.util.module_from_spec(spec)
    sys.modules["functions_action_connection_tests"] = module
    spec.loader.exec_module(module)
    return module


def test_manifest_secrets_are_redacted():
    """Verify literal manifest credentials never survive into an error message."""
    print("Testing manifest secret redaction...")

    try:
        assert_app_version_at_least(
            "0.250.217",
            reason="Action connection test sanitization was added in 0.250.217.",
        )

        module = _load_tester_module()

        account_key = "Zm9vYmFyU3VwZXJTZWNyZXRBY2NvdW50S2V5PT0"
        tenant_id = "11111111-2222-3333-4444-555555555555"
        passphrase = "private-key-passphrase-value"
        header_secret = "custom-header-secret-value"

        manifest = {
            "auth": {"type": "key", "key": account_key, "tenantId": tenant_id},
            "additionalFields": {
                "private_key_passphrase": passphrase,
                "custom_headers": {"X-Api-Token": header_secret},
            },
        }

        raw_error = (
            f"Connection failed for AccountKey={account_key} tenant {tenant_id} "
            f"passphrase {passphrase} header {header_secret}"
        )
        sanitized = module.sanitize_connection_error(raw_error, manifest)

        for secret_value in (account_key, tenant_id, passphrase, header_secret):
            assert secret_value not in sanitized, (
                f"Sanitized message still contains a manifest secret: {sanitized}"
            )
        assert module.REDACTED_PLACEHOLDER in sanitized, (
            f"Sanitized message should mark redactions: {sanitized}"
        )

        print("Manifest secrets were redacted.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_generic_credential_patterns_are_redacted():
    """Verify driver error text with inline credentials is scrubbed without a manifest."""
    print("Testing generic credential pattern redaction...")

    try:
        module = _load_tester_module()

        cases = [
            ("Login failed: password=SuperSecret123!", "SuperSecret123!"),
            ("pwd=hunter2 rejected by the server", "hunter2"),
            ("DefaultEndpointsProtocol=https;AccountKey=abc123def456==;", "abc123def456=="),
            ("Rejected header Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload", "eyJhbGciOiJIUzI1NiJ9.payload"),
            ("client secret: s3cr3t-client-value", "s3cr3t-client-value"),
            ("SharedAccessSignature=sv=2021&sig=abcdef123456", "sv=2021"),
        ]

        for raw_error, secret_fragment in cases:
            sanitized = module.sanitize_connection_error(raw_error, None)
            assert secret_fragment not in sanitized, (
                f"Sanitized message leaked {secret_fragment!r}: {sanitized}"
            )

        print(f"Verified {len(cases)} generic credential patterns.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_base64_encoded_manifest_secrets_are_redacted():
    """Verify a base64-encoded credential echoed by a driver is still redacted."""
    print("Testing base64-encoded secret redaction...")

    try:
        module = _load_tester_module()

        raw_secret = "tableau-pat-secret-value"
        encoded_secret = base64.b64encode(raw_secret.encode("utf-8")).decode("ascii")
        manifest = {"auth": {"type": "key", "key": raw_secret}}

        sanitized = module.sanitize_connection_error(
            f"Upstream rejected credential {encoded_secret}",
            manifest,
        )

        assert encoded_secret not in sanitized, (
            f"Sanitized message leaked the base64 credential: {sanitized}"
        )

        print("Base64-encoded secrets were redacted.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_result_helpers_and_timeout_clamp():
    """Verify result shapes and the outbound timeout clamp used by every tester."""
    print("Testing result helpers and timeout clamp...")

    try:
        module = _load_tester_module()

        success = module.build_success_result("Connected.", warehouse_state="RUNNING", empty_value="")
        assert success["success"] is True
        assert success["status"] == 200
        assert success["details"] == {"warehouse_state": "RUNNING"}, (
            f"Empty detail values should be dropped: {success['details']}"
        )

        failure = module.build_failure_result("Nope.", status=403, http_status=401)
        assert failure["success"] is False
        assert failure["status"] == 403
        assert failure["details"] == {"http_status": 401}

        maximum = module.ACTION_CONNECTION_TEST_MAX_TIMEOUT_SECONDS
        minimum = module.ACTION_CONNECTION_TEST_MIN_TIMEOUT_SECONDS
        assert module.resolve_test_timeout(9999) == maximum, "Large timeouts must be clamped."
        assert module.resolve_test_timeout(0) == minimum, "Zero timeouts must be raised to the minimum."
        assert module.resolve_test_timeout(-5) == minimum, "Negative timeouts must be raised to the minimum."
        assert module.resolve_test_timeout("not-a-number") == module.ACTION_CONNECTION_TEST_DEFAULT_TIMEOUT_SECONDS
        assert module.resolve_test_timeout(10) == 10, "In-range timeouts must be preserved."

        short_values = module.collect_manifest_secret_values({"auth": {"key": "ab"}})
        assert short_values == [], f"Very short values should not be treated as secrets: {short_values}"

        empty_message = module.sanitize_connection_error("", None)
        assert empty_message, "An empty error must still produce a user-facing message."

        print("Result helpers and timeout clamp behaved correctly.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_all_testers_are_exported():
    """Verify every supported action type exposes a tester function."""
    print("Testing tester exports...")

    try:
        module = _load_tester_module()

        expected_testers = [
            "test_openapi_connection",
            "test_azure_maps_connection",
            "test_blob_storage_connection",
            "test_databricks_connection",
            "test_log_analytics_connection",
            "test_mcp_connection",
            "test_snowflake_connection",
            "test_tableau_connection",
        ]

        for tester_name in expected_testers:
            assert callable(getattr(module, tester_name, None)), (
                f"Missing callable tester: {tester_name}"
            )

        print(f"Verified {len(expected_testers)} exported testers.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_manifest_secrets_are_redacted,
        test_generic_credential_patterns_are_redacted,
        test_base64_encoded_manifest_secrets_are_redacted,
        test_result_helpers_and_timeout_clamp,
        test_all_testers_are_exported,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
