# test_workflow_cancellation.py
"""
Functional test for active workflow cancellation.
Version: 0.250.105
Implemented in: 0.250.062

This test ensures personal and group workflow cancellation requests persist by
scope and run id, stop the runner at a cooperative boundary, mark unfinished
items as cancelled, and return the workflow to an idle schedulable state.
"""

import ast
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
RUNNER_FILE = APP_ROOT / "functions_workflow_runner.py"
ROUTES_FILE = APP_ROOT / "route_backend_workflows.py"
BACKGROUND_TASKS_FILE = APP_ROOT / "background_tasks.py"
CONFIG_FILE = APP_ROOT / "config.py"
ACTIVITY_FILE = APP_ROOT / "functions_workflow_activity.py"
WORKSPACE_UI_FILE = APP_ROOT / "static" / "js" / "workspace" / "workspace_workflows.js"
ACTIVITY_UI_FILE = APP_ROOT / "static" / "js" / "workflow" / "workflow-activity.js"
ACTIVITY_CSS_FILE = APP_ROOT / "static" / "css" / "workflow-activity.css"
ACTIVITY_TEMPLATE_FILE = APP_ROOT / "templates" / "workflow_activity.html"
GROUP_TEMPLATE_FILE = APP_ROOT / "templates" / "group_workspaces.html"
RELEASE_NOTES_FILE = REPO_ROOT / "docs" / "explanation" / "release_notes.md"


def _read(path):
    return path.read_text(encoding="utf-8")


def _load_nodes(path, function_names=(), class_names=(), assignment_names=(), namespace=None):
    """Load selected top-level definitions without importing application services."""
    module_tree = ast.parse(_read(path), filename=str(path))
    wanted_functions = set(function_names)
    wanted_classes = set(class_names)
    wanted_assignments = set(assignment_names)
    selected_nodes = []
    found_functions = set()
    found_classes = set()
    found_assignments = set()

    for node in module_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_functions:
            selected_nodes.append(node)
            found_functions.add(node.name)
        elif isinstance(node, ast.ClassDef) and node.name in wanted_classes:
            selected_nodes.append(node)
            found_classes.add(node.name)
        elif isinstance(node, ast.Assign):
            assigned_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if assigned_names.intersection(wanted_assignments):
                selected_nodes.append(node)
                found_assignments.update(assigned_names.intersection(wanted_assignments))

    missing = (
        (wanted_functions - found_functions)
        | (wanted_classes - found_classes)
        | (wanted_assignments - found_assignments)
    )
    assert not missing, f"Missing selected definitions in {path.name}: {sorted(missing)}"

    selected_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(selected_module)
    resolved_namespace = dict(namespace or {})
    exec(compile(selected_module, str(path), "exec"), resolved_namespace)
    return resolved_namespace


def _load_cancellation_route_helpers():
    return _load_nodes(
        ROUTES_FILE,
        function_names=("_request_workflow_run_cancellation",),
        class_names=("WorkflowCancellationConflictError",),
        namespace={
            "datetime": datetime,
            "timezone": timezone,
            "_normalize_identifier": lambda value: str(value or "").strip(),
        },
    )


