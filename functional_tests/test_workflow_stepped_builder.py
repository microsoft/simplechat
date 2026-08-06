# test_workflow_stepped_builder.py
"""
Functional test for the stepped workflow builder.
Version: 0.250.065
Implemented in: 0.250.064
Enhanced in: 0.250.065

This test ensures personal and group workflow modals use the same five-step
builder and submit ordered tasks and error handling through existing routes.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.250.065"


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_personal_and_group_templates_share_five_step_builder() -> None:
    """Both workflow scopes must expose the same step and task controls."""
    print("Testing stepped workflow template contract...")
    for template_path in (
        "application/single_app/templates/workspace.html",
        "application/single_app/templates/group_workspaces.html",
    ):
        content = read_text(template_path)
        for step in ("general", "trigger", "tasks", "reliability", "review"):
            assert f'data-workflow-step-target="{step}"' in content
            assert f'data-workflow-step="{step}"' in content
        for element_id in (
            "workflow-task-list",
            "workflow-add-task-btn",
            "workflow-task-name",
            "workflow-task-runner-type",
            "workflow-task-model-fields",
            "workflow-task-model-source",
            "workflow-task-model-endpoint",
            "workflow-task-model",
            "workflow-task-agent-fields",
            "workflow-task-agent",
            "workflow-error-strategy-halt",
            "workflow-error-strategy-continue",
            "workflow-task-retry-count",
            "workflow-review-summary",
            "workflow-step-back-btn",
            "workflow-step-next-btn",
        ):
            assert f'id="{element_id}"' in content
        assert "modal-dialog modal-xl modal-dialog-scrollable" in content
        assert '<label for="workflow-runner-type" class="form-label">Default Runner</label>' in content
        assert '<option value="inherit">Workflow default</option>' in content
        assert "cdn.tailwindcss.com" not in content
        assert "fonts.googleapis.com" not in content

    print("PASS: stepped workflow template contract")


def test_shared_browser_behavior_builds_safe_ordered_task_payload() -> None:
    """The shared module must safely render and submit task sequence state."""
    print("Testing stepped workflow browser behavior contract...")
    content = read_text("application/single_app/static/js/workspace/workspace_workflows.js")

    for function_name in (
        "renderWorkflowTasks",
        "addWorkflowTask",
        "moveWorkflowTask",
        "removeWorkflowTask",
        "initializeWorkflowTasks",
        "normalizeWorkflowTaskRunner",
        "serializeWorkflowTaskRunner",
        "getWorkflowTaskRunnerSummary",
        "updateWorkflowTaskRunnerFields",
        "renderWorkflowReview",
        "validateWorkflowStep",
        "showWorkflowStep",
        "navigateWorkflowStep",
    ):
        assert f"function {function_name}(" in content
    assert "workflowTasks.map((task, index) => ({" in content
    assert "runner: serializeWorkflowTaskRunner(task.runner)," in content
    assert "error_handling:" in content
    assert "workflow-review-summary__item" in content
    assert 'name.textContent = task.name || `Task ${index + 1}`;' in content
    assert "runner.textContent = getWorkflowTaskRunnerSummary(task);" in content
    assert 'addWorkflowReviewItem("Default Runner"' in content
    assert "workflowTaskAgentSelect.innerHTML" not in content
    assert "item.innerHTML" not in content

    print("PASS: stepped workflow browser behavior contract")


def test_existing_routes_persist_tasks_without_new_endpoints() -> None:
    """Task sequencing must reuse current create/update and run routes."""
    print("Testing stepped workflow route and persistence contract...")
    personal_store = read_text("application/single_app/functions_personal_workflows.py")
    group_store = read_text("application/single_app/functions_group_workflows.py")
    routes = read_text("application/single_app/route_backend_workflows.py")
    config = read_text("application/single_app/config.py")

    assert f'VERSION = "{EXPECTED_VERSION}"' in config
    assert "'tasks': tasks," in personal_store
    assert "'error_handling': error_handling," in personal_store
    assert "'tasks': tasks," in group_store
    assert "'error_handling': error_handling," in group_store
    assert "save_personal_workflow(" in routes
    assert "save_group_workflow(" in routes
    assert "/api/user/workflows/<workflow_id>/run" in routes
    assert "/api/group/workflows/<workflow_id>/run" in routes
    assert "/task-runners" not in routes

    print("PASS: stepped workflow route and persistence contract")


def run_tests() -> bool:
    tests = [
        test_personal_and_group_templates_share_five_step_builder,
        test_shared_browser_behavior_builds_safe_ordered_task_payload,
        test_existing_routes_persist_tasks_without_new_endpoints,
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