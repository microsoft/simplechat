#!/usr/bin/env python3
# test_color_schemes_admin_settings.py
"""
Functional test for the V2 color scheme admin settings and user preference wiring.
Version: 0.261.452
Implemented in: 0.261.452

This test ensures that the Appearance section declares the color scheme editor and the three
user color mode switches, that the color scheme is validated when it is saved through the
admin settings PATCH, that the settings have defaults (custom modes on by default), and that
the user settings route validates the color mode keys it accepts.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module
from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

fields_module = import_app_module("admin_settings_fields")

PALETTE = {
    "accent": "#0F7B6C",
    "onAccent": "#FFFFFF",
    "backdrop": "#EEF2FB",
    "panel": "#FFFFFF",
    "border": "#DCE3EE",
    "text1": "#0F172A",
    "text2": "#475569",
    "ok": "#059669",
    "warn": "#D97706",
    "danger": "#DC2626",
    "info": "#0E7490",
}


def _appearance_fields():
    return {
        field.get("key"): field
        for section_id, field in fields_module.iter_fields()
        if section_id == "appearance-section" and field.get("key")
    }


def test_version_is_at_least_implementation_version():
    """The app version includes this feature."""
    assert_app_version_at_least("0.261.452")


def test_appearance_section_declares_the_color_controls():
    """The editor is a component field and the switches default on."""
    fields = _appearance_fields()
    editor = fields["v2_color_scheme"]
    assert editor["type"] == "component"
    assert editor["component"] == "color-scheme-editor"
    assert editor["default"] is None
    for key in ("allow_user_custom_color_modes", "allow_user_theme_cards", "require_readable_custom_colors"):
        assert fields[key]["type"] == "switch"
        assert fields[key]["default"] is True
    for key in ("allow_user_theme_cards", "require_readable_custom_colors"):
        assert fields[key]["depends_on"] == {"key": "allow_user_custom_color_modes", "equals": True}


def test_color_scheme_is_validated_on_save():
    """A valid scheme is normalized, null resets, and unsafe values are refused."""
    normalized, errors, _ = fields_module.normalize_admin_settings_updates(
        {"v2_color_scheme": {"light": {**PALETTE, "accent": "#0f7b6c"}, "dark": PALETTE}}, {}
    )
    assert not errors
    assert normalized["v2_color_scheme"]["light"]["accent"] == "#0F7B6C"

    normalized, errors, _ = fields_module.normalize_admin_settings_updates({"v2_color_scheme": None}, {})
    assert not errors and normalized["v2_color_scheme"] is None

    _, errors, _ = fields_module.normalize_admin_settings_updates(
        {"v2_color_scheme": {"light": {**PALETTE, "accent": "red;}body{display:none"}, "dark": PALETTE}}, {}
    )
    assert "v2_color_scheme" in errors


def test_settings_have_defaults_and_reach_users_unsanitized_away():
    """Defaults exist, and no key name trips the sensitive-term filter for user bootstrap."""
    source = (APP_ROOT / "functions_settings.py").read_text(encoding="utf-8")
    for line in (
        "'v2_color_scheme': None,",
        "'allow_user_custom_color_modes': True,",
        "'allow_user_theme_cards': True,",
        "'require_readable_custom_colors': True,",
    ):
        assert line in source
    sensitive_terms = ("key", "secret", "password", "connection", "base64", "storage_account_url")
    for key in _appearance_fields():
        assert not any(term in key.lower() for term in sensitive_terms), key


def test_user_settings_route_validates_color_modes():
    """The route accepts the two keys only through the color scheme validators."""
    source = (APP_ROOT / "route_backend_users.py").read_text(encoding="utf-8")
    assert "'v2ColorMode', 'v2CustomColorMode'," in source
    assert "normalize_color_mode(settings_to_update[\"v2ColorMode\"])" in source
    assert "normalize_custom_color_mode(" in source
    assert "\"allow_user_custom_color_modes\", True" in source
    assert "\"require_readable_custom_colors\", True" in source


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
