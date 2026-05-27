# test_workflow_access_controls.py
"""
Functional test for workflow access controls.
Version: 0.241.106
Implemented in: 0.241.106

This test ensures personal workflows are an optional feature, can be gated
with the WorkflowUser app role, and are enforced across UI and API surfaces.
"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_workflow_access_control_wiring():
    config_content = read_text("application/single_app/config.py")
    settings_content = read_text("application/single_app/functions_settings.py")
    workflow_routes_content = read_text("application/single_app/route_backend_workflows.py")
    frontend_chats_content = read_text("application/single_app/route_frontend_chats.py")
    frontend_workspace_content = read_text("application/single_app/route_frontend_workspace.py")
    admin_route_content = read_text("application/single_app/route_frontend_admin_settings.py")
    simplechat_operations_content = read_text("application/single_app/functions_simplechat_operations.py")
    background_tasks_content = read_text("application/single_app/background_tasks.py")
    backend_agents_content = read_text("application/single_app/route_backend_agents.py")
    admin_template_content = read_text("application/single_app/templates/admin_settings.html")
    workspace_template_content = read_text("application/single_app/templates/workspace.html")
    chats_template_content = read_text("application/single_app/templates/chats.html")
    sidebar_template_content = read_text("application/single_app/templates/_sidebar_nav.html")
    sidebar_short_template_content = read_text("application/single_app/templates/_sidebar_short_nav.html")
    sidebar_css_content = read_text("application/single_app/static/css/sidebar.css")
    personal_workflows_doc_content = read_text("docs/explanation/features/PERSONAL_WORKFLOWS.md")
    fix_doc_content = read_text("docs/explanation/fixes/WORKFLOW_ACCESS_CONTROL_FIX.md")
    setup_docs_content = read_text("docs/setup_instructions_manual.md")
    terraform_content = read_text("deployers/terraform/main.tf")
    deployer_version = read_text("deployers/version.txt").strip()
    app_roles = json.loads(read_text("deployers/azurecli/appRegistrationRoles.json"))

    assert 'VERSION = "0.241.106"' in config_content, (
        "Expected config.py to be bumped for workflow access controls."
    )
    assert 'WORKFLOW_USER_APP_ROLE = "WorkflowUser"' in settings_content, (
        "Expected a shared WorkflowUser app role constant."
    )
    assert "'allow_user_workflows': False" in settings_content, (
        "Expected personal workflows to default to disabled."
    )
    assert "'require_member_of_workflow_user': False" in settings_content, (
        "Expected WorkflowUser role enforcement to default to disabled."
    )
    assert "def has_workflow_user_app_role(user_roles):" in settings_content, (
        "Expected WorkflowUser role detection helper."
    )
    assert "def is_user_workflows_enabled_for_user(settings, user_roles=None, authorization_prechecked=False):" in settings_content, (
        "Expected effective per-user workflow access helper."
    )
    assert "def workflow_user_required(f):" in settings_content, (
        "Expected reusable workflow route decorator."
    )

    workflow_api_route_count = workflow_routes_content.count("@enabled_required('allow_user_workflows')")
    assert workflow_api_route_count == 7, "Expected seven backend personal workflow API route gates."
    assert workflow_routes_content.count("@workflow_user_required") == workflow_api_route_count, (
        "Expected every backend workflow API route to require workflow user access."
    )
    assert "@workflow_user_required" in frontend_chats_content, (
        "Expected the workflow activity page to require workflow user access."
    )

    assert "public_settings['allow_user_workflows'] = is_user_workflows_enabled_for_user" in frontend_workspace_content, (
        "Expected workspace rendering to use effective user workflow access."
    )
    assert "public_settings['allow_user_workflows'] = user_workflows_enabled_for_user" in frontend_chats_content, (
        "Expected chat rendering to use effective user workflow access."
    )
    assert "is_user_workflows_enabled_for_user(settings, user_roles=user_roles)" in simplechat_operations_content, (
        "Expected SimpleChat workflow creation operations to enforce workflow access."
    )
    assert "settings.get('allow_user_workflows', False)" in background_tasks_content, (
        "Expected scheduled workflow polling to honor disabled-by-default workflows."
    )
    assert '"allow_user_workflows": settings.get("allow_user_workflows", False)' in backend_agents_content, (
        "Expected backend agent settings response to expose disabled-by-default workflow state."
    )

    assert "settings['allow_user_workflows'] = False" in admin_route_content, (
        "Expected Admin Settings GET defaults to initialize workflows as disabled."
    )
    assert "settings['require_member_of_workflow_user'] = False" in admin_route_content, (
        "Expected Admin Settings GET defaults to initialize WorkflowUser enforcement as disabled."
    )
    assert "'allow_user_workflows': form_data.get('allow_user_workflows') == 'on'" in admin_route_content, (
        "Expected Admin Settings POST to persist the workflow enable toggle."
    )
    assert "'require_member_of_workflow_user': require_member_of_workflow_user" in admin_route_content, (
        "Expected Admin Settings POST to persist the WorkflowUser requirement."
    )

    assert 'id="workflow-settings-section"' in admin_template_content, (
        "Expected a dedicated admin Workflow section."
    )
    assert 'id="allow_user_workflows"' in admin_template_content, (
        "Expected admin workflow enable toggle markup."
    )
    assert 'id="require_member_of_workflow_user"' in admin_template_content, (
        "Expected admin WorkflowUser requirement toggle markup."
    )
    assert 'data-section="workflow-settings-section"' in sidebar_template_content, (
        "Expected Admin Settings sidebar navigation to link to Workflow settings."
    )

    assert '{% if settings.allow_user_workflows %}' in workspace_template_content, (
        "Expected workspace workflow tab and modals to be gated by effective workflow access."
    )
    assert 'id="workflow-activity-btn"' in chats_template_content, (
        "Expected chat workflow activity button markup to exist for authorized users."
    )
    assert '{% if settings.allow_user_workflows %}' in chats_template_content, (
        "Expected chat workflow activity button to be gated by effective workflow access."
    )
    assert 'data-tab="workflows-tab"' in sidebar_template_content, (
        "Expected workspace sidebar to include Your Workflows for authorized users."
    )
    assert 'id="sidebar-workflow-section"' in sidebar_template_content, (
        "Expected full chat sidebar workflow conversation section for authorized users."
    )
    assert 'id="sidebar-workflow-section"' in sidebar_short_template_content, (
        "Expected short chat sidebar workflow conversation section for authorized users."
    )
    assert ".sidebar-section-toggle" in sidebar_css_content, (
        "Expected shared sidebar section styling."
    )
    assert ".sidebar-workflow-list-container" in sidebar_css_content, (
        "Expected workflow sidebar list styling."
    )

    workflow_role = next((role for role in app_roles if role.get("value") == "WorkflowUser"), None)
    assert workflow_role is not None, "Expected WorkflowUser app role in Azure CLI role definitions."
    assert workflow_role.get("id") == "7d42c0b7-5a95-43b6-9e38-2fb06988901e", (
        "Expected WorkflowUser app role ID to match Terraform."
    )
    assert 'value                = "WorkflowUser"' in terraform_content, (
        "Expected WorkflowUser app role in Terraform role definitions."
    )
    assert deployer_version == "1.0.10", "Expected deployer version bump after role definition changes."

    assert "WorkflowUser" in personal_workflows_doc_content, (
        "Expected Personal Workflows documentation to describe WorkflowUser."
    )
    assert "Fixed in version: **0.241.106**" in fix_doc_content, (
        "Expected workflow access control fix documentation with version."
    )
    assert "`WorkflowUser`" in setup_docs_content, (
        "Expected manual setup docs to include the WorkflowUser app role."
    )

    print("Workflow access control wiring verified.")


def run_tests():
    tests = [test_workflow_access_control_wiring]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("Test passed")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)
