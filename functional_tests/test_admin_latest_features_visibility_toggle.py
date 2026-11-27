#!/usr/bin/env python3
# test_admin_latest_features_visibility_toggle.py
"""
Functional test for the Latest Features settings visibility fix.
Version: 0.261.491
Implemented in: 0.261.491

This test ensures that the Latest Features hint and its settings have different
element IDs, and that the admin toggle shows and hides both of them.
"""

import re
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
PANES = APP_DIR / "templates" / "admin" / "_panes"


def element_ids(pane):
    return re.findall(r'\bid="(support_latest_features_[a-z]+)"', (PANES / pane).read_text(encoding="utf-8"))


def test_each_element_has_its_own_id():
    assert element_ids("support-menu.html") == ["support_latest_features_hint"]
    assert element_ids("user-facing-latest-features.html") == ["support_latest_features_settings"]


def test_the_toggle_updates_both_elements():
    script = (APP_DIR / "static" / "js" / "admin" / "admin_settings.js").read_text(encoding="utf-8")
    body = script.split("function toggleSupportLatestFeaturesVisibility() {", 1)[1].split("\n}", 1)[0]
    assert "supportLatestFeaturesHintDiv?.classList.toggle('d-none', isHidden)" in body
    assert "supportLatestFeaturesSettingsDiv?.classList.toggle('d-none', isHidden)" in body


if __name__ == "__main__":
    test_each_element_has_its_own_id()
    test_the_toggle_updates_both_elements()
