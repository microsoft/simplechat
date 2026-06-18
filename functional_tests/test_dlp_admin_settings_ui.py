# test_dlp_admin_settings_ui.py
#!/usr/bin/env python3
"""
Functional test for DLP admin settings UI.
Version: 0.242.074
Implemented in: 0.242.073

This test ensures shared and web-search DLP defaults exist, admin settings
persist supported controls, the admin template exposes only implemented controls,
and new DLP JavaScript uses Bootstrap d-none instead of JavaScript display toggles.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(ROOT_DIR, "application", "single_app", "functions_settings.py")
ADMIN_ROUTE_FILE = os.path.join(ROOT_DIR, "application", "single_app", "route_frontend_admin_settings.py")
ADMIN_TEMPLATE_FILE = os.path.join(ROOT_DIR, "application", "single_app", "templates", "admin_settings.html")
ADMIN_JS_FILE = os.path.join(ROOT_DIR, "application", "single_app", "static", "js", "admin", "admin_settings.js")


REQUIRED_KEYS = [
    "enable_dlp_control_plane",
    "dlp_default_engine",
    "dlp_regex_rules",
    "dlp_max_scan_chars",
    "dlp_fail_closed_on_scanner_error",
    "dlp_audit_level",
    "dlp_enable_structured_telemetry",
    "dlp_telemetry_sample_allow_events",
    "dlp_review_destination",
    "enable_web_search_dlp",
    "web_search_dlp_mode",
    "enable_upload_dlp",
    "upload_dlp_mode",
    "upload_dlp_fail_upload_on_match",
]


UNSUPPORTED_ADMIN_CONTROL_IDS = [
    "dlp_presidio_use_service",
    "dlp_presidio_service_settings",
    "dlp_scanner_timeout_seconds",
    "dlp_review_include_redacted_preview",
    "web_search_dlp_track_review_events",
    "upload_dlp_track_review_events",
]

PRESIDIO_ENDPOINT_CONTROL_IDS = [
    "dlp_presidio_endpoint_settings",
    "dlp_presidio_analyzer_endpoint",
    "dlp_presidio_auth_header_name",
    "dlp_presidio_auth_secret_env_var",
    "dlp_presidio_timeout_seconds",
    "dlp_presidio_score_threshold",
    "dlp_presidio_language",
    "dlp_presidio_entities",
]


RETIRED_DLP_SETTING_KEYS = [
    "dlp_presidio_use_service",
    "dlp_presidio_endpoint",
    "dlp_scanner_timeout_seconds",
    "dlp_review_include_redacted_preview",
    "web_search_dlp_track_review_events",
    "upload_dlp_track_review_events",
]


def read_file_text(path):
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def assert_no_retired_structured_redaction_control(source, source_name):
    """Retired structured-redaction controls should not appear in admin DLP sources."""
    redaction_prefix = "web_search_dlp_redact"
    for line_number, line in enumerate(source.splitlines(), start=1):
        normalized = line.lower()
        has_retired_prefix = redaction_prefix in normalized
        has_structured_identifier_wording = "structured" in normalized and "identifier" in normalized
        assert not (has_retired_prefix and has_structured_identifier_wording), (
            f"Retired structured-redaction DLP control remains in {source_name}:{line_number}"
        )


def test_dlp_defaults_exist_and_are_safe():
    """Defaults should include shared/web-search DLP and keep review disabled."""
    print("Testing DLP defaults...")
    source = read_file_text(SETTINGS_FILE)

    for key in REQUIRED_KEYS:
        assert f"'{key}'" in source, f"Missing DLP default setting: {key}"

    assert "'dlp_review_destination': 'none'" in source
    assert "'enable_web_search_dlp': False" in source
    assert "raw_matches" not in source

    for key in RETIRED_DLP_SETTING_KEYS:
        assert f"'{key}'" not in source, f"Retired DLP default setting remains: {key}"
    assert_no_retired_structured_redaction_control(source, SETTINGS_FILE)


def test_admin_route_persists_dlp_settings():
    """Admin settings route should persist all PR1 DLP fields."""
    print("Testing DLP admin route persistence...")
    source = read_file_text(ADMIN_ROUTE_FILE)

    for key in REQUIRED_KEYS:
        assert key in source, f"Admin route does not persist or normalize {key}"


def test_admin_template_exposes_dlp_controls():
    """Admin UI should expose supported shared and web-search DLP controls."""
    print("Testing DLP admin template controls...")
    source = read_file_text(ADMIN_TEMPLATE_FILE)

    assert "Data Loss Prevention" in source
    assert 'id="dlp_control_plane_settings"' in source
    assert 'id="web_search_dlp_settings"' in source
    for key in REQUIRED_KEYS:
        if key == "dlp_regex_rules":
            assert 'id="dlp_regex_rules_json"' in source
            assert 'name="dlp_regex_rules_json"' in source
        else:
            assert f'id="{key}"' in source or f'name="{key}"' in source, f"Missing DLP control: {key}"

    assert 'value="none"' in source
    assert 'value="safety_violations"' not in source, (
        "Safety Violations destination should stay hidden unless PR1 implements reachable review integration"
    )
    assert 'value="regex"' in source
    assert 'value="presidio_endpoint"' in source
    assert "Regex structured identifier scan" in source
    assert "External Presidio Analyzer endpoint" in source
    assert "Use regex for lightweight built-in scanning" in source
    assert "Custom Regex Rules" in source
    assert "{{ dlp_regex_rules_json }}" in source
    assert "web_search_dlp_block_on_internal_phrases" not in source
    assert "Detect internal phrases" not in source

    for unsupported_id in UNSUPPORTED_ADMIN_CONTROL_IDS:
        assert unsupported_id not in source, f"Unsupported DLP control is still visible: {unsupported_id}"

    assert_no_retired_structured_redaction_control(source, ADMIN_TEMPLATE_FILE)


def test_presidio_endpoint_controls_are_rendered_without_secret_value_field():
    """DLP admin UI should configure endpoint metadata but not store raw API keys."""
    print("Testing Presidio endpoint admin controls...")
    source = read_file_text(ADMIN_TEMPLATE_FILE)

    for control_id in PRESIDIO_ENDPOINT_CONTROL_IDS:
        assert f'id="{control_id}"' in source, f"Missing Presidio endpoint control: {control_id}"

    assert 'name="dlp_presidio_analyzer_endpoint"' in source
    assert 'name="dlp_presidio_auth_header_name"' in source
    assert 'name="dlp_presidio_auth_secret_env_var"' in source
    assert 'name="dlp_presidio_timeout_seconds"' in source
    assert 'name="dlp_presidio_score_threshold"' in source
    assert 'name="dlp_presidio_language"' in source
    assert 'name="dlp_presidio_entities"' in source
    assert 'name="dlp_presidio_auth_secret"' not in source
    assert "production endpoints should be private, authenticated, and https" in source.lower()


def test_admin_js_uses_d_none_for_dlp_toggles():
    """New DLP JS should use Bootstrap d-none, not style.display."""
    print("Testing DLP admin JavaScript visibility handling...")
    source = read_file_text(ADMIN_JS_FILE)

    assert "initializeDlpSettings" in source
    assert "dlp_control_plane_settings" in source
    assert "web_search_dlp_settings" in source
    assert "dlp_presidio_endpoint_settings" in source
    assert "presidio_endpoint" in source
    assert "classList.toggle('d-none'" in source or 'classList.toggle("d-none"' in source

    dlp_section = source[source.find("initializeDlpSettings"):]
    assert ".style.display" not in dlp_section

    for unsupported_id in UNSUPPORTED_ADMIN_CONTROL_IDS:
        assert unsupported_id not in dlp_section, f"Unsupported DLP JS hook remains: {unsupported_id}"
    assert_no_retired_structured_redaction_control(dlp_section, ADMIN_JS_FILE)


def test_admin_settings_form_contains_csrf_token():
    """Admin settings form should submit a per-session CSRF token."""
    print("Testing admin settings CSRF template field...")
    template = read_file_text(ADMIN_TEMPLATE_FILE)

    form_index = template.find('id="admin-settings-form"')
    token_index = template.find('name="admin_settings_csrf_token"', form_index)
    value_index = template.find('value="{{ admin_settings_csrf_token }}"', token_index)

    assert form_index != -1
    assert token_index > form_index
    assert value_index > token_index


def test_admin_template_exposes_regex_rule_editor_without_internal_phrase_toggle():
    """Admin UI should expose configurable regex rules and remove hardcoded internal phrases."""
    print("Testing DLP regex rule admin editor...")
    source = read_file_text(ADMIN_TEMPLATE_FILE)

    assert 'id="dlp_regex_rules_json"' in source
    assert 'name="dlp_regex_rules_json"' in source
    assert "{{ dlp_regex_rules_json }}" in source
    assert "Custom Regex Rules" in source
    assert "web_search_dlp_block_on_internal_phrases" not in source
    assert "Detect internal phrases" not in source


if __name__ == "__main__":
    tests = [
        test_dlp_defaults_exist_and_are_safe,
        test_admin_route_persists_dlp_settings,
        test_admin_template_exposes_dlp_controls,
        test_presidio_endpoint_controls_are_rendered_without_secret_value_field,
        test_admin_js_uses_d_none_for_dlp_toggles,
        test_admin_settings_form_contains_csrf_token,
        test_admin_template_exposes_regex_rule_editor_without_internal_phrase_toggle,
    ]

    try:
        for test in tests:
            test()
        print(f"All {len(tests)} DLP admin settings UI tests passed.")
        sys.exit(0)
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
