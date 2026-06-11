# test_workflow_activity_new_tab_navigation.py
#!/usr/bin/env python3
"""
Functional test for workflow Activity new-tab navigation.
Version: 0.241.189
Implemented in: 0.241.189

This test ensures workflow Activity buttons open the activity view only in a new
browser tab and do not fall back to navigating the current workspace tab.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding='utf-8')


def test_activity_button_does_not_redirect_current_tab():
    """Workspace workflow Activity buttons should not use current-tab fallback navigation."""
    config = _read('application/single_app/config.py')
    workflow_js = _read('application/single_app/static/js/workspace/workspace_workflows.js')

    assert 'VERSION = "0.241.189"' in config
    assert 'function openWorkflowActivity(workflow)' in workflow_js
    assert 'const activityWindow = window.open("about:blank", "_blank");' in workflow_js
    assert 'activityWindow.opener = null;' in workflow_js
    assert 'activityWindow.location.href = activityState.url;' in workflow_js
    assert 'window.location.href = activityState.url;' not in workflow_js
    assert 'Allow pop-ups to open the workflow activity view.' in workflow_js


def run_tests():
    tests = [test_activity_button_does_not_redirect_current_tab]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print('PASS')
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == '__main__':
    sys.exit(0 if run_tests() else 1)
