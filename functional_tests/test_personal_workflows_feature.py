# test_personal_workflows_feature.py
"""
Functional test for personal workflows feature.
Version: 0.241.036
Implemented in: 0.241.029

This test ensures personal workflows are wired through backend routes,
scheduler integration, workspace UI, and admin workspace settings.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_personal_workflows_feature_wiring():
    config_content = read_text("application/single_app/config.py")
    settings_content = read_text("application/single_app/functions_settings.py")
    app_content = read_text("application/single_app/app.py")
    background_tasks_content = read_text("application/single_app/background_tasks.py")
    workflow_store_content = read_text("application/single_app/functions_personal_workflows.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")
    workflow_routes_content = read_text("application/single_app/route_backend_workflows.py")
    workspace_template_content = read_text("application/single_app/templates/workspace.html")
    sidebar_template_content = read_text("application/single_app/templates/_sidebar_nav.html")
    sidebar_short_template_content = read_text("application/single_app/templates/_sidebar_short_nav.html")
    admin_settings_content = read_text("application/single_app/templates/admin_settings.html")
    sidebar_js_content = read_text("application/single_app/static/js/chat/chat-sidebar-conversations.js")
    sidebar_css_content = read_text("application/single_app/static/css/sidebar.css")
    workspace_init_content = read_text("application/single_app/static/js/workspace/workspace-init.js")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")
    feature_doc_content = read_text("docs/explanation/features/PERSONAL_WORKFLOWS.md")

    assert 'VERSION = "0.241.036"' in config_content, (
        "Expected config.py version 0.241.036 for the personal workflows feature."
    )
    assert 'cosmos_personal_workflows_container_name = "personal_workflows"' in config_content, (
        "Expected config.py to register the personal workflows Cosmos container with the exported plural name."
    )
    assert (
        'cosmos_personal_workflows_container = cosmos_database.create_container_if_not_exists(\n'
        '    id=cosmos_personal_workflows_container_name,\n'
        '    partition_key=PartitionKey(path="/user_id")'
    ) in config_content, (
        "Expected workflow definitions to use a user_id partition key that matches workflow storage helpers."
    )
    assert (
        'cosmos_personal_workflow_runs_container = cosmos_database.create_container_if_not_exists(\n'
        '    id=cosmos_personal_workflow_runs_container_name,\n'
        '    partition_key=PartitionKey(path="/user_id")'
    ) in config_content, (
        "Expected workflow runs to use a user_id partition key that matches workflow run queries and deletes."
    )
    assert "'allow_user_workflows': True" in settings_content, (
        "Expected functions_settings.py to default allow_user_workflows to True."
    )
    assert "register_route_backend_workflows(app)" in app_content, (
        "Expected app.py to register the backend workflow routes."
    )
    assert "run_workflow_scheduler_loop" in background_tasks_content, (
        "Expected background_tasks.py to define the workflow scheduler loop."
    )
    assert "check_due_workflows_once" in background_tasks_content, (
        "Expected background_tasks.py to process due workflows."
    )
    assert "compute_next_run_at" in workflow_store_content, (
        "Expected functions_personal_workflows.py to compute workflow schedule timestamps."
    )
    assert "run_personal_workflow" in workflow_runner_content, (
        "Expected functions_workflow_runner.py to execute workflow runs."
    )
    assert "/api/user/workflows/<workflow_id>/run" in workflow_routes_content, (
        "Expected route_backend_workflows.py to expose the manual workflow run route."
    )
    assert 'id="workflows-tab-btn"' in workspace_template_content, (
        "Expected workspace.html to render the workflows tab button."
    )
    assert 'id="workflowModal"' in workspace_template_content, (
        "Expected workspace.html to render the workflow create/edit modal."
    )
    assert 'id="workflowHistoryModal"' in workspace_template_content, (
        "Expected workspace.html to render the workflow history modal."
    )
    assert 'id="workflow-history-open-conversation-link"' in workspace_template_content, (
        "Expected workspace.html to provide a direct link to the workflow conversation from run history."
    )
    assert 'data-tab="workflows-tab"' in sidebar_template_content, (
        "Expected the left-hand workspace navigation to include Your Workflows."
    )
    assert 'id="sidebar-workflow-section"' in sidebar_template_content, (
        "Expected the full chat sidebar to render a dedicated workflow conversations section."
    )
    assert 'id="sidebar-workflow-section"' in sidebar_short_template_content, (
        "Expected the short chat sidebar to render a dedicated workflow conversations section."
    )
    assert 'id="sidebar-workflow-show-more-btn"' in sidebar_template_content, (
        "Expected the full chat sidebar workflow section to include a show-more control."
    )
    assert 'id="sidebar-workflow-show-more-btn"' in sidebar_short_template_content, (
        "Expected the short chat sidebar workflow section to include a show-more control."
    )
    assert 'id="sidebar-workflows-toggle"' in sidebar_template_content, (
        "Expected the full chat sidebar workflow section to expose a collapsible Workflows header."
    )
    assert 'class="sidebar-section-toggle mt-2 mb-1 ps-3 pe-2 text-muted small d-flex align-items-center justify-content-between"' in sidebar_template_content, (
        "Expected the Conversations header to use the shared sidebar section styling."
    )
    assert 'id="sidebar-workflow-list-container"' in sidebar_template_content, (
        "Expected the full chat sidebar workflow section to render its own scrollable list container."
    )
    assert 'id="sidebar-workflows-toggle"' in sidebar_short_template_content, (
        "Expected the short chat sidebar workflow section to expose a collapsible Workflows header."
    )
    assert 'class="sidebar-section-toggle mt-2 mb-1 ps-3 pe-2 text-muted small d-flex align-items-center"' in sidebar_short_template_content, (
        "Expected the short chat sidebar workflow header to use the shared sidebar section styling."
    )
    assert 'id="sidebar-workflow-list-container"' in sidebar_short_template_content, (
        "Expected the short chat sidebar workflow section to render its own scrollable list container."
    )
    assert 'id="allow_user_workflows"' in admin_settings_content, (
        "Expected admin settings to expose the Allow User Workflows toggle."
    )
    assert "const DEFAULT_WORKFLOW_SECTION_LIMIT = 5;" in sidebar_js_content, (
        "Expected the chat sidebar workflow section to default to five visible workflow conversations."
    )
    assert "return String(conversation?.chat_type || '').trim().toLowerCase() === 'workflow';" in sidebar_js_content, (
        "Expected the chat sidebar to detect workflow conversations from chat_type instead of using a separate API."
    )
    assert "const regularConversations = visibleConversations.filter(conversation => !isWorkflowConversation(conversation));" in sidebar_js_content, (
        "Expected the Conversations section to exclude workflow chats."
    )
    assert "const workflowConversations = visibleConversations.filter(conversation => isWorkflowConversation(conversation));" in sidebar_js_content, (
        "Expected the Workflows section to render only workflow chats."
    )
    assert "const sidebarWorkflowListContainer = document.getElementById(\"sidebar-workflow-list-container\");" in sidebar_js_content, (
        "Expected the chat sidebar workflow section to keep its own list container."
    )
    assert "function applyWorkflowSectionCollapsedState(isCollapsed = false) {" in sidebar_js_content, (
        "Expected the chat sidebar workflow section to support open and close behavior."
    )
    assert "function buildWorkflowConversationUrl(conversationId) {" in workflow_js_content, (
        "Expected workflow history rendering to build direct links to workflow conversations."
    )
    assert 'Open workflow conversation' in workflow_js_content, (
        "Expected workflow history rows to render a direct workflow conversation link for each run."
    )
    assert ".sidebar-section-toggle {" in sidebar_css_content, (
        "Expected sidebar.css to define shared section-header styling for Conversations and Workflows."
    )
    assert ".sidebar-workflow-list-container {" in sidebar_css_content, (
        "Expected sidebar.css to define a dedicated workflow list container."
    )
    assert "overflow-y: auto;" in sidebar_css_content, (
        "Expected the workflow sidebar list to keep its own vertical scrollbar styling."
    )
    assert "window.fetchUserWorkflows = fetchUserWorkflows" in workflow_js_content, (
        "Expected workspace_workflows.js to expose a loader for workspace-init.js."
    )
    assert "Loading workflows tab data" in workspace_init_content, (
        "Expected workspace-init.js to load workflows when the workflows tab becomes active."
    )
    assert "Personal Workflows" in feature_doc_content, (
        "Expected PERSONAL_WORKFLOWS.md to document the feature."
    )

    print("✅ Personal workflows feature wiring verified.")


def run_tests():
    tests = [test_personal_workflows_feature_wiring]
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