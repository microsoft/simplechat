# test_document_analysis_progress_and_limits.py
"""
Functional test for analysis progress and limits.
Version: 0.241.023
Implemented in: 0.241.071

This test ensures chat streams structured analysis progress, shows
per-document progress metadata, and enforces the chat/workflow document caps.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_document_analysis_progress_and_limits_wiring():
    config_content = read_text("application/single_app/config.py")
    analysis_service_content = read_text("application/single_app/functions_document_analysis.py")
    chat_route_content = read_text("application/single_app/route_backend_chats.py")
    chat_thoughts_content = read_text("application/single_app/static/js/chat/chat-thoughts.js")
    chat_messages_content = read_text("application/single_app/static/js/chat/chat-messages.js")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")
    workflow_store_content = read_text("application/single_app/functions_personal_workflows.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")
    feature_index_content = read_text("docs/explanation/features/index.md")
    feature_doc_content = read_text("docs/explanation/features/v0.241.071/DOCUMENT_ANALYSIS_PROGRESS_AND_LIMITS.md")

    assert 'VERSION = "0.241.023"' in config_content, (
        "Expected config.py version 0.241.023 for analysis progress improvements."
    )
    assert 'CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS = 3' in analysis_service_content, (
        "Expected the analysis service to define the chat document cap."
    )
    assert 'WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS = 10' in analysis_service_content, (
        "Expected the analysis service to define the workflow document cap."
    )
    assert 'def _build_progress_snapshot(coverage):' in analysis_service_content, (
        "Expected the analysis service to build structured progress snapshots."
    )
    assert "'progress': _build_progress_snapshot(coverage)" in analysis_service_content, (
        "Expected analysis activity events to include serialized progress snapshots."
    )
    assert 'def _build_document_action_stream_activity_callback(' in chat_route_content, (
        "Expected the chat route to stream document action progress events."
    )
    assert 'publish_background_event=publish_background_event' in chat_route_content, (
        "Expected the chat stream route to pass the background publisher into analysis execution."
    )
    assert 'renderDocumentAnalysisProgress(thoughtData)' in chat_thoughts_content, (
        "Expected the chat thought renderer to build analysis progress cards."
    )
    assert "'document_analysis': 'bi-journal-richtext'" in chat_thoughts_content, (
        "Expected the chat thought renderer to map document analysis events to a dedicated icon."
    )
    assert 'chat_max_documents: 3' in chat_messages_content, (
        "Expected the chat UI to define the default chat analysis document cap."
    )
    assert 'Use workflows for up to ${workflowMaxDocuments} documents.' in chat_messages_content, (
        "Expected the chat UI to guide larger analysis jobs to workflows."
    )
    assert 'workflow_max_documents: 10' in workflow_js_content, (
        "Expected the workflow UI to define its default analysis document cap."
    )
    assert 'getWorkflowDocumentActionMaxDocuments(documentActionType)' in workflow_js_content, (
        "Expected the workflow UI to reject oversized document action selections using configured limits."
    )
    assert 'max_documents_by_type=get_document_action_max_documents_by_type(' in workflow_store_content, (
        "Expected workflow persistence to normalize analysis document caps from configured limits."
    )
    assert 'workflow_analysis_max_documents = get_document_action_max_documents(' in workflow_runner_content, (
        "Expected workflow execution to enforce the configured workflow analysis cap for saved runs."
    )
    assert 'DOCUMENT_ANALYSIS_PROGRESS_AND_LIMITS.md' in feature_index_content, (
        "Expected the feature index to link the analysis progress and limits documentation."
    )
    assert 'Analyze Progress And Limits' in feature_doc_content, (
        "Expected feature documentation for analysis progress and limits."
    )
    assert 'Fixed/Implemented in version: **0.241.071**' in feature_doc_content, (
        "Expected feature documentation to include version 0.241.071."
    )

    print("✅ Document analysis progress and limit wiring verified.")


def run_tests():
    tests = [test_document_analysis_progress_and_limits_wiring]
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