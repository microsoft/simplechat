# test_document_actions_and_comparison_feature.py
"""
Functional test for document actions and comparison.
Version: 0.241.023
Implemented in: 0.241.104

This test ensures chat and workflows share the generic backend document action
shape, expose Source/Target comparison selectors, and support compact summary
tags plus a modal editor for workspace revisions and chat-uploaded files.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_document_actions_and_comparison_wiring():
    config_content = read_text("application/single_app/config.py")
    document_actions_content = read_text("application/single_app/functions_document_actions.py")
    comparison_service_content = read_text("application/single_app/functions_document_comparison.py")
    documents_route_content = read_text("application/single_app/route_backend_documents.py")
    group_documents_route_content = read_text("application/single_app/route_backend_group_documents.py")
    public_documents_route_content = read_text("application/single_app/route_backend_public_documents.py")
    workflow_store_content = read_text("application/single_app/functions_personal_workflows.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")
    chat_route_content = read_text("application/single_app/route_backend_chats.py")
    chat_template_content = read_text("application/single_app/templates/chats.html")
    chat_documents_content = read_text("application/single_app/static/js/chat/chat-documents.js")
    chat_messages_content = read_text("application/single_app/static/js/chat/chat-messages.js")
    workflow_template_content = read_text("application/single_app/templates/workspace.html")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")
    feature_index_content = read_text("docs/explanation/features/index.md")
    search_service_content = read_text("application/single_app/functions_search_service.py")
    latest_feature_doc_content = read_text("docs/explanation/features/v0.241.104/CHAT_COMPARISON_MODAL_SUMMARY.md")

    assert 'VERSION = "0.241.023"' in config_content, (
        "Expected config.py version 0.241.023 for document actions and comparison."
    )
    assert "DOCUMENT_ACTION_TYPE_COMPARISON = 'comparison'" in document_actions_content, (
        "Expected shared document action helpers to define the comparison action type."
    )
    assert 'def normalize_document_action_config(' in document_actions_content, (
        "Expected shared document action helpers to normalize the generic action payload."
    )
    assert 'def run_document_comparison(' in comparison_service_content, (
        "Expected a dedicated deterministic comparison service."
    )
    assert 'conversation_id=None' in comparison_service_content, (
        "Expected the comparison service to accept chat conversation context for uploaded files."
    )
    assert '_build_pairwise_comparison_prompt' in comparison_service_content, (
        "Expected the comparison service to build pairwise comparison prompts."
    )
    assert 'comparison_items' in comparison_service_content, (
        "Expected the comparison service to retain pairwise comparison results."
    )
    assert 'def _resolve_chat_upload_context(' in search_service_content, (
        "Expected search helpers to resolve uploaded chat files for comparison and analysis."
    )
    assert "/api/documents/<document_id>/versions" in documents_route_content, (
        "Expected personal document routes to expose a versions endpoint for comparison target selection."
    )
    assert "/api/group_documents/<document_id>/versions" in group_documents_route_content, (
        "Expected group document routes to expose a versions endpoint for comparison target selection."
    )
    assert "/api/public_workspace_documents/<document_id>/versions" in public_documents_route_content, (
        "Expected public workspace document routes to expose a versions endpoint for comparison target selection."
    )
    assert 'document_action = _normalize_document_action_config' in workflow_store_content, (
        "Expected workflow persistence to normalize the shared document action configuration."
    )
    assert 'def _execute_document_comparison_workflow(' in workflow_runner_content, (
        "Expected workflow execution to expose a comparison executor."
    )
    assert 'run_document_comparison(' in workflow_runner_content, (
        "Expected workflow execution to call the deterministic comparison service."
    )
    assert 'def execute_document_action_chat_request(' in chat_route_content, (
        "Expected chat requests to dispatch through the shared document action entry point."
    )
    assert 'comparison_started' in chat_route_content, (
        "Expected the chat stream formatter to describe comparison activity updates."
    )
    assert 'document-action-select' in chat_template_content, (
        "Expected the chat UI to expose a document action selector."
    )
    assert 'document-comparison-summary-bar' in chat_template_content, (
        "Expected the chat UI to expose a compact comparison summary bar."
    )
    assert 'document-comparison-modal' in chat_template_content, (
        "Expected the chat UI to expose a dedicated comparison modal editor."
    )
    assert 'fetchDocumentVersions' in chat_documents_content, (
        "Expected the chat document loader to fetch version families for selected comparison documents."
    )
    assert 'DOCUMENT_ACTION_COMPARISON' in chat_messages_content, (
        "Expected the chat client to handle the comparison action type."
    )
    assert 'buildComparisonChatUploadCatalog' in chat_messages_content, (
        "Expected the chat client to merge uploaded chat files into the comparison candidate catalog."
    )
    assert 'getComparisonCandidateCatalog' in chat_messages_content, (
        "Expected the chat client to combine version history targets with uploaded chat files."
    )
    assert 'renderComparisonInlineSummary' in chat_messages_content, (
        "Expected the chat client to render compact comparison tags outside the modal editor."
    )
    assert 'right_document_ids: comparisonRightDocumentIds' in chat_messages_content, (
        "Expected chat requests to serialize one-source-to-many-target comparison targets."
    )
    assert 'workflow-document-action-type' in workflow_template_content, (
        "Expected the workflow modal to expose a document action selector."
    )
    assert 'workflow-comparison-target-document-ids' in workflow_template_content, (
        "Expected the workflow modal to expose comparison version targets."
    )
    assert 'Source Version' in workflow_template_content, (
        "Expected the workflow modal to use Source terminology for the comparison anchor version."
    )
    assert 'DOCUMENT_ACTION_COMPARISON' in workflow_js_content, (
        "Expected the workflow UI to handle the comparison action type."
    )
    assert 'loadWorkflowComparisonVersionTargets' in workflow_js_content, (
        "Expected the workflow UI to load version families for selected comparison documents."
    )
    assert 'getSelectedWorkflowComparisonTargetIds' in workflow_js_content, (
        "Expected workflow payload building to derive comparison targets from selected versions."
    )
    assert 'Compare one source to' in workflow_js_content, (
        "Expected workflow summaries to use Source/Target wording for compare actions."
    )
    assert 'payload.document_action.document_ids.length < 2' in workflow_js_content, (
        "Expected workflow save validation to require at least two comparison version targets."
    )
    assert 'CHAT_COMPARISON_MODAL_SUMMARY.md' in feature_index_content, (
        "Expected the feature index to link the modal comparison summary documentation."
    )
    assert 'Chat Comparison Modal Summary' in latest_feature_doc_content, (
        "Expected versioned feature documentation for the modal comparison summary enhancement."
    )
    assert 'Implemented in version: **0.241.104**' in latest_feature_doc_content, (
        "Expected the feature documentation to include version 0.241.104."
    )

    print("✅ Document action and comparison wiring verified.")


def run_tests():
    tests = [test_document_actions_and_comparison_wiring]
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