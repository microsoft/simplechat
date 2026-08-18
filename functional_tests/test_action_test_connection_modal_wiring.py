#!/usr/bin/env python3
# test_action_test_connection_modal_wiring.py
"""
Functional test for the action modal Test Connection wiring.
Version: 0.250.217
Implemented in: 0.250.217

This test ensures the action modal renders a Test Connection control for all
eight newly supported action types, that every button is wired to the matching
backend route, that results are rendered without an innerHTML sink, and that the
new Log Analytics Step 3 section replaces the generic form while preserving
stored additionalFields such as query_history.

Refs microsoft/simplechat#1267
"""

import os
import re
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

APP_DIR = os.path.join(REPO_ROOT, "application", "single_app")
MODAL_TEMPLATE = os.path.join(APP_DIR, "templates", "_plugin_modal.html")
STEPPER_JS = os.path.join(APP_DIR, "static", "js", "plugin_modal_stepper.js")
ROUTE_FILE = os.path.join(APP_DIR, "route_backend_plugins.py")

TEST_CONNECTION_PREFIXES = [
    "openapi",
    "azure-maps",
    "blob-storage",
    "databricks",
    "log-analytics",
    "mcp",
    "snowflake",
    "tableau",
]

LOG_ANALYTICS_FIELD_IDS = [
    "log-analytics-config-section",
    "log-analytics-workspace-id",
    "log-analytics-cloud",
    "log-analytics-endpoint",
    "log-analytics-custom-cloud-group",
    "log-analytics-authority-host",
    "log-analytics-endpoint-override",
    "log-analytics-action-identity-group",
    "log-analytics-identity-select",
    "log-analytics-identity-status",
    "log-analytics-auth-method",
    "log-analytics-auth-identity",
    "log-analytics-auth-key",
    "log-analytics-auth-tenant-id",
]