def _build_runner_storage_helpers():
    personal_runs = {
        ("user-1", "personal-run"): {
            "id": "personal-run",
            "workflow_id": "personal-workflow",
            "status": "cancelling",
            "cancellation_requested_at": "2026-07-27T12:00:00+00:00",
            "cancellation_requested_by": "user-1",
        },
    }
    group_runs = {
        ("group-1", "group-run"): {
            "id": "group-run",
            "workflow_id": "group-workflow",
            "status": "cancelling",
            "cancellation_requested_at": "2026-07-27T12:00:00+00:00",
            "cancellation_requested_by": "user-1",
        },
    }
    personal_workflows = {
        ("user-1", "personal-workflow"): {
            "id": "personal-workflow",
            "user_id": "user-1",
            "active_run_id": "personal-run",
            "status": "cancelling",
            "cancellation_requested_at": "2026-07-27T12:00:00+00:00",
        },
    }
    group_workflows = {
        ("group-1", "group-workflow"): {
            "id": "group-workflow",
            "user_id": "user-1",
            "group_id": "group-1",
            "active_run_id": "group-run",
            "status": "cancelling",
            "cancellation_requested_at": "2026-07-27T12:00:00+00:00",
        },
    }
    personal_items = {
        "personal-run": [
            {"id": "personal-queued", "status": "queued"},
            {"id": "personal-completed", "status": "succeeded"},
        ],
    }
    group_items = {
        "group-run": [
            {"id": "group-running", "status": "running"},
            {"id": "group-failed", "status": "failed"},
        ],
    }
    saved_items = []

    namespace = {
        "get_personal_workflow_run": lambda user_id, run_id: personal_runs.get((user_id, run_id)),
        "get_group_workflow_run": lambda group_id, run_id: group_runs.get((group_id, run_id)),
        "get_personal_workflow": lambda user_id, workflow_id: personal_workflows.get((user_id, workflow_id)),
        "get_group_workflow": lambda group_id, workflow_id: group_workflows.get((group_id, workflow_id)),
        "list_personal_workflow_run_items": lambda run_id, limit=1000: personal_items.get(run_id, []),
        "list_group_workflow_run_items": lambda run_id, limit=1000: group_items.get(run_id, []),
        "_utc_now_iso": lambda: "2026-07-27T12:01:00+00:00",
        "_save_workflow_run_item_record": lambda workflow, item: saved_items.append(dict(item)),
    }
    helpers = _load_nodes(
        RUNNER_FILE,
        function_names=(
            "_get_workflow_scope",
            "_get_workflow_group_id",
            "_get_workflow_run_record",
            "_get_current_workflow_runtime",
            "_list_workflow_run_items",
            "_has_workflow_run_cancellation_request",
            "_is_workflow_run_cancellation_requested",
            "_raise_if_workflow_run_cancelled",
            "_execute_cancelable_workflow_step",
            "_preserve_workflow_run_cancellation_request",
            "_mark_unfinished_workflow_run_items_cancelled",
        ),
        class_names=("WorkflowRunCancelledError",),
        assignment_names=("WORKFLOW_RUN_CANCELLED_MESSAGE",),
        namespace=namespace,
    )
    return helpers, saved_items


def test_cancellation_request_persists_personal_and_group_runs():
    """Cancellation must persist for the exact active run in both workflow scopes."""
    helpers = _load_cancellation_route_helpers()
    request_cancellation = helpers["_request_workflow_run_cancellation"]

    for scope, workflow in (
        (
            "personal",
            {"id": "personal-workflow", "active_run_id": "personal-run", "status": "running"},
        ),
        (
            "group",
            {"id": "group-workflow", "active_run_id": "group-run", "status": "running"},
        ),
    ):
        stored_runs = {
            workflow["active_run_id"]: {
                "id": workflow["active_run_id"],
                "workflow_id": workflow["id"],
                "status": "running",
            },
        }
        runtime_updates = []

        def get_run(run_id):
            return stored_runs.get(run_id)

        def save_run(run_record):
            stored_runs[run_record["id"]] = dict(run_record)
            return dict(run_record)

        def update_runtime_fields(updates):
            runtime_updates.append(dict(updates))
            updated_workflow = dict(workflow)
            updated_workflow.update(updates)
            return updated_workflow

        updated_workflow, run_record = request_cancellation(
            workflow,
            run_id="",
            requested_by="user-1",
            get_run=get_run,
            save_run=save_run,
            update_runtime_fields=update_runtime_fields,
        )

        assert run_record["status"] == "cancelling", f"Expected {scope} run to enter cancelling state."
        assert run_record["cancellation_requested_by"] == "user-1"
        assert stored_runs[workflow["active_run_id"]]["status"] == "cancelling"
        assert updated_workflow["active_run_id"] == workflow["active_run_id"]
        assert runtime_updates[-1]["status"] == "cancelling"


