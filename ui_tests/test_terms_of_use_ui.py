# test_terms_of_use_ui.py
"""
UI tests for Terms of Use admin and interstitial templates.
Version: 0.250.056
Implemented in: 0.250.055

These tests ensure the admin General tab exposes the terms of use controls
and the user-facing interstitial uses local assets and safe escaped rendering.
"""

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
TERMS_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "terms_of_use.html"


def _read(path):
    return path.read_text(encoding="utf-8")


@pytest.mark.ui
def test_admin_general_tab_exposes_terms_of_use_controls():
    """Validate admin settings include the new General-tab controls."""
    source = _read(ADMIN_TEMPLATE)

    assert 'id="terms-of-use-section"' in source
    assert 'name="enable_terms_of_use"' in source
    assert 'name="terms_of_use_message"' in source
    assert 'name="terms_of_use_frequency"' in source
    assert 'value="every_session"' in source
    assert 'value="daily"' in source
    assert 'value="once"' in source
    assert 'name="terms_of_use_decline_redirect_url"' in source
    assert "Terms of Use" in source


@pytest.mark.ui
def test_terms_of_use_template_uses_local_assets_and_escaped_message():
    """Validate the interstitial template does not depend on external scripts or raw HTML injection."""
    source = _read(TERMS_TEMPLATE)

    assert "terms_of_use.html" in source
    assert "url_for('static', filename='css/bootstrap.min.css')" in source
    assert "url_for('static', filename='css/bootstrap-icons.min.css')" in source
    assert "url_for('static', filename='images/custom_logo.png')" in source
    assert "url_for('static', filename='images/logo-lightmode.png')" in source
    assert "url_for('static', filename='images/logo.png')" not in source
    assert "data:image" not in source
    assert "https://" not in source
    assert "http://" not in source
    assert "{{ terms.message }}" in source
    assert "|safe" not in source
    assert "innerHTML" not in source
    assert "display:none" not in source
