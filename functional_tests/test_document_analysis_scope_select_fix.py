# test_document_analysis_scope_select_fix.py
"""
Functional test for document analysis scope select fix.
Version: 0.241.023
Implemented in: 0.241.070

This test ensures ordered chunk retrieval only requests the scope field
available on the active Azure Search index, so analysis works
for both chat and workflow execution.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_document_analysis_scope_select_fix_wiring():
    config_content = read_text("application/single_app/config.py")
    documents_content = read_text("application/single_app/functions_documents.py")
    chat_route_content = read_text("application/single_app/route_backend_chats.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")
    fix_doc_content = read_text("docs/explanation/fixes/DOCUMENT_ANALYSIS_SCOPE_SELECT_FIX.md")

    assert 'VERSION = "0.241.023"' in config_content, (
        "Expected config.py version 0.241.023 for the analysis scope-select fix."
    )
    assert "scope_field = 'public_workspace_id' if public_workspace_id is not None else ('group_id' if group_id is not None else 'user_id')" in documents_content, (
        "Expected ordered chunk retrieval to choose the scope-specific Azure Search field."
    )
    assert "'select': ','.join(select_fields)" in documents_content, (
        "Expected ordered chunk retrieval to keep using an explicit select list."
    )
    assert "'user_id': result.get('user_id') if scope_field == 'user_id' else document_item.get('user_id')" in documents_content, (
        "Expected missing scope ids to fall back to the resolved document record."
    )
    assert 'def execute_document_action_chat_request(data=None, publish_background_event=None, forced_action_type=None):' in chat_route_content, (
        "Expected chat document actions to execute through the shared backend helper."
    )
    assert 'def _execute_document_action_workflow(' in workflow_runner_content, (
        "Expected workflows to continue using the same shared document action executor as chat."
    )
    assert 'Analyze Scope Select Fix' in fix_doc_content, (
        "Expected fix documentation for the Azure Search scope-select regression."
    )
    assert 'Fixed/Implemented in version: **0.241.070**' in fix_doc_content, (
        "Expected the fix documentation to include version 0.241.070."
    )

    print("✅ Document analysis scope-select fix wiring verified.")


def run_tests():
    tests = [test_document_analysis_scope_select_fix_wiring]
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