def test_early_cancellation_is_saved_and_mismatched_runs_are_rejected():
    """A cancel request must survive before initial save and cannot target another run."""
    helpers = _load_cancellation_route_helpers()
    request_cancellation = helpers["_request_workflow_run_cancellation"]

    saved_runs = []
    workflow = {"id": "personal-workflow", "active_run_id": "run-before-initial-save", "status": "running"}
    _, early_run = request_cancellation(
        workflow,
        run_id="",
        requested_by="user-1",
        get_run=lambda run_id: None,
        save_run=lambda run_record: saved_runs.append(dict(run_record)) or dict(run_record),
        update_runtime_fields=lambda updates: {**workflow, **updates},
    )

    assert early_run["status"] == "cancelling"
    assert saved_runs == [early_run], "Expected early cancellation to persist a placeholder run record."

    try:
        request_cancellation(
            workflow,
            run_id="run-before-initial-save",
            requested_by="user-1",
            get_run=lambda run_id: {"id": run_id, "workflow_id": "different-workflow", "status": "running"},
            save_run=lambda run_record: run_record,
            update_runtime_fields=lambda updates: {**workflow, **updates},
        )
    except LookupError:
        pass
    else:
        raise AssertionError("Expected a workflow run belonging to another workflow to be rejected.")


def test_runner_cancellation_helpers_cover_personal_and_group_items():
    """Persisted requests stop new work and terminalize unfinished items in both scopes."""
    helpers, saved_items = _build_runner_storage_helpers()
    personal_workflow = {"id": "personal-workflow", "user_id": "user-1"}
    group_workflow = {"id": "group-workflow", "user_id": "user-1", "group_id": "group-1"}

    assert helpers["_is_workflow_run_cancellation_requested"](personal_workflow, "personal-run")
    assert helpers["_is_workflow_run_cancellation_requested"](group_workflow, "group-run")

    preserved_personal_run = helpers["_preserve_workflow_run_cancellation_request"](
        personal_workflow,
        {"id": "personal-run", "status": "running"},
    )
    preserved_group_run = helpers["_preserve_workflow_run_cancellation_request"](
        group_workflow,
        {"id": "group-run", "status": "running"},
    )
    assert preserved_personal_run["status"] == "cancelling"
    assert preserved_group_run["status"] == "cancelling"

    helpers["_mark_unfinished_workflow_run_items_cancelled"](personal_workflow, "personal-run")
    helpers["_mark_unfinished_workflow_run_items_cancelled"](group_workflow, "group-run")
    assert [item["id"] for item in saved_items] == ["personal-queued", "group-running"]
    assert all(item["status"] == "cancelled" for item in saved_items)
    assert all(item["completed_at"] == "2026-07-27T12:01:00+00:00" for item in saved_items)

    operation_calls = []
    try:
        helpers["_execute_cancelable_workflow_step"](
            personal_workflow,
            "personal-run",
            lambda: operation_calls.append("should-not-run"),
        )
    except helpers["WorkflowRunCancelledError"]:
        pass
    else:
        raise AssertionError("Expected a persisted cancellation request to stop the next workflow operation.")
    assert operation_calls == []


