#!/usr/bin/env python3
"""
Functional test for settings and secrets exposure hardening.
Version: 0.242.059
Implemented in: 0.242.059

This test ensures Admin Settings redacts stored secrets from browser markup while
preserving stored values on save/test, and verifies plugin/TTS error paths do not
return or log raw secret-bearing service diagnostics.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ADMIN_ROUTE = os.path.join(REPO_ROOT, "application", "single_app", "route_frontend_admin_settings.py")
SETTINGS_HELPER = os.path.join(REPO_ROOT, "application", "single_app", "functions_settings.py")
SETTINGS_TEST_ROUTE = os.path.join(REPO_ROOT, "application", "single_app", "route_backend_settings.py")
ADMIN_TEMPLATE = os.path.join(REPO_ROOT, "application", "single_app", "templates", "admin_settings.html")
AZURE_BILLING_PLUGIN = os.path.join(
    REPO_ROOT,
    "application",
    "community_customizations",
    "actions",
    "azure_billing_retriever",
    "azure_billing_plugin.py",
)
TTS_ROUTE = os.path.join(REPO_ROOT, "application", "single_app", "route_backend_tts.py")

ADMIN_SECRET_FIELDS = [
    "azure_openai_gpt_key",
    "azure_apim_gpt_subscription_key",
    "azure_openai_embedding_key",
    "azure_apim_embedding_subscription_key",
    "azure_openai_image_gen_key",
    "azure_apim_image_gen_subscription_key",
    "redis_key",
    "office_docs_storage_account_url",
    "office_docs_storage_account_blob_endpoint",
    "video_files_storage_account_url",
    "audio_files_storage_account_url",
    "content_safety_key",
    "azure_apim_content_safety_subscription_key",
    "azure_ai_search_key",
    "azure_apim_ai_search_subscription_key",
    "azure_document_intelligence_key",
    "azure_apim_document_intelligence_subscription_key",
    "speech_service_key",
]

TEST_PAYLOAD_MAPPINGS = [
    "azure_openai_gpt_key",
    "azure_apim_gpt_subscription_key",
    "azure_openai_embedding_key",
    "azure_apim_embedding_subscription_key",
    "azure_openai_image_gen_key",
    "azure_apim_image_gen_subscription_key",
    "content_safety_key",
    "azure_apim_content_safety_subscription_key",
    "azure_ai_search_key",
    "azure_apim_ai_search_subscription_key",
    "azure_document_intelligence_key",
    "azure_apim_document_intelligence_subscription_key",
    "redis_key",
    "web_search_agent.other_settings.azure_ai_foundry.client_secret",
]


def read_source(path):
    with open(path, "r", encoding="utf-8") as source_file:
        return source_file.read()


def assert_contains(source, needle, description):
    if needle not in source:
        raise AssertionError(f"Missing {description}: {needle}")


def assert_not_contains(source, needle, description):
    if needle in source:
        raise AssertionError(f"Unexpected {description}: {needle}")


def test_admin_secret_redaction_and_preservation():
    """Admin Settings should render redacted values and preserve stored submissions."""
    print("Testing Admin Settings secret redaction and preservation wiring...")
    helper_source = read_source(SETTINGS_HELPER)
    admin_route_source = read_source(ADMIN_ROUTE)
    template_source = read_source(ADMIN_TEMPLATE)

    assert_contains(helper_source, 'ADMIN_SETTINGS_SECRET_REDACTED_VALUE = "***REDACTED***"', "redaction sentinel")
    assert_contains(helper_source, "def resolve_admin_settings_secret_value", "secret preservation helper")
    assert_contains(helper_source, "def redact_admin_settings_secrets_for_form", "form redaction helper")
    assert_contains(admin_route_source, "settings_for_template = redact_admin_settings_secrets_for_form(settings_for_template)", "admin GET redaction")
    assert_contains(template_source, 'id="admin-settings-form"', "admin settings form")

    for field_name in ADMIN_SECRET_FIELDS:
        assert_contains(helper_source, f'"{field_name}"', f"registered secret field {field_name}")
        assert_contains(admin_route_source, f"admin_secret('{field_name}'", f"save preservation for {field_name}")
        assert_not_contains(
            admin_route_source,
            f"'{field_name}': form_data.get('{field_name}', '').strip()",
            f"raw save assignment for {field_name}",
        )

    assert_contains(
        helper_source,
        '"web_search_agent.other_settings.azure_ai_foundry.client_secret"',
        "nested web search secret field",
    )
    assert_contains(
        admin_route_source,
        "admin_secret(\n                                'web_search_agent.other_settings.azure_ai_foundry.client_secret'",
        "nested web search secret preservation",
    )
    print("Admin Settings secret redaction and preservation wiring passed.")
    return True


def test_admin_connection_tests_resolve_stored_secrets():
    """Admin Test Connection payloads should resolve the redacted sentinel server-side."""
    print("Testing Admin Settings test-connection stored secret resolution...")
    source = read_source(SETTINGS_TEST_ROUTE)

    assert_contains(source, "def _resolve_admin_settings_test_secrets", "test payload resolver")
    assert_contains(source, "data = _resolve_admin_settings_test_secrets(data)", "test resolver invocation")
    for field_name in TEST_PAYLOAD_MAPPINGS:
        assert_contains(source, field_name, f"test payload mapping for {field_name}")
    print("Admin Settings test-connection stored secret resolution passed.")
    return True


def test_azure_billing_token_errors_are_sanitized():
    """Azure Billing service principal token failures should not log/raise raw token response details."""
    print("Testing Azure Billing token error sanitization...")
    source = read_source(AZURE_BILLING_PLUGIN)

    assert_contains(source, "AZURE_BILLING_AUTH_FAILURE_MESSAGE", "generic billing auth failure message")
    assert_contains(source, "[AzureBilling] Service principal token request failed.", "billing auth log event")
    assert_not_contains(source, "URL=%s, Error=%s, Response=%s", "raw token URL/response logging")
    assert_not_contains(source, "Response: {resp_text}", "raw HTTP response in raised error")
    assert_not_contains(source, "Response: {resp.text}", "raw token endpoint response in raised error")
    assert_not_contains(source, "Invalid JSON returned from token endpoint: {resp.text}", "raw invalid JSON response")
    print("Azure Billing token error sanitization passed.")
    return True


def test_tts_client_errors_are_generic():
    """TTS should log detailed failures server-side while returning generic client errors."""
    print("Testing TTS client-facing error hardening...")
    source = read_source(TTS_ROUTE)

    assert_contains(source, "TTS_CONFIG_ERROR_MESSAGE", "generic TTS config error message")
    assert_contains(source, "TTS_SYNTHESIS_ERROR_MESSAGE", "generic TTS synthesis error message")
    assert_contains(source, "[TTS] Speech synthesis failed.", "server-side TTS failure log")
    assert_not_contains(source, 'return jsonify({"error": error_msg})', "raw TTS cancellation response")
    assert_not_contains(source, 'return jsonify({"error": f"TTS synthesis failed: {str(e)}"})', "raw TTS exception response")
    assert_not_contains(source, 'return jsonify({"error": str(config_error)})', "raw TTS configuration response")
    print("TTS client-facing error hardening passed.")
    return True


def main():
    """Run all settings and secrets exposure hardening checks."""
    tests = [
        test_admin_secret_redaction_and_preservation,
        test_admin_connection_tests_resolve_stored_secrets,
        test_azure_billing_token_errors_are_sanitized,
        test_tts_client_errors_are_generic,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    test_success = main()
    sys.exit(0 if test_success else 1)
