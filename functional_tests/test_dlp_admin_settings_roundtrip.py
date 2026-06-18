# test_dlp_admin_settings_roundtrip.py
#!/usr/bin/env python3
"""
Functional test for DLP admin settings roundtrip.
Version: 0.242.073
Implemented in: 0.242.073

This test ensures DLP admin settings are normalized, persisted, and rendered
through the admin settings POST contract without requiring live Azure services.
"""

import os
import sys
from pathlib import Path


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
ADMIN_ROUTE_FILE = os.path.join(APP_DIR, "route_frontend_admin_settings.py")
ADMIN_TEMPLATE_FILE = os.path.join(APP_DIR, "templates", "admin_settings.html")
ADMIN_TEMPLATE = Path(ADMIN_TEMPLATE_FILE)


NORMALIZED_ASSIGNMENTS = [
    "dlp_max_scan_chars = max(1000, dlp_max_scan_chars)",
    "if web_search_dlp_mode not in ('monitor', 'redact', 'block'):",
    "web_search_dlp_mode = 'monitor'",
    "if dlp_review_destination not in ('none',):",
    "dlp_review_destination = 'none'",
]


PERSISTED_DLP_FIELDS = {
    "enable_dlp_control_plane": "form_data.get('enable_dlp_control_plane') == 'on'",
    "dlp_default_engine": "'regex'",
    "dlp_regex_rules": "normalized_dlp_regex_rules",
    "dlp_max_scan_chars": "dlp_max_scan_chars",
    "dlp_fail_closed_on_scanner_error": "form_data.get('dlp_fail_closed_on_scanner_error') == 'on'",
    "dlp_audit_level": "'counts_only'",
    "dlp_enable_structured_telemetry": "form_data.get('dlp_enable_structured_telemetry') == 'on'",
    "dlp_telemetry_sample_allow_events": "form_data.get('dlp_telemetry_sample_allow_events') == 'on'",
    "dlp_review_destination": "dlp_review_destination",
    "enable_web_search_dlp": "form_data.get('enable_web_search_dlp') == 'on'",
    "web_search_dlp_mode": "web_search_dlp_mode",
    "enable_upload_dlp": "form_data.get('enable_upload_dlp') == 'on'",
    "upload_dlp_mode": "upload_dlp_mode",
    "upload_dlp_fail_upload_on_match": "form_data.get('upload_dlp_fail_upload_on_match') == 'on'",
}


