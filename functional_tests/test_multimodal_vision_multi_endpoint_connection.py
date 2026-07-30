# test_multimodal_vision_multi_endpoint_connection.py
#!/usr/bin/env python3
"""
Functional test for multi-endpoint Vision test connection wiring.
Version: 0.250.008
Implemented in: 0.250.008

This test ensures the admin Vision Model test button preserves multi-endpoint
selection metadata and the backend resolves the selected endpoint from saved
settings instead of always using the legacy GPT endpoint.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_SETTINGS_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_settings.js"
ADMIN_SETTINGS_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
ROUTE_BACKEND_SETTINGS = REPO_ROOT / "application" / "single_app" / "route_backend_settings.py"


def assert_contains(content, expected, description):
    """Assert a source file contains expected text."""
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_multimodal_vision_multi_endpoint_wiring():
    """Validate frontend payload metadata and backend endpoint resolution."""
    print("Testing multi-endpoint Vision test connection wiring...")

    js_content = ADMIN_SETTINGS_JS.read_text(encoding="utf-8")
    template_content = ADMIN_SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    backend_content = ROUTE_BACKEND_SETTINGS.read_text(encoding="utf-8")

    assert_contains(js_content, "opt.dataset.endpointId = ep.id || '';", "vision endpoint id option metadata")
    assert_contains(js_content, "opt.dataset.modelId = m.id || '';", "vision model id option metadata")
    assert_contains(js_content, "payload.multi_endpoint = {", "vision test multi-endpoint payload")
    assert_contains(js_content, "endpoint_id: selectedVisionOption.dataset.endpointId", "vision test endpoint id payload field")
    assert_contains(js_content, "model_id: selectedVisionOption.dataset.modelId", "vision test model id payload field")

    assert_contains(template_content, 'data-endpoint-id="{{ endpoint.id or \'\' }}"', "template endpoint id metadata")
    assert_contains(template_content, 'data-model-id="{{ m.id or \'\' }}"', "template model id metadata")

    function_count = backend_content.count("def _test_multimodal_vision_connection(payload):")
    if function_count != 1:
        raise AssertionError(f"Expected one _test_multimodal_vision_connection function, found {function_count}")

    assert_contains(backend_content, "resolve_model_endpoint_from_context(settings, model_context)", "backend multi-endpoint resolution")
    assert_contains(backend_content, "build_model_endpoint_sync_chat_client(", "backend multi-endpoint client creation")
    assert_contains(backend_content, "vision_model_name_lower", "backend modelName token parameter selection")

    print("Multi-endpoint Vision test connection wiring passed.")
    return True


if __name__ == "__main__":
    try:
        success = test_multimodal_vision_multi_endpoint_wiring()
    except Exception as exc:
        print(f"Test failed: {exc}")
        sys.exit(1)

    sys.exit(0 if success else 1)