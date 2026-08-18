#!/usr/bin/env python3
# test_log_credential_key_redaction.py
"""
Functional test for credential key redaction in application logging.
Version: 0.250.218
Implemented in: 0.250.218

This test ensures that credential-bearing property names reach the logging sinks
redacted. Before this fix, `_is_sensitive_log_key` matched only a fixed list of
substrings, so the field names this codebase actually uses for plugin secrets --
notably `auth_key` and the plugin manifest's `auth.key` -- were logged in clear
text through `log_event`.

It also guards the opposite failure: benign configuration keys that merely contain
the word "key" (`key_encoding`, `partition_key_path`, `key_prefix_hints`) must stay
visible so logs remain useful for diagnostics.
"""

import io
import os
import sys
import types
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

from test_support.versioning import assert_app_version_at_least


SECRET_VALUE = "SuperSecretCredentialValue123"


def install_cosmos_stub():
    """Let config.py import without contacting a live Cosmos account."""
    import azure.cosmos as azure_cosmos

    class StubContainer:
        def read_item(self, item, partition_key=None):
            if item == "app_settings":
                return {"id": "app_settings", "settings": {}}
            raise KeyError(item)

        def upsert_item(self, item):
            return item

        def query_items(self, *args, **kwargs):
            return []

    class StubDatabase:
        def create_container_if_not_exists(self, id, **kwargs):
            return StubContainer()

    class StubClient:
        def __init__(self, *args, **kwargs):
            pass

        def create_database_if_not_exists(self, *args, **kwargs):
            return StubDatabase()

    original_client = azure_cosmos.CosmosClient
    azure_cosmos.CosmosClient = StubClient
    return azure_cosmos, original_client


def get_appinsights_module():
    azure_cosmos, original_client = install_cosmos_stub()
    try:
        import functions_appinsights
        return functions_appinsights
    finally:
        azure_cosmos.CosmosClient = original_client


# Credential-bearing names that must never be logged in clear text. Each of these
# is either used by this codebase or is a common Azure credential field name.
SENSITIVE_KEY_NAMES = (
    "auth_key",
    "authKey",
    "auth-key",
    "key",
    "keys",
    "pwd",
    "pass",
    "passphrase",
    "password",
    "api_key",
    "account_key",
    "client_secret",
    "connection_string",
    "access_token",
    "bearer_token",
    "key_pair",
    "master_key",
    "primary_key",
    "secondary_key",
    "encryption_key",
    "signing_key",
    "session_key",
    "storage_key",
    "private_key",
    "subscription_key",
    "sig",
    "signature",
    "shared_access_signature",
    "credential",
    "authorization",
)

# Benign configuration names that must stay readable in logs.
NON_SENSITIVE_KEY_NAMES = (
    "key_encoding",
    "key_prefix_hints",
    "partition_key_path",
    "key_vault_name",
    "column_family",
    "max_results",
    "max_value_bytes",
    "timeout",
    "read_only",
    "keyboard",
    "keyword",
    "monkey",
    "turkey",
    "public_key_id",
    "agent_signal",
    "connection_mode",
)


