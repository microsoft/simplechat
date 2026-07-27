# test_generic_workflow_automation.py
"""
Functional test for generic workflow automation.
Version: 0.250.063
Implemented in: 0.250.063

This test ensures a workflow requires instructions and a selected model or
agent, while workspace document actions remain explicitly optional.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.250.063"


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def get_document_action_selector(template_content: str) -> str:
    selector_start = template_content.index('id="workflow-document-action-type"')
    selector_end = template_content.index("</select>", selector_start)
    return template_content[selector_start:selector_end]


def test_generic_workflow_ui_defaults_to_no_document_action() -> None:
    """New personal and group workflows must expose and default to no document action."""
    print("Testing generic workflow document-optional UI contract...")

    config_content = read_text("application/single_app/config.py")
    feature_doc_content = read_text("docs/explanation/features/GENERIC_WORKFLOW_AUTOMATION.md")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")

    assert f'VERSION = "{EXPECTED_VERSION}"' in config_content
    assert "# Generic Workflow Automation" in feature_doc_content
    assert f"Implemented in version: **{EXPECTED_VERSION}**" in feature_doc_content
    assert "No document action" in feature_doc_content
    assert "workflowDocumentActionTypeSelect.value = DOCUMENT_ACTION_NONE;" in workflow_js_content
    assert "const documentActionType = normalizeText(workflowDocumentActionTypeSelect?.value) || DOCUMENT_ACTION_NONE;" in workflow_js_content
    assert "if (actionType === DOCUMENT_ACTION_NONE) {" in workflow_js_content
    assert "setWorkflowPickerLoadingState(false);" in workflow_js_content
    assert "setElementVisibility(workflowAnalysisRetriesGroup, hasWindowedDocumentAction);" in workflow_js_content

    for template_path in (
        "application/single_app/templates/workspace.html",
        "application/single_app/templates/group_workspaces.html",
    ):
        selector_content = get_document_action_selector(read_text(template_path))
        assert '<option value="none"' in selector_content
        assert ">No document action</option>" in selector_content
        assert selector_content.index('value="none"') < selector_content.index('value="search"')

    print("PASS: generic workflow UI defaults to no document action")


def test_generic_workflow_runner_retains_direct_execution_paths() -> None:
    """No-document workflows must retain both direct model and agent execution branches."""
    print("Testing generic workflow execution contract...")

    workflow_store_content = read_text("application/single_app/functions_personal_workflows.py")
    group_workflow_store_content = read_text("application/single_app/functions_group_workflows.py")
    workflow_runner_content = read_text("application/single_app/functions_workflow_runner.py")
    workflow_js_content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")

    assert "task_prompt = _normalize_text(workflow_data.get('task_prompt'), 'Task prompt', required=True)" in workflow_store_content
    assert "runner_type = _normalize_text(workflow_data.get('runner_type'), 'Runner type', required=True).lower()" in workflow_store_content
    assert "'chat_capabilities_enabled': chat_capabilities_enabled," in workflow_store_content
    assert "'chat_capabilities_enabled': chat_capabilities_enabled," in group_workflow_store_content
    assert "chat_capabilities_enabled: currentEditingWorkflow" in workflow_js_content
    assert "elif execution_workflow.get('runner_type') == 'agent':" in workflow_runner_content
    assert "lambda: _execute_agent_workflow(" in workflow_runner_content
    assert "lambda: _execute_model_workflow(" in workflow_runner_content

    print("PASS: generic workflow execution retains direct model and agent paths")


def run_tests() -> bool:
    tests = [
        test_generic_workflow_ui_defaults_to_no_document_action,
        test_generic_workflow_runner_retains_direct_execution_paths,
    ]
    results = []

    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            results.append(False)

    print(f"Results: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)