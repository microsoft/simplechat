# test_exhaustive_document_review_feature.py
"""
Functional test for exhaustive document review.
Version: 0.241.071
Implemented in: 0.241.069

This test ensures workflows and chat share the deterministic exhaustive
document review path with structured document targets and coverage metadata.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_exhaustive_document_review_feature_wiring():
    config_content = read_text("application/single_app/config.py")
    review_service_content = read_text("application/single_app/functions_exhaustive_document_review.py")
    workflow_store_content = read_text("application/single_app/functions_personal_workflows.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")
    workflow_template_content = read_text("application/single_app/templates/workspace.html")
    chat_route_content = read_text("application/single_app/route_backend_chats.py")
    chat_messages_content = read_text("application/single_app/static/js/chat/chat-messages.js")
    chat_template_content = read_text("application/single_app/templates/chats.html")
    feature_index_content = read_text("docs/explanation/features/index.md")
    feature_doc_content = read_text("docs/explanation/features/v0.241.069/EXHAUSTIVE_DOCUMENT_REVIEW.md")

    assert 'VERSION = "0.241.071"' in config_content, (
        "Expected config.py version 0.241.071 for exhaustive document review."
    )
    assert 'def normalize_exhaustive_review_targets(' in review_service_content, (
        "Expected functions_exhaustive_document_review.py to normalize structured review targets."
    )
    assert 'def run_exhaustive_document_review(' in review_service_content, (
        "Expected functions_exhaustive_document_review.py to execute the shared exhaustive review loop."
    )
    assert '## Coverage' in review_service_content, (
        "Expected the exhaustive review service to append a deterministic coverage summary."
    )
    assert 'exhaustive_review = _normalize_exhaustive_review_config' in workflow_store_content, (
        "Expected workflow storage to normalize exhaustive review settings."
    )
    assert "'exhaustive_review': exhaustive_review" in workflow_store_content, (
        "Expected workflows to persist exhaustive review configuration."
    )
    assert 'def _execute_exhaustive_review_workflow(' in workflow_runner_content, (
        "Expected workflow runner to expose a shared exhaustive review execution helper."
    )
    assert "if (workflow.get('exhaustive_review') or {}).get('enabled'):" in workflow_runner_content, (
        "Expected workflow execution to branch into exhaustive review when enabled."
    )
    assert "'review_coverage': execution_result.get('review_coverage') or {}," in workflow_runner_content, (
        "Expected workflow runs to persist exhaustive review coverage metadata."
    )
    assert 'workflow-exhaustive-review-enabled' in workflow_template_content, (
        "Expected workspace workflow modal to expose the exhaustive review toggle."
    )
    assert 'workflow-use-selected-documents-btn' in workflow_template_content, (
        "Expected workspace workflow modal to offer one-click workspace document targeting."
    )
    assert 'getExhaustiveReviewLabel' in workflow_js_content, (
        "Expected workspace workflow UI to describe exhaustive review configuration in list and grid views."
    )
    assert 'payload.exhaustive_review.document_ids.length' in workflow_js_content, (
        "Expected workflow save validation to require document ids for exhaustive review."
    )
    assert "/api/chat/exhaustive-review" in chat_route_content, (
        "Expected route_backend_chats.py to expose a dedicated exhaustive review JSON route."
    )
    assert "/api/chat/exhaustive-review/stream" in chat_route_content, (
        "Expected route_backend_chats.py to expose a dedicated exhaustive review streaming route."
    )
    assert '_execute_exhaustive_review_workflow' in chat_route_content, (
        "Expected chat exhaustive review to reuse the shared workflow executor."
    )
    assert 'exhaustive-review-btn' in chat_template_content, (
        "Expected chats.html to expose an exhaustive review entry point beside document selection."
    )
    assert "endpoint: useExhaustiveReview ? '/api/chat/exhaustive-review/stream' : '/api/chat/stream'" in chat_messages_content, (
        "Expected chat message sending to route exhaustive review through the dedicated streaming endpoint."
    )
    assert 'EXHAUSTIVE_DOCUMENT_REVIEW.md' in feature_index_content, (
        "Expected the feature index to link the exhaustive document review documentation."
    )
    assert 'Exhaustive Document Review' in feature_doc_content, (
        "Expected feature documentation to describe the exhaustive review capability."
    )
    assert 'Fixed/Implemented in version: **0.241.069**' in feature_doc_content, (
        "Expected feature documentation to include the implemented version."
    )

    print("✅ Exhaustive document review feature wiring verified.")


def run_tests():
    tests = [test_exhaustive_document_review_feature_wiring]
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