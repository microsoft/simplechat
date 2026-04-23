# test_exhaustive_review_progress_and_limits.py
"""
Functional test for exhaustive review progress and limits.
Version: 0.241.071
Implemented in: 0.241.071

This test ensures chat streams structured exhaustive review progress, shows
per-document progress metadata, and enforces the chat/workflow document caps.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_exhaustive_review_progress_and_limits_wiring():
    config_content = read_text("application/single_app/config.py")
    review_service_content = read_text("application/single_app/functions_exhaustive_document_review.py")
    chat_route_content = read_text("application/single_app/route_backend_chats.py")
    chat_thoughts_content = read_text("application/single_app/static/js/chat/chat-thoughts.js")
    chat_messages_content = read_text("application/single_app/static/js/chat/chat-messages.js")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")
    workflow_store_content = read_text("application/single_app/functions_personal_workflows.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")
    feature_index_content = read_text("docs/explanation/features/index.md")
    feature_doc_content = read_text("docs/explanation/features/v0.241.071/EXHAUSTIVE_REVIEW_PROGRESS_AND_LIMITS.md")

    assert 'VERSION = "0.241.071"' in config_content, (
        "Expected config.py version 0.241.071 for exhaustive review progress improvements."
    )
    assert 'CHAT_EXHAUSTIVE_REVIEW_MAX_DOCUMENTS = 3' in review_service_content, (
        "Expected the exhaustive review service to define the chat document cap."
    )
    assert 'WORKFLOW_EXHAUSTIVE_REVIEW_MAX_DOCUMENTS = 10' in review_service_content, (
        "Expected the exhaustive review service to define the workflow document cap."
    )
    assert 'def _build_progress_snapshot(coverage):' in review_service_content, (
        "Expected the exhaustive review service to build structured progress snapshots."
    )
    assert "'progress': _build_progress_snapshot(coverage)" in review_service_content, (
        "Expected exhaustive review activity events to include serialized progress snapshots."
    )
    assert 'def _build_exhaustive_review_stream_activity_callback(' in chat_route_content, (
        "Expected the chat route to stream exhaustive review progress events."
    )
    assert 'publish_background_event=publish_background_event' in chat_route_content, (
        "Expected the chat stream route to pass the background publisher into exhaustive review execution."
    )
    assert 'renderExhaustiveReviewProgress(thoughtData)' in chat_thoughts_content, (
        "Expected the chat thought renderer to build exhaustive review progress cards."
    )
    assert "'document_review': 'bi-journal-richtext'" in chat_thoughts_content, (
        "Expected the chat thought renderer to map document review events to a dedicated icon."
    )
    assert 'CHAT_EXHAUSTIVE_REVIEW_MAX_DOCUMENTS = 3' in chat_messages_content, (
        "Expected the chat UI to enforce the chat exhaustive review document cap."
    )
    assert 'Use workflows for up to ${WORKFLOW_EXHAUSTIVE_REVIEW_MAX_DOCUMENTS} documents.' in chat_messages_content, (
        "Expected the chat UI to guide larger review jobs to workflows."
    )
    assert 'WORKFLOW_EXHAUSTIVE_REVIEW_MAX_DOCUMENTS = 10' in workflow_js_content, (
        "Expected the workflow UI to define its exhaustive review document cap."
    )
    assert 'Workflow exhaustive review supports up to ${WORKFLOW_EXHAUSTIVE_REVIEW_MAX_DOCUMENTS} documents per run.' in workflow_js_content, (
        "Expected the workflow UI to reject oversized exhaustive review selections."
    )
    assert 'max_documents=WORKFLOW_EXHAUSTIVE_REVIEW_MAX_DOCUMENTS' in workflow_store_content, (
        "Expected workflow persistence to normalize exhaustive review document caps."
    )
    assert 'max_documents=WORKFLOW_EXHAUSTIVE_REVIEW_MAX_DOCUMENTS' in workflow_runner_content, (
        "Expected workflow execution to enforce the workflow exhaustive review cap for saved runs."
    )
    assert 'EXHAUSTIVE_REVIEW_PROGRESS_AND_LIMITS.md' in feature_index_content, (
        "Expected the feature index to link the exhaustive review progress and limits documentation."
    )
    assert 'Exhaustive Review Progress And Limits' in feature_doc_content, (
        "Expected feature documentation for exhaustive review progress and limits."
    )
    assert 'Fixed/Implemented in version: **0.241.071**' in feature_doc_content, (
        "Expected feature documentation to include version 0.241.071."
    )

    print("✅ Exhaustive review progress and limit wiring verified.")


def run_tests():
    tests = [test_exhaustive_review_progress_and_limits_wiring]
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