def test_runner_returns_cancelled_terminal_state_and_clears_active_run():
    """The runner must release its active run state after observing cancellation."""
    saved_runs = []
    cancelled_items = []
    logged_runs = []
    namespace = {
        "_get_workflow_group_id": lambda workflow: str(workflow.get("group_id") or ""),
        "_get_workflow_scope": lambda workflow: "group" if workflow.get("group_id") else "personal",
        "create_workflow_run_id": lambda: "generated-run",
        "_utc_now_iso": lambda: "2026-07-27T12:02:00+00:00",
        "get_settings": lambda: {},
        "_save_workflow_run_record": lambda workflow, run_record: saved_runs.append(dict(run_record)),
        "_raise_if_workflow_run_cancelled": lambda workflow, run_id: None,
        "_get_current_workflow_runtime": lambda workflow: {
            "cancellation_requested_at": "2026-07-27T12:00:00+00:00",
            "cancellation_requested_by": "user-1",
        },
        "_mark_unfinished_workflow_run_items_cancelled": lambda workflow, run_id: cancelled_items.append((workflow["id"], run_id)),
        "_add_workflow_activity_thought": lambda *args, **kwargs: None,
        "log_workflow_run": lambda **kwargs: logged_runs.append(dict(kwargs)),
    }
    helpers = _load_nodes(
        RUNNER_FILE,
        function_names=("_finalize_cancelled_workflow_run", "run_personal_workflow"),
        class_names=("WorkflowRunCancelledError",),
        assignment_names=("WORKFLOW_RUN_CANCELLED_MESSAGE",),
        namespace=namespace,
    )
    helpers["_raise_if_workflow_run_cancelled"] = lambda workflow, run_id: (_ for _ in ()).throw(
        helpers["WorkflowRunCancelledError"]("Workflow cancellation was requested.")
    )

    result = helpers["run_personal_workflow"](
        {"id": "group-workflow", "user_id": "user-1", "group_id": "group-1", "run_count": 2},
        trigger_source="scheduled",
        run_id="group-run",
    )

    assert result["success"] is True
    assert result["run"]["status"] == "cancelled"
    assert result["workflow_updates"]["active_run_id"] == ""
    assert result["workflow_updates"]["cancellation_requested_at"] is None
    assert result["workflow_updates"]["last_run_status"] == "cancelled"
    assert cancelled_items == [("group-workflow", "group-run")]
    assert saved_runs[-1]["status"] == "cancelled"
    assert logged_runs[-1]["status"] == "cancelled"
    assert logged_runs[-1]["workspace_type"] == "group"


def test_cancellation_contracts_cover_routes_scheduler_activity_and_shared_ui():
    """Personal and group cancellation must stay wired across all public surfaces."""
    route_source = _read(ROUTES_FILE)
    runner_source = _read(RUNNER_FILE)
    scheduler_source = _read(BACKGROUND_TASKS_FILE)
    activity_source = _read(ACTIVITY_FILE)
    workspace_ui_source = _read(WORKSPACE_UI_FILE)
    activity_ui_source = _read(ACTIVITY_UI_FILE)
    activity_css_source = _read(ACTIVITY_CSS_FILE)
    activity_template_source = _read(ACTIVITY_TEMPLATE_FILE)
    group_template_source = _read(GROUP_TEMPLATE_FILE)
    release_notes_source = _read(RELEASE_NOTES_FILE)

    assert 'VERSION = "0.250.105"' in _read(CONFIG_FILE)
    assert "### **(v0.250.062)**" in release_notes_source
    assert "Workflow Run Cancellation" in release_notes_source
    for route in (
        "/api/user/workflows/<workflow_id>/cancel",
        "/api/user/workflows/<workflow_id>/runs/<run_id>/cancel",
        "/api/group/workflows/<workflow_id>/cancel",
        "/api/group/workflows/<workflow_id>/runs/<run_id>/cancel",
    ):
        assert route in route_source, f"Missing cancellation endpoint: {route}"
    assert "_resolve_group_workflow_request_group(user_id)" in route_source
    assert "create_workflow_run_id" in route_source
    assert "create_workflow_run_id" in scheduler_source
    assert "WorkflowRunCancelledError" in runner_source
    assert "_mark_unfinished_workflow_run_items_cancelled" in runner_source
    assert "'last_run_status': 'cancelled'" in runner_source
    assert "{'running', 'cancelling'}" in route_source
    assert "{'running', 'cancelling'}" in activity_source
    assert "run_status in {'cancelled', 'canceled'}" in route_source
    assert 'data-action="cancel"' in workspace_ui_source
    assert "cancelWorkflow(workflow" in workspace_ui_source
    assert "workflow-activity-cancel-btn" in activity_template_source
    assert "buildWorkflowRunCancellationPath" in activity_ui_source
    assert '.workflow-activity-card[data-status="cancelling"]' in activity_css_source
    assert '.workflow-activity-card[data-status="cancelled"]' in activity_css_source
    assert "apiBase: '/api/group/workflows'" in group_template_source
