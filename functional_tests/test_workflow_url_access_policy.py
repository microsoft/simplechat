# test_workflow_url_access_policy.py
#!/usr/bin/env python3
"""
Functional test for workflow URL Access policy wiring.
Version: 0.241.082
Implemented in: 0.241.081
Updated in: 0.241.082

This test ensures workflow URL Access is an explicit saved workflow option,
uses the shared workflow URL limit and optional UrlAccessUser role gate, validates
requests server-side, and injects Source Review evidence only through the workflow runner.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
WORKFLOW_STORAGE = APP_ROOT / "functions_personal_workflows.py"
WORKFLOW_RUNNER = APP_ROOT / "functions_workflow_runner.py"
WORKFLOW_ROUTES = APP_ROOT / "route_backend_workflows.py"
WORKSPACE_TEMPLATE = APP_ROOT / "templates" / "workspace.html"
WORKSPACE_WORKFLOWS_JS = APP_ROOT / "static" / "js" / "workspace" / "workspace_workflows.js"


def read_text(path):
    """Read a source file for static regression checks."""
    return path.read_text(encoding="utf-8")


def test_workflow_persists_url_access_opt_in():
    """Validate workflow definitions persist the explicit URL Access flag."""
    print("Testing workflow URL Access persistence...")

    source = read_text(WORKFLOW_STORAGE)

    assert "def _normalize_bool" in source
    assert "workflow_data.get(\n            'url_access_enabled'" in source
    assert "existing_workflow.get('url_access_enabled', False)" in source
    assert "'url_access_enabled': url_access_enabled" in source
    assert "'url_access_authorized': url_access_authorized" in source
    assert "'url_access_authorized_by':" in source
    assert "'url_access_authorized_at':" in source


def test_workflow_routes_enforce_url_access_role_gate():
    """Validate workflow saves and manual runs carry URL Access role context."""
    print("Testing workflow URL Access route role gate...")

    source = read_text(WORKFLOW_ROUTES)

    assert "require_member_of_url_access_user" not in source
    assert "has_url_access_app_role" in source
    assert "is_url_access_enabled_for_user" in source
    assert "validate_url_access_request(" in source
    assert "URL Access requires the UrlAccessUser app role." in source
    assert "payload['url_access_authorized'] = has_url_access_app_role(current_user_roles)" in source
    assert "run_personal_workflow(" in source
    assert "user_roles=(session.get('user') or {}).get('roles', [])" in source


def test_workflow_runner_enforces_url_access_policy():
    """Validate workflow runs use URL Access validation and Source Review evidence."""
    print("Testing workflow URL Access runner policy...")

    source = read_text(WORKFLOW_RUNNER)

    assert "URL_ACCESS_CONTEXT_WORKFLOW" in source
    assert "validate_url_access_request(" in source
    assert "execution_context=URL_ACCESS_CONTEXT_WORKFLOW" in source
    assert "authorization_prechecked=bool(workflow.get('url_access_authorized'))" in source
    assert "perform_source_review(" in source
    assert "url_access_only=True" in source
    assert "include_direct_user_urls=True" in source
    assert "url_access_context=URL_ACCESS_CONTEXT_WORKFLOW" in source
    assert "_build_workflow_chat_messages" in source
    assert "_build_workflow_agent_messages" in source
    assert "compact_source_review_result_for_metadata" in source
    assert "'web_search_citations': web_search_citations" in source
    assert "'url_access': execution_result.get('url_access') or {}" in source
    assert "Workflow URL Access requires the UrlAccessUser app role." in source
    assert "'content': workflow.get('task_prompt', '')" in source


def test_workflow_modal_exposes_explicit_url_access_control():
    """Validate workspace workflow authoring shows a saved URL Access switch."""
    print("Testing workflow URL Access UI markup...")

    template_source = read_text(WORKSPACE_TEMPLATE)

    assert "settings.enable_url_access" in template_source
    assert "id=\"workflow-url-access-enabled\"" in template_source
    assert "Allow URL Access for this workflow" in template_source
    assert "settings.url_access_max_workflow_urls_per_run" in template_source
    assert "window.urlAccessSettings" in template_source
    assert "url_access_max_workflow_urls_per_run" in template_source


def test_workspace_js_saves_and_validates_workflow_url_access():
    """Validate workflow JavaScript saves the flag and checks URL counts."""
    print("Testing workflow URL Access JavaScript payload handling...")

    source = read_text(WORKSPACE_WORKFLOWS_JS)

    assert "const workflowUrlAccessEnabledToggle = document.getElementById(\"workflow-url-access-enabled\")" in source
    assert "const WORKFLOW_URL_PATTERN" in source
    assert "function getWorkflowPromptUrls()" in source
    assert "workflowUrlAccessEnabledToggle.checked = Boolean(workflow.url_access_enabled)" in source
    assert "url_access_enabled: isWorkflowUrlAccessAvailable() ? Boolean(workflowUrlAccessEnabledToggle?.checked) : false" in source
    assert "URL Access workflows support up to ${maxWorkflowUrls} URLs per run." in source


def main():
    """Run all workflow URL Access regression checks."""
    tests = [
        test_workflow_persists_url_access_opt_in,
        test_workflow_routes_enforce_url_access_role_gate,
        test_workflow_runner_enforces_url_access_policy,
        test_workflow_modal_exposes_explicit_url_access_control,
        test_workspace_js_saves_and_validates_workflow_url_access,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print(f"Test passed: {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())