# test_workflow_agent_selection_fix.py
"""
Functional test for workflow agent selection fix.
Version: 0.241.036
Implemented in: 0.241.029

This test ensures the workflow modal accepts the existing user-agents API
array response, retries agent loading after failures, and refreshes agent
choices each time the modal opens.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_workflow_agent_selection_fix_contracts():
    config_content = read_text("application/single_app/config.py")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")
    workflow_ui_test_content = read_text("ui_tests/test_workspace_workflows_tab.py")
    fix_doc_content = read_text("docs/explanation/fixes/WORKFLOW_AGENT_SELECTION_FIX.md")

    assert 'VERSION = "0.241.036"' in config_content, (
        "Expected config.py version 0.241.036 for the workflow agent selection fix."
    )
    assert "Array.isArray(data)" in workflow_js_content, (
        "Expected workflow agent loading to accept a direct array response from /api/user/agents."
    )
    assert "Array.isArray(data?.agents)" in workflow_js_content, (
        "Expected workflow agent loading to remain compatible with wrapped agent payloads."
    )
    assert "await loadAgentOptions(true);" in workflow_js_content, (
        "Expected the workflow modal to refresh agent options whenever it opens."
    )
    assert "agentsLoaded = false;" in workflow_js_content, (
        "Expected failed agent loads to retry instead of caching an empty list forever."
    )
    assert "body=json.dumps(" in workflow_ui_test_content and '"name": "researcher_agent"' in workflow_ui_test_content, (
        "Expected the workflow UI regression test to stub the user agents API."
    )
    assert '"agents": [' not in workflow_ui_test_content, (
        "Expected the workflow UI regression test to use the real bare-array user agents response shape."
    )
    assert "Workflow Agent Selection Fix" in fix_doc_content, (
        "Expected the fix documentation to describe the workflow agent selection issue."
    )

    print("✅ Workflow agent selection fix contracts verified.")


def run_tests():
    tests = [test_workflow_agent_selection_fix_contracts]
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