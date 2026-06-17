# test_governance_admin_scope_toggle_visibility.py
#!/usr/bin/env python3
"""
Functional test for governance admin scope toggle visibility.
Version: 0.242.062
Implemented in: 0.242.062

This test ensures the Governance tab exposes every personal, group, and global
scope toggle even when the matching primary feature switch is disabled.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    path = os.path.join(ROOT_DIR, *parts)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


GOVERNANCE_SCOPE_CONTROLS = {
    "governance_user_endpoints": "Govern Personal Endpoints",
    "governance_user_agents": "Govern Personal Agents",
    "governance_user_actions": "Govern Personal Actions",
    "governance_group_endpoints": "Govern Group Endpoints",
    "governance_group_agents": "Govern Group Agents",
    "governance_group_actions": "Govern Group Actions",
    "governance_global_endpoints": "Govern Global Endpoints",
    "governance_global_agents_usage": "Govern Global Agents",
    "governance_global_actions_usage": "Govern Global Actions",
}


def test_governance_scope_toggles_are_visible_in_admin_markup():
    print("Testing governance scope toggle markup coverage...")

    template_content = _read("application", "single_app", "templates", "admin_settings.html")

    for feature_key, label in GOVERNANCE_SCOPE_CONTROLS.items():
        assert f'id="{feature_key}"' in template_content, f"Missing toggle id for {feature_key}"
        assert f'name="{feature_key}"' in template_content, f"Missing toggle name for {feature_key}"
        assert label in template_content, f"Missing toggle label for {feature_key}"

    print("PASS: all governance scope toggles are present in admin markup")


def test_governance_scope_toggles_are_disabled_not_hidden_by_runtime_js():
    print("Testing governance scope toggle runtime visibility behavior...")

    governance_js_content = _read("application", "single_app", "static", "js", "admin", "admin_governance.js")
    hidden_toggle_snippet = "wrapper.classList.toggle('d-none', !isGovernanceFeatureApplicable(featureKey));"

    assert hidden_toggle_snippet not in governance_js_content, (
        "Governance scope toggles should not be hidden when primary features are disabled"
    )

    for feature_key in GOVERNANCE_SCOPE_CONTROLS:
        assert f"{feature_key}:" in governance_js_content, f"Missing governance JS label/map entry for {feature_key}"

    for marker in [
        "const isApplicable = isGovernanceFeatureApplicable(featureKey);",
        "wrapper.classList.remove('d-none');",
        "featureToggle.disabled = !isApplicable;",
        "target.disabled && target.dataset.governanceLocked !== 'true'",
        "Enable the matching primary feature before governance can be enforced for this scope.",
    ]:
        assert marker in governance_js_content, f"Missing runtime visibility marker: {marker}"

    print("PASS: unavailable governance scope toggles are disabled instead of hidden")


def run_tests():
    test_governance_scope_toggles_are_visible_in_admin_markup()
    test_governance_scope_toggles_are_disabled_not_hidden_by_runtime_js()
    return True


if __name__ == "__main__":
    try:
        success = run_tests()
    except AssertionError as ex:
        print(f"FAIL: {ex}")
        sys.exit(1)
    sys.exit(0 if success else 1)
