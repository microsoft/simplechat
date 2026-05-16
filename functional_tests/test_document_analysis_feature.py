# test_document_analysis_feature.py
"""
Functional test for document analysis.
Version: 0.241.023
Implemented in: 0.241.069

This test ensures workflows and chat share the deterministic document analysis
path with structured document targets and coverage metadata.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_document_analysis_feature_wiring():
    config_content = read_text("application/single_app/config.py")
    analysis_service_content = read_text("application/single_app/functions_document_analysis.py")
    workflow_store_content = read_text("application/single_app/functions_personal_workflows.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")
    workflow_template_content = read_text("application/single_app/templates/workspace.html")
    chat_route_content = read_text("application/single_app/route_backend_chats.py")
    chat_messages_content = read_text("application/single_app/static/js/chat/chat-messages.js")
    chat_template_content = read_text("application/single_app/templates/chats.html")
    feature_index_content = read_text("docs/explanation/features/index.md")
    feature_doc_content = read_text("docs/explanation/features/v0.241.069/DOCUMENT_ANALYSIS.md")

    assert 'VERSION = "0.241.023"' in config_content, (
        "Expected config.py version 0.241.023 for document analysis wiring checks."
    )
    assert 'def normalize_document_analysis_targets(' in analysis_service_content, (
        "Expected functions_document_analysis.py to normalize structured analysis targets."
    )
    assert 'def run_document_analysis(' in analysis_service_content, (
        "Expected functions_document_analysis.py to execute the shared analysis loop."
    )
    assert 'def _resolve_document_name(' in analysis_service_content, (
        "Expected the analysis service to resolve a preferred source name for each document."
    )
    assert 'Preferred source name:' in analysis_service_content, (
        "Expected the analysis prompt to expose a preferred source name for tables and citations."
    )
    assert 'Source filename:' in analysis_service_content, (
        "Expected the analysis prompt to provide the canonical filename to the model."
    )
    assert 'Document ID:' not in analysis_service_content, (
        "Expected the analysis prompt to stop emphasizing internal document GUIDs."
    )
    assert "'file_name': document_file_name," in analysis_service_content, (
        "Expected analysis coverage results to retain each document's file name."
    )
    assert '## Coverage' in analysis_service_content, (
        "Expected the analysis service to append a deterministic coverage summary."
    )
    assert 'document_action = _normalize_document_action_config' in workflow_store_content, (
        "Expected workflow storage to normalize shared document action settings."
    )
    assert "'document_action': document_action" in workflow_store_content, (
        "Expected workflows to persist normalized document action configuration."
    )
    assert 'def _execute_document_action_workflow(' in workflow_runner_content, (
        "Expected workflow runner to expose a shared document action execution helper."
    )
    assert "if document_action.get('type') != DOCUMENT_ACTION_TYPE_NONE:" in workflow_runner_content, (
        "Expected workflow execution to branch into the shared document action executor when configured."
    )
    assert "'analysis_coverage': execution_result.get('analysis_coverage') or {}," in workflow_runner_content, (
        "Expected workflow runs to persist analysis coverage metadata."
    )
    assert 'workflow-document-action-type' in workflow_template_content, (
        "Expected workspace workflow modal to expose a document action selector."
    )
    assert 'workflow-comparison-left-document-id' in workflow_template_content, (
        "Expected workspace workflow modal to expose comparison left-side document targeting."
    )
    assert 'getDocumentActionDisplayLabel' in workflow_js_content, (
        "Expected workspace workflow UI to describe document action configuration in list and grid views."
    )
    assert 'payload.document_action.right_document_ids.length' in workflow_js_content, (
        "Expected workflow save validation to support one-left-to-many-right comparison targets."
    )
    assert "/api/chat/document-action" in chat_route_content, (
        "Expected route_backend_chats.py to expose a shared document action JSON route."
    )
    assert "/api/chat/document-action/stream" in chat_route_content, (
        "Expected route_backend_chats.py to expose a shared document action streaming route."
    )
    assert "/api/chat/analyze" in chat_route_content, (
        "Expected route_backend_chats.py to preserve the dedicated analyze JSON compatibility route."
    )
    assert "/api/chat/analyze/stream" in chat_route_content, (
        "Expected route_backend_chats.py to preserve the dedicated analyze streaming compatibility route."
    )
    assert '_execute_document_action_workflow' in chat_route_content, (
        "Expected chat document actions to reuse the shared workflow executor."
    )
    assert 'document-action-select' in chat_template_content, (
        "Expected chats.html to expose a document action selector beside document selection."
    )
    assert 'document-comparison-left-select' in chat_template_content, (
        "Expected chats.html to expose a left-side selector for comparison actions."
    )
    assert 'if (documentActionType !== DOCUMENT_ACTION_NONE) {' in chat_messages_content, (
        "Expected standard chat payloads to add document actions only when an opt-in action is selected."
    )
    assert 'requestPayload.document_action = documentAction;' in chat_messages_content, (
        "Expected chat message payloads to include the shared document action structure only for opt-in actions."
    )
    assert 'if (documentActionType === DOCUMENT_ACTION_ANALYZE) {' in chat_messages_content, (
        "Expected legacy analysis payloads to be serialized only for analysis runs."
    )
    assert "endpoint: useDocumentAction ? '/api/chat/document-action/stream' : '/api/chat/stream'" in chat_messages_content, (
        "Expected chat message sending to route document actions through the shared streaming endpoint."
    )
    assert 'DOCUMENT_ANALYSIS.md' in feature_index_content, (
        "Expected the feature index to link the document analysis documentation."
    )
    assert 'Document Analysis' in feature_doc_content, (
        "Expected feature documentation to describe the analysis capability."
    )
    assert 'Fixed/Implemented in version: **0.241.069**' in feature_doc_content, (
        "Expected feature documentation to include the implemented version."
    )

    print("✅ Document analysis feature wiring verified.")


def run_tests():
    tests = [test_document_analysis_feature_wiring]
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