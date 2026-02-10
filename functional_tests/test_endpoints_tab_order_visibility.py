# test_endpoints_tab_order_visibility.py
#!/usr/bin/env python3
"""
Functional test for workspace/group endpoints tab order and visibility.
Version: 0.236.046
Implemented in: 0.236.046

This test ensures endpoints tabs appear after actions and are gated by admin
custom endpoint settings.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_workspace_endpoints_tab_order_visibility():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    template_path = os.path.join(repo_root, "application", "single_app", "templates", "workspace.html")
    content = read_file_text(template_path)

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

    assert "settings.allow_user_custom_agent_endpoints" in content, "Workspace endpoints should be gated by custom endpoint settings."

    print("✅ Workspace endpoints tab order and visibility verified.")


def test_group_endpoints_tab_order_visibility():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    template_path = os.path.join(repo_root, "application", "single_app", "templates", "group_workspaces.html")
    content = read_file_text(template_path)

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

    assert "settings.allow_group_custom_agent_endpoints" in content, "Group endpoints should be gated by custom endpoint settings."

    print("✅ Group endpoints tab order and visibility verified.")


def run_tests():
    tests = [
        test_workspace_endpoints_tab_order_visibility,
        test_group_endpoints_tab_order_visibility
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