def _read(file_path):
    with open(file_path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_modal_renders_test_connection_controls():
    """Verify all eight action types render a button, result container, and alert."""
    print("Testing Test Connection markup...")

    try:
        assert_app_version_at_least(
            "0.250.217",
            reason="Action Test Connection controls were added in 0.250.217.",
        )

        template_source = _read(MODAL_TEMPLATE)

        for prefix in TEST_CONNECTION_PREFIXES:
            for suffix in ("btn", "result", "alert"):
                element_id = f'id="{prefix}-test-connection-{suffix}"'
                assert element_id in template_source, f"Missing modal element: {element_id}"

            assert f'id="{prefix}-test-connection-result" class="mt-2 d-none"' in template_source, (
                f"The {prefix} test connection result must start hidden with the Bootstrap d-none class."
            )

        print(f"Verified Test Connection markup for {len(TEST_CONNECTION_PREFIXES)} action types.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_buttons_are_wired_to_matching_backend_routes():
    """Verify the stepper config maps every button prefix to a registered route."""
    print("Testing Test Connection button wiring...")

    try:
        stepper_source = _read(STEPPER_JS)
        route_source = _read(ROUTE_FILE)

        config_match = re.search(
            r"const ACTION_CONNECTION_TEST_CONFIG = \{(.*?)\n\};",
            stepper_source,
            re.DOTALL,
        )
        assert config_match, "ACTION_CONNECTION_TEST_CONFIG was not found in plugin_modal_stepper.js."

        entries = re.findall(
            r"(\w+):\s*\{\s*idPrefix:\s*'([^']+)',\s*url:\s*'([^']+)'",
            config_match.group(1),
        )
        assert len(entries) == len(TEST_CONNECTION_PREFIXES), (
            f"Expected {len(TEST_CONNECTION_PREFIXES)} test connection entries, found {len(entries)}."
        )

        configured_prefixes = sorted(prefix for _key, prefix, _url in entries)
        assert configured_prefixes == sorted(TEST_CONNECTION_PREFIXES), (
            f"Configured prefixes do not match the modal markup: {configured_prefixes}"
        )

        for _key, prefix, url in entries:
            assert f"@bpap.route('{url}', methods=['POST'])" in route_source, (
                f"The {prefix} test connection URL {url} is not registered in route_backend_plugins.py."
            )

        assert "ACTION_CONNECTION_TEST_CONFIG).forEach(testKey" in stepper_source, (
            "bindEvents must attach a click handler for every configured test connection button."
        )
        assert "this.runActionConnectionTest(testKey)" in stepper_source, (
            "Test connection buttons must call runActionConnectionTest."
        )

        print(f"Verified {len(entries)} button-to-route mappings.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_results_render_without_an_inner_html_sink():
    """Verify server-provided test messages are rendered through DOM text nodes."""
    print("Testing Test Connection result rendering...")

    try:
        stepper_source = _read(STEPPER_JS)

        renderer_match = re.search(
            r"showActionConnectionTestMessage\(testKey, variant, message, iconClass = ''\) \{(.*?)\n  \}",
            stepper_source,
            re.DOTALL,
        )
        assert renderer_match, "showActionConnectionTestMessage was not found."

        renderer_body = renderer_match.group(1)
        assert "innerHTML" not in renderer_body, (
            "Test connection results must not use innerHTML for server-provided text."
        )
        assert "createTextNode(message)" in renderer_body, (
            "Test connection results must render the message as a text node."
        )
        assert "replaceChildren()" in renderer_body, (
            "Test connection results must clear prior content with DOM APIs."
        )

        runner_match = re.search(
            r"async runActionConnectionTest\(testKey\) \{(.*?)\n  \}\n\n  initializeSqlConfiguration",
            stepper_source,
            re.DOTALL,
        )
        assert runner_match, "runActionConnectionTest was not found."
        assert "innerHTML" not in runner_match.group(1), (
            "runActionConnectionTest must not use innerHTML for the button loading state."
        )

        print("Test connection results avoid innerHTML sinks.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_log_analytics_section_replaces_the_generic_form():
    """Verify the Log Analytics Step 3 section exists and is treated as structured config."""
    print("Testing Log Analytics configuration section...")

    try:
        template_source = _read(MODAL_TEMPLATE)
        stepper_source = _read(STEPPER_JS)

        for element_id in LOG_ANALYTICS_FIELD_IDS:
            assert f'id="{element_id}"' in template_source, f"Missing Log Analytics element: {element_id}"

        assert "const LOG_ANALYTICS_PLUGIN_TYPE = 'log_analytics';" in stepper_source, (
            "The stepper must declare the log_analytics plugin type constant."
        )
        assert "isLogAnalyticsType(type = this.selectedType)" in stepper_source, (
            "The stepper must expose an isLogAnalyticsType predicate."
        )

        structured_match = re.search(
            r"isStructuredConfigType\(type = this\.selectedType\) \{\s*return ([^;]+);",
            stepper_source,
        )
        assert structured_match, "isStructuredConfigType was not found."
        assert "this.isLogAnalyticsType(type)" in structured_match.group(1), (
            "log_analytics must be a structured config type so Step 4 stops rendering duplicate fields."
        )

        assert "logAnalytics: document.getElementById('log-analytics-config-section')" in stepper_source, (
            "The Log Analytics section must be registered in showConfigSectionForType."
        )
        assert "this.initializeLogAnalyticsConfiguration();" in stepper_source, (
            "Selecting the Log Analytics type must initialize its configuration section."
        )
        assert "logAnalytics: 'log-analytics-identity-select'" in stepper_source, (
            "Log Analytics must support reusable workspace identities."
        )

        print(f"Verified {len(LOG_ANALYTICS_FIELD_IDS)} Log Analytics elements and stepper wiring.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


def test_log_analytics_preserves_stored_additional_fields():
    """Verify getLogAnalyticsConfiguration keeps stored fields such as query_history."""
    print("Testing Log Analytics additionalFields preservation...")

    try:
        stepper_source = _read(STEPPER_JS)

        config_match = re.search(
            r"getLogAnalyticsConfiguration\(\) \{(.*?)\n  \}",
            stepper_source,
            re.DOTALL,
        )
        assert config_match, "getLogAnalyticsConfiguration was not found."

        config_body = config_match.group(1)
        assert "this.originalPlugin?.additionalFields" in config_body, (
            "Log Analytics config must seed additionalFields from the stored action."
        )
        assert "query_history" in config_body, (
            "Log Analytics config must preserve or default the required query_history field."
        )
        assert "Array.isArray(additionalFields.query_history)" in config_body, (
            "query_history must default to an array when it is missing."
        )
        assert "additionalFields.workspaceId" in config_body, (
            "Log Analytics config must write the workspaceId field."
        )
        assert "delete additionalFields.authorityHost" in config_body, (
            "Custom-cloud fields must be cleared when the cloud is not custom."
        )

        print("Log Analytics configuration preserves stored additionalFields.")
        print("Test passed!")
        return True

    except Exception as e:
        print(f"Test failed: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_modal_renders_test_connection_controls,
        test_buttons_are_wired_to_matching_backend_routes,
        test_results_render_without_an_inner_html_sink,
        test_log_analytics_section_replaces_the_generic_form,
        test_log_analytics_preserves_stored_additional_fields,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