def test_sensitive_key_names_are_classified_as_secrets():
    """Test that credential field names are recognized as sensitive."""
    print("Testing credential key classification...")

    try:
        functions_appinsights = get_appinsights_module()

        missed = [
            key_name for key_name in SENSITIVE_KEY_NAMES
            if not functions_appinsights._is_sensitive_log_key(key_name)
        ]
        assert not missed, f"These credential key names are not treated as sensitive: {missed}"

        print("Credential key names are classified as sensitive.")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_benign_configuration_keys_stay_visible():
    """Test that ordinary configuration keys are not over-redacted."""
    print("Testing that benign configuration keys stay visible...")

    try:
        functions_appinsights = get_appinsights_module()

        over_redacted = [
            key_name for key_name in NON_SENSITIVE_KEY_NAMES
            if functions_appinsights._is_sensitive_log_key(key_name)
        ]
        assert not over_redacted, (
            f"These benign configuration keys are redacted and would lose diagnostic value: {over_redacted}"
        )

        print("Benign configuration keys remain visible.")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_sanitize_log_properties_redacts_nested_credentials():
    """Test that credentials are redacted at any nesting depth."""
    print("Testing nested credential redaction...")

    try:
        functions_appinsights = get_appinsights_module()
        sanitize = functions_appinsights.sanitize_log_properties

        shapes = [
            {"auth_key": SECRET_VALUE},
            # The shape of a plugin manifest auth block from plugin.schema.json.
            {"auth": {"type": "key", "key": SECRET_VALUE}},
            {"plugin": {"auth": {"key": SECRET_VALUE}}},
            {"items": [{"auth_key": SECRET_VALUE}]},
            {"settings": {"nested": {"deeper": {"password": SECRET_VALUE}}}},
            {"credentials": [{"pwd": SECRET_VALUE}, {"master_key": SECRET_VALUE}]},
        ]

        for shape in shapes:
            sanitized_text = str(sanitize(shape))
            assert SECRET_VALUE not in sanitized_text, (
                f"Secret survived sanitization for shape {shape!r}: {sanitized_text}"
            )

        print("Nested credentials are redacted at every depth.")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_log_event_does_not_emit_credentials():
    """Test end to end that log_event never prints a credential in clear text."""
    print("Testing log_event output for credential leaks...")

    try:
        functions_appinsights = get_appinsights_module()

        leaking_cases = [
            ("auth_key property", {"auth_key": SECRET_VALUE}),
            ("plugin manifest auth block", {"auth": {"type": "key", "key": SECRET_VALUE}}),
            ("bare key property", {"key": SECRET_VALUE}),
            ("pwd property", {"pwd": SECRET_VALUE}),
            ("list of credential objects", {"items": [{"auth_key": SECRET_VALUE}]}),
            ("account key property", {"account_key": SECRET_VALUE}),
        ]

        for label, extra in leaking_cases:
            captured_output = io.StringIO()
            with redirect_stdout(captured_output):
                functions_appinsights.log_event("credential redaction probe", extra=extra)
            assert SECRET_VALUE not in captured_output.getvalue(), (
                f"log_event leaked a credential for {label}: {captured_output.getvalue()}"
            )

        # Message text using the key=value convention is still redacted.
        captured_output = io.StringIO()
        with redirect_stdout(captured_output):
            functions_appinsights.log_event(f"connect failed password={SECRET_VALUE}")
        assert SECRET_VALUE not in captured_output.getvalue(), (
            "log_event leaked a credential embedded in the message text"
        )

        print("log_event does not emit credentials in clear text.")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_logger_extra_reports_presence_without_values():
    """Test that the structured log record reports presence rather than the secret."""
    print("Testing structured log record properties...")

    try:
        functions_appinsights = get_appinsights_module()

        logger_extra = functions_appinsights._build_logger_extra(
            "probe", {"auth_key": SECRET_VALUE, "column_family": "events"}
        )
        serialized = str(logger_extra)

        assert SECRET_VALUE not in serialized, f"Secret reached the log record: {serialized}"
        assert any(key.endswith("_present") for key in logger_extra), (
            "The log record should report that a credential was supplied without its value"
        )

        print("Structured log record omits credential values.")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_cosmos_client_imports_are_module_qualified():
    """Test that helper scripts look up CosmosClient on the module at runtime."""
    print("Testing CosmosClient import bindings...")

    try:
        assert_app_version_at_least("0.250.218")

        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        checked_files = (
            os.path.join(root_dir, "scripts", "resolve_multiendpoint_gpt.py"),
            os.path.join(root_dir, "deployers", "bicep", "postconfig.py"),
        )

        for file_path in checked_files:
            with open(file_path, "r", encoding="utf-8") as file_handle:
                source = file_handle.read()

            assert "from azure.cosmos import CosmosClient" not in source, (
                f"{os.path.basename(file_path)} still binds CosmosClient directly, so patching "
                "azure.cosmos.CosmosClient would not be observed"
            )
            assert "import azure.cosmos as azure_cosmos" in source, (
                f"{os.path.basename(file_path)} should import the Cosmos module"
            )
            assert "azure_cosmos.CosmosClient(" in source, (
                f"{os.path.basename(file_path)} should construct the client through the module"
            )

        print("CosmosClient is resolved through the module in helper scripts.")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_sensitive_key_names_are_classified_as_secrets,
        test_benign_configuration_keys_stay_visible,
        test_sanitize_log_properties_redacts_nested_credentials,
        test_log_event_does_not_emit_credentials,
        test_logger_extra_reports_presence_without_values,
        test_cosmos_client_imports_are_module_qualified,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
