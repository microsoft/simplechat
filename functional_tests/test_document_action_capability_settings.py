#!/usr/bin/env python3
# test_document_action_capability_settings.py
"""
Functional test for document action capability settings.
Version: 0.241.095
Implemented in: 0.241.084

This test ensures admin settings can enable or disable analysis and
comparison independently, and that chat/workflow document limits are driven by
saved settings instead of hard-coded UI and backend constants.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_document_action_capability_settings_wiring() -> None:
    print("🔍 Testing document action capability settings wiring...")

    config_content = read_text("application/single_app/config.py")
    document_actions_content = read_text("application/single_app/functions_document_actions.py")
    settings_content = read_text("application/single_app/functions_settings.py")
    admin_route_content = read_text("application/single_app/route_frontend_admin_settings.py")
    admin_template_content = read_text("application/single_app/templates/admin_settings.html")
    admin_js_content = read_text("application/single_app/static/js/admin/admin_settings.js")
    chat_route_content = read_text("application/single_app/route_backend_chats.py")
    chat_template_content = read_text("application/single_app/templates/chats.html")
    chat_messages_content = read_text("application/single_app/static/js/chat/chat-messages.js")
    workflow_store_content = read_text("application/single_app/functions_personal_workflows.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")
    workflow_template_content = read_text("application/single_app/templates/workspace.html")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")

    assert 'VERSION = "0.241.095"' in config_content, (
        "Expected config.py version 0.241.095 for document action capability settings."
    )
    assert 'DEFAULT_DOCUMENT_ACTION_CAPABILITIES' in document_actions_content, (
        "Expected shared document action helpers to define default capability settings."
    )
    assert 'def normalize_document_action_capabilities(' in document_actions_content, (
        "Expected shared document action helpers to normalize saved capability settings."
    )
    assert 'def get_document_action_max_documents_by_type(' in document_actions_content, (
        "Expected shared document action helpers to expose per-action document caps by context."
    )
    assert "'document_action_capabilities': get_default_document_action_capabilities()" in settings_content, (
        "Expected app settings defaults to persist document action capability settings."
    )
    assert 'document_action_analyze_enabled' in admin_route_content, (
        "Expected the admin settings route to parse the analysis enable toggle."
    )
    assert 'document_action_comparison_workflow_max_documents' in admin_route_content, (
        "Expected the admin settings route to parse the comparison workflow max-documents value."
    )
    assert 'Document Action Capabilities' in admin_template_content, (
        "Expected the admin settings UI to include a document action capabilities section."
    )
    assert 'document-action-capability-range' in admin_template_content, (
        "Expected the admin settings UI to render slider controls for capability limits."
    )
    assert 'setupDocumentActionCapabilityControls' in admin_js_content, (
        "Expected admin settings JavaScript to synchronize capability sliders and numeric inputs."
    )
    assert 'get_document_action_max_documents_by_type(' in chat_route_content, (
        "Expected chat document action requests to resolve max-documents limits from saved settings."
    )
    assert 'documentActionCapabilities' in chat_template_content, (
        "Expected the chat template to bootstrap document action capability settings for the browser."
    )
    assert 'getDocumentActionMaxDocuments' in chat_messages_content, (
        "Expected the chat client to enforce per-action max-documents values from saved settings."
    )
    assert 'get_enabled_document_action_types' in workflow_store_content, (
        "Expected workflow save validation to honor admin-enabled document action types."
    )
    assert 'get_document_action_max_documents(' in workflow_runner_content, (
        "Expected workflow execution to resolve analysis max-documents from saved settings."
    )
    assert 'window.documentActionCapabilities' in workflow_template_content, (
        "Expected the workspace template to bootstrap document action capability settings for workflows."
    )
    assert 'getWorkflowDocumentActionMaxDocuments' in workflow_js_content, (
        "Expected the workflow client to enforce per-action workflow max-documents values from saved settings."
    )

    print("✅ Document action capability settings wiring verified")


def run_tests() -> bool:
    tests = [test_document_action_capability_settings_wiring]
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
