#!/usr/bin/env python3
# test_endpoints_tab_order_visibility.py
"""
Functional test for workspace/group endpoints tab order and visibility.
Version: 0.239.197
Implemented in: 0.239.197

This test ensures endpoints tabs only render when multi-endpoint management is
enabled, the personal and group admin-controlled toggles stay hidden, and the
admin multi-endpoint toggle is removed after migration while its script keeps
the endpoint editor initialized.
"""

import os


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORKSPACE_TEMPLATE = os.path.join(REPO_ROOT, "application", "single_app", "templates", "workspace.html")
GROUP_TEMPLATE = os.path.join(REPO_ROOT, "application", "single_app", "templates", "group_workspaces.html")
ADMIN_TEMPLATE = os.path.join(REPO_ROOT, "application", "single_app", "templates", "admin_settings.html")
ADMIN_ENDPOINTS_JS = os.path.join(REPO_ROOT, "application", "single_app", "static", "js", "admin", "admin_model_endpoints.js")


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_workspace_endpoints_tab_order_visibility():
    content = read_file_text(WORKSPACE_TEMPLATE)

    agents_idx = content.find('id="agents-tab-btn"')
    actions_idx = content.find('id="plugins-tab-btn"')
    endpoints_idx = content.find('id="endpoints-tab-btn"')

    assert agents_idx != -1, "Agents tab button missing in workspace template."
    assert actions_idx != -1, "Actions tab button missing in workspace template."
    assert endpoints_idx != -1, "Endpoints tab button missing in workspace template."
    assert agents_idx < actions_idx < endpoints_idx, "Workspace tab order should be Agents -> Actions -> Endpoints."

    actions_pane_idx = content.find('id="plugins-tab"')
    endpoints_pane_idx = content.find('id="endpoints-tab"')
    assert actions_pane_idx != -1, "Actions tab pane missing in workspace template."
    assert endpoints_pane_idx != -1, "Endpoints tab pane missing in workspace template."
    assert actions_pane_idx < endpoints_pane_idx, "Endpoints tab pane should appear after actions pane."

    expected_gate = "{% if settings.allow_user_custom_endpoints and settings.enable_multi_model_endpoints %}"
    assert content.count(expected_gate) >= 2, "Workspace endpoints tab button and pane should share the multi-endpoint gate."
    assert 'form-check form-switch mb-3 d-flex align-items-center d-none' in content, "Workspace admin-controlled endpoint toggle should stay hidden in the DOM."
    assert 'Multi-endpoint management is controlled by your admin' in content, "Workspace hidden admin-controlled endpoint toggle text missing."

    print("✅ Workspace endpoints tab order and visibility verified.")


def test_group_endpoints_tab_order_visibility():
    content = read_file_text(GROUP_TEMPLATE)

    agents_idx = content.find('id="group-agents-tab-btn"')
    actions_idx = content.find('id="group-plugins-tab-btn"')
    endpoints_idx = content.find('id="group-endpoints-tab-btn"')

    assert agents_idx != -1, "Group agents tab button missing in group workspace template."
    assert actions_idx != -1, "Group actions tab button missing in group workspace template."
    assert endpoints_idx != -1, "Group endpoints tab button missing in group workspace template."
    assert agents_idx < actions_idx < endpoints_idx, "Group tab order should be Agents -> Actions -> Endpoints."

    actions_pane_idx = content.find('id="group-plugins-tab"')
    endpoints_pane_idx = content.find('id="group-endpoints-tab"')
    assert actions_pane_idx != -1, "Group actions tab pane missing in group workspace template."
    assert endpoints_pane_idx != -1, "Group endpoints tab pane missing in group workspace template."
    assert actions_pane_idx < endpoints_pane_idx, "Group endpoints tab pane should appear after actions pane."

    expected_gate = "{% if settings.enable_semantic_kernel and settings.allow_group_custom_endpoints and settings.enable_multi_model_endpoints %}"
    assert content.count(expected_gate) >= 2, "Group endpoints tab button and pane should share the multi-endpoint gate."
    assert 'form-check form-switch mb-3 d-flex align-items-center d-none' in content, "Group admin-controlled endpoint toggle should stay hidden in the DOM."
    assert 'Multi-endpoint management is controlled by your admin' in content, "Group hidden admin-controlled endpoint toggle text missing."

    print("✅ Group endpoints tab order and visibility verified.")


def test_admin_multi_endpoint_toggle_is_omitted_after_enablement():
    content = read_file_text(ADMIN_TEMPLATE)

    assert '{% if not settings.enable_multi_model_endpoints %}' in content, "Admin multi-endpoint toggle should only render before migration is enabled."
    assert 'Enable multi-endpoint model management' in content, "Admin multi-endpoint toggle label missing from template."

    print("✅ Admin multi-endpoint toggle render gating verified.")


def test_admin_endpoints_script_supports_missing_toggle():
    content = read_file_text(ADMIN_ENDPOINTS_JS)

    assert 'const isMultiEndpointEnabled = enableMultiEndpointToggle ? enableMultiEndpointToggle.checked : true;' in content, "Admin endpoints script should default to enabled when the toggle is not rendered."
    assert 'if (!enableMultiEndpointToggle) {' not in content, "Admin endpoints init should not exit early when the toggle is omitted."

    print("✅ Admin endpoints script missing-toggle support verified.")


def run_tests():
    tests = [
        test_workspace_endpoints_tab_order_visibility,
        test_group_endpoints_tab_order_visibility,
        test_admin_multi_endpoint_toggle_is_omitted_after_enablement,
        test_admin_endpoints_script_supports_missing_toggle,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print("✅ Test passed")
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)
