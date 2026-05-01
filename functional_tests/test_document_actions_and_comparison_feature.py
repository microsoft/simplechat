# test_document_actions_and_comparison_feature.py
"""
Functional test for document actions and comparison.
Version: 0.241.072
Implemented in: 0.241.072

This test ensures chat and workflows share the generic backend document action
shape and that comparison is implemented as one-left-to-many-right.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_document_actions_and_comparison_wiring():
    config_content = read_text("application/single_app/config.py")
    document_actions_content = read_text("application/single_app/functions_document_actions.py")
    comparison_service_content = read_text("application/single_app/functions_document_comparison.py")
    workflow_store_content = read_text("application/single_app/functions_personal_workflows.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")
    chat_route_content = read_text("application/single_app/route_backend_chats.py")
    chat_template_content = read_text("application/single_app/templates/chats.html")
    chat_messages_content = read_text("application/single_app/static/js/chat/chat-messages.js")
    workflow_template_content = read_text("application/single_app/templates/workspace.html")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")
    feature_index_content = read_text("docs/explanation/features/index.md")
    feature_doc_content = read_text("docs/explanation/features/v0.241.072/DOCUMENT_ACTIONS_AND_COMPARISON.md")

    assert 'VERSION = "0.241.072"' in config_content, (
        "Expected config.py version 0.241.072 for document actions and comparison."
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
    assert '_build_pairwise_comparison_prompt' in comparison_service_content, (
        "Expected the comparison service to build pairwise comparison prompts."
    )
    assert 'comparison_items' in comparison_service_content, (
        "Expected the comparison service to retain pairwise comparison results."
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
    assert 'document-comparison-left-select' in chat_template_content, (
        "Expected the chat UI to expose a left document selector for comparison."
    )
    assert 'DOCUMENT_ACTION_COMPARISON' in chat_messages_content, (
        "Expected the chat client to handle the comparison action type."
    )
    assert 'right_document_ids: comparisonRightDocumentIds' in chat_messages_content, (
        "Expected chat requests to serialize one-left-to-many-right comparison targets."
    )
    assert 'workflow-document-action-type' in workflow_template_content, (
        "Expected the workflow modal to expose a document action selector."
    )
    assert 'workflow-comparison-right-document-ids' in workflow_template_content, (
        "Expected the workflow modal to expose right-side comparison document targets."
    )
    assert 'DOCUMENT_ACTION_COMPARISON' in workflow_js_content, (
        "Expected the workflow UI to handle the comparison action type."
    )
    assert 'payload.document_action.left_document_id' in workflow_js_content, (
        "Expected workflow save validation to require a left-side document for comparison."
    )
    assert 'DOCUMENT_ACTIONS_AND_COMPARISON.md' in feature_index_content, (
        "Expected the feature index to link the document actions and comparison documentation."
    )
    assert 'Document Actions And Comparison' in feature_doc_content, (
        "Expected versioned feature documentation for document actions and comparison."
    )
    assert 'Fixed/Implemented in version: **0.241.072**' in feature_doc_content, (
        "Expected the feature documentation to include version 0.241.072."
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