UNSUPPORTED_DLP_FORM_FIELDS = [
    "dlp_presidio_use_service",
    "dlp_presidio_endpoint",
    "dlp_presidio_score_threshold",
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


def test_dlp_admin_post_normalizes_untrusted_form_values():
    """Admin POST should clamp numeric inputs and fail closed on enum-like fields."""
    print("Testing DLP admin POST normalization...")
    route_source = read_file_text(ADMIN_ROUTE_FILE)

    for snippet in NORMALIZED_ASSIGNMENTS:
        assert snippet in route_source, f"Missing DLP normalization contract: {snippet}"

    assert "safe_int_with_source(" in route_source

    for field_name in UNSUPPORTED_DLP_FORM_FIELDS:
        assert f"form_data.get('{field_name}'" not in route_source, (
            f"Admin route still accepts unsupported DLP form field: {field_name}"
        )
    assert_no_retired_structured_redaction_control(route_source, ADMIN_ROUTE_FILE)


def test_dlp_admin_post_persists_normalized_dlp_payload():
    """Admin POST should persist normalized values, not raw form strings."""
    print("Testing DLP admin POST persistence payload...")
    route_source = read_file_text(ADMIN_ROUTE_FILE)

    for field_name, expected_value in PERSISTED_DLP_FIELDS.items():
        expected_mapping = f"'{field_name}': {expected_value}"
        assert expected_mapping in route_source, f"Missing DLP persistence mapping: {expected_mapping}"


def test_dlp_admin_template_roundtrips_persisted_values():
    """Admin template should render the same fields that POST persists."""
    print("Testing DLP admin template roundtrip controls...")
    template_source = read_file_text(ADMIN_TEMPLATE_FILE)

    for field_name in PERSISTED_DLP_FIELDS:
        if field_name == "dlp_regex_rules":
            assert 'id="dlp_regex_rules_json"' in template_source
            assert 'name="dlp_regex_rules_json"' in template_source
        else:
            assert (
                f'id="{field_name}"' in template_source or f'name="{field_name}"' in template_source
            ), f"Missing DLP admin control: {field_name}"

    assert 'id="dlp_control_plane_settings"' in template_source
    assert 'id="web_search_dlp_mode_settings"' in template_source

    for field_name in UNSUPPORTED_DLP_FORM_FIELDS:
        assert field_name not in template_source, f"Unsupported DLP control still rendered: {field_name}"
    assert_no_retired_structured_redaction_control(template_source, ADMIN_TEMPLATE_FILE)


def test_dlp_review_destination_stays_unreachable_until_review_flow_exists():
    """Review records should stay disabled until a reachable review destination is implemented."""
    print("Testing DLP review destination fail-closed behavior...")
    route_source = read_file_text(ADMIN_ROUTE_FILE)
    template_source = read_file_text(ADMIN_TEMPLATE_FILE)

    assert "if dlp_review_destination not in ('none',):" in route_source
    assert "dlp_review_destination = 'none'" in route_source
    assert 'value="safety_violations"' not in template_source


def test_admin_dlp_controls_only_expose_supported_regex_engine():
    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    route_source = read_file_text(ADMIN_ROUTE_FILE)

    assert '<option value="regex" selected>Regex structured identifier scan</option>' in template
    assert "Regex scanning is the only implemented engine in this release." in template
    assert 'name="dlp_regex_rules_json"' in template
    assert "web_search_dlp_block_on_internal_phrases" not in template
    assert "Detect internal phrases" not in template
    assert 'value="presidio_service"' not in template
    assert 'value="presidio_embedded"' not in template
    assert_no_retired_structured_redaction_control(template, str(ADMIN_TEMPLATE))

    for field_name in UNSUPPORTED_DLP_FORM_FIELDS:
        assert f"'{field_name}':" not in route_source, f"Unsupported DLP field still persisted: {field_name}"
    assert_no_retired_structured_redaction_control(route_source, ADMIN_ROUTE_FILE)


def test_admin_settings_post_validates_csrf_before_dlp_persistence():
    """Admin settings POST should validate CSRF before persisting security-sensitive DLP fields."""
    print("Testing admin settings CSRF validation ordering...")
    source = read_file_text(ADMIN_ROUTE_FILE)

    post_index = source.find("if request.method == 'POST':")
    form_index = source.find("form_data = request.form", post_index)
    csrf_index = source.find("if not _validate_admin_settings_csrf_token(form_data):", form_index)
    persist_index = source.find("'enable_dlp_control_plane': form_data.get('enable_dlp_control_plane') == 'on'", form_index)

    assert post_index != -1
    assert form_index > post_index
    assert csrf_index > form_index
    assert persist_index > csrf_index
    assert "secrets.compare_digest" in source
    assert "ADMIN_SETTINGS_CSRF_SESSION_KEY" in source


def test_admin_settings_persists_valid_dlp_regex_rules():
    """Admin settings should persist normalized configurable regex rules."""
    print("Testing admin regex rule persistence...")
    source = read_file_text(ADMIN_ROUTE_FILE)

    assert "dlp_regex_rules_json" in source
    assert "validate_dlp_regex_rules" in source
    assert "'dlp_regex_rules': normalized_dlp_regex_rules" in source


def test_admin_settings_rejects_invalid_dlp_regex_rules_before_update():
    """Invalid DLP regex rules should be rejected before update_settings."""
    print("Testing invalid admin regex rule rejection ordering...")
    source = read_file_text(ADMIN_ROUTE_FILE)

    parse_index = source.find("raw_dlp_regex_rules = form_data.get('dlp_regex_rules_json'")
    validate_index = source.find("validate_dlp_regex_rules", parse_index)
    update_index = source.find("if update_settings(new_settings):", validate_index)

    assert parse_index != -1
    assert validate_index > parse_index
    assert update_index > validate_index
    assert "return redirect(url_for('admin_settings'))" in source[validate_index:update_index]


if __name__ == "__main__":
    tests = [
        test_dlp_admin_post_normalizes_untrusted_form_values,
        test_dlp_admin_post_persists_normalized_dlp_payload,
        test_dlp_admin_template_roundtrips_persisted_values,
        test_dlp_review_destination_stays_unreachable_until_review_flow_exists,
        test_admin_dlp_controls_only_expose_supported_regex_engine,
        test_admin_settings_post_validates_csrf_before_dlp_persistence,
        test_admin_settings_persists_valid_dlp_regex_rules,
        test_admin_settings_rejects_invalid_dlp_regex_rules_before_update,
    ]

    try:
        for test in tests:
            test()
        print(f"All {len(tests)} DLP admin settings roundtrip tests passed.")
        sys.exit(0)
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
