# test_admin_content_safety_threshold_ui.py
"""
UI test for Admin Settings Content Safety prompt threshold controls.

Version: 0.261.059
Implemented in: 0.261.058

This test ensures the Content Safety admin pane exposes category severity
threshold sliders, describes their blocking behavior, keeps the labels synchronized
through local SimpleChat JavaScript, and verifies Admin Settings range sliders
share the dark-mode contrast fix.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_PANES_DIR = REPO_ROOT / "application" / "single_app" / "templates" / "admin" / "_panes"
CONTENT_SAFETY_TEMPLATE = ADMIN_PANES_DIR / "content-safety.html"
ADMIN_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_settings.js"
STYLES_CSS = REPO_ROOT / "application" / "single_app" / "static" / "css" / "styles.css"


def test_content_safety_category_threshold_sliders_are_rendered():
    """Validate category threshold sliders are present with trimmed severity bounds."""
    template = CONTENT_SAFETY_TEMPLATE.read_text(encoding="utf-8")

    assert 'id="content-safety-category-thresholds"' in template
    assert '<th scope="col">Category</th>' in template
    assert '<th scope="col">Threshold</th>' in template
    for category_name in ('Violence', 'Hate', 'Sexual', 'Self-harm'):
        assert category_name in template
    for field_name in (
        'content_safety_threshold_violence',
        'content_safety_threshold_hate',
        'content_safety_threshold_sexual',
        'content_safety_threshold_self_harm',
    ):
        assert f'id="{field_name}"' in template
        assert f'name="{field_name}"' in template
    assert 'type="range"' in template
    assert 'class="form-range content-safety-category-threshold-range"' in template
    assert 'min="2"' in template
    assert 'max="6"' in template
    assert 'step="2"' in template
    assert 'Block Low, Medium and High' in template
    assert 'Allow Low / Block Medium and High' in template
    assert 'Allow Low and Medium / Block High' in template
    assert 'Higher threshold levels don’t override the model deployment guardrails.' in template


def test_content_safety_threshold_labels_use_text_content():
    """Validate threshold labels are updated without HTML injection sinks."""
    admin_js = ADMIN_JS.read_text(encoding="utf-8")

    assert "document.querySelectorAll('.content-safety-category-threshold-range').forEach" in admin_js
    assert 'thresholdLabel.textContent = thresholdCopy.label;' in admin_js
    assert 'thresholdHelp.textContent = thresholdCopy.help;' in admin_js
    assert "thresholdSlider.addEventListener('input', updateContentSafetyCategoryThreshold);" in admin_js
    assert "thresholdSlider.addEventListener('change', markFormAsModified);" in admin_js


def test_admin_settings_range_sliders_use_switch_off_gray_track():
    """Validate every Admin Settings range slider receives the dark-mode contrast fix."""
    styles_css = STYLES_CSS.read_text(encoding="utf-8")
    pane_markup = "\n".join(
        path.read_text(encoding="utf-8") for path in ADMIN_PANES_DIR.glob("*.html")
    )

    assert 'id="landing_page_logo_scale_percent"' in pane_markup
    assert 'type="range"' in pane_markup
    assert '[data-bs-theme="dark"] .form-range::-webkit-slider-runnable-track' in styles_css
    assert '[data-bs-theme="dark"] .form-range::-moz-range-track' in styles_css
    assert 'background-color: #6c757d;' in styles_css
