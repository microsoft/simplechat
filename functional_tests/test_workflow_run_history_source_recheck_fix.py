# test_workflow_run_history_source_recheck_fix.py
"""
Functional test for the workflow run history source re-check fix.
Version: 0.261.229
Implemented in: 0.261.229

This test ensures that workflow run lists and run task items load from the
workflow the caller can already read, without re-checking each run's source
documents, and that a task is not failed after its output is saved because one
of its sources can no longer be confirmed. It also checks that the Approvals
page shows the content screening notice only while content screening is on.

The route bodies and the task sequence are the application's own definitions,
compiled from source with only storage and identity doubled.
"""

import ast
import sys
from pathlib import Path

import pytest
from flask import Flask, jsonify
from jinja2 import ChainableUndefined, ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.append(str(Path(__file__).resolve().parent))
sys.path.insert(0, str(APP_ROOT))

from functions_analysis_access import AnalysisResultUnavailable  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_workflow_task_sequence import load_runner_helpers  # noqa: E402  (real runner harness)


ROUTES = APP_ROOT / "route_backend_workflows.py"
TEMPLATES = APP_ROOT / "templates"
FIX_VERSION = "0.261.229"
ROUTE_NAMES = {
    "_normalize_identifier",
    "get_user_workflow_runs",
    "get_user_workflow_run_items",
    "get_group_workflow_runs_route",
    "get_group_workflow_run_items_route",
}


def _source_cannot_be_confirmed(*_args, **_kwargs):
    raise AnalysisResultUnavailable()


@pytest.fixture
def run_history_client():
    workflow = {"id": "workflow-1", "user_id": "owner", "name": "Weekly summary"}
    runs = [{"id": f"run-{index}", "workflow_id": "workflow-1", "status": "completed"} for index in range(3)]
    items = [{"id": "item-1", "run_id": "run-0", "task_id": "summarize", "status": "succeeded"}]
    sanitized = []

    def sanitize(workflow_record, run_record, user_id, items=None):
        sanitized.append(run_record["id"])
        return run_record, items, True

    def find_run(run_id):
        return next((dict(run) for run in runs if run["id"] == run_id), None)

    namespace = {
        "jsonify": jsonify,
        "AnalysisResultUnavailable": AnalysisResultUnavailable,
        # Any per-run source re-check would fail, as it did for a deleted or re-uploaded source.
        "authorize_workflow_run_read": _source_cannot_be_confirmed,
        "get_current_user_id": lambda: "owner",
        "get_personal_workflow": lambda user_id, workflow_id: dict(workflow) if workflow_id == workflow["id"] else None,
        "get_group_workflow": lambda group_id, workflow_id: dict(workflow) if workflow_id == workflow["id"] else None,
        "list_personal_workflow_runs": lambda user_id, workflow_id, limit=50: [dict(run) for run in runs],
        "list_group_workflow_runs": lambda group_id, workflow_id, limit=50: [dict(run) for run in runs],
        "get_personal_workflow_run": lambda user_id, run_id: find_run(run_id),
        "get_group_workflow_run": lambda group_id, run_id: find_run(run_id),
        "list_personal_workflow_run_items": lambda run_id, limit=1000: [dict(item) for item in items],
        "list_group_workflow_run_items": lambda run_id, limit=1000: [dict(item) for item in items],
        "_resolve_group_workflow_request_group": lambda user_id: ("group-1", {}),
        "_resolve_active_group_for_workflows": lambda user_id: ("group-1", {}),
        "sanitize_workflow_analysis_history": sanitize,
    }
    nodes = []
    for node in ast.walk(ast.parse(ROUTES.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name in ROUTE_NAMES:
            node.decorator_list = []
            nodes.append(node)
    assert sorted(node.name for node in nodes) == sorted(ROUTE_NAMES)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROUTES), "exec"), namespace)

    app = Flask("workflow-run-history")
    app.add_url_rule("/api/user/workflows/<workflow_id>/runs", view_func=namespace["get_user_workflow_runs"])
    app.add_url_rule(
        "/api/user/workflows/<workflow_id>/runs/<run_id>/items", view_func=namespace["get_user_workflow_run_items"],
    )
    app.add_url_rule("/api/group/workflows/<workflow_id>/runs", view_func=namespace["get_group_workflow_runs_route"])
    app.add_url_rule(
        "/api/group/workflows/<workflow_id>/runs/<run_id>/items",
        view_func=namespace["get_group_workflow_run_items_route"],
    )
    return app.test_client(), sanitized


def _render_approvals(screening_enabled):
    environment = Environment(
        loader=ChoiceLoader([
            DictLoader({"base.html": "{% block content %}{% endblock %}{% block scripts %}{% endblock %}"}),
            FileSystemLoader(str(TEMPLATES)),
        ]),
        undefined=ChainableUndefined,
        autoescape=select_autoescape(["html"]),
    )
    environment.globals["url_for"] = lambda endpoint, **values: "/static/" + values.get("filename", "")
    return environment.get_template("approvals.html").render(
        app_settings={"app_title": "SimpleChat"},
        settings={"enable_content_screening": screening_enabled},
        config={"VERSION": FIX_VERSION},
        has_agent_template_admin_access=False,
    )


def test_fix_version_is_present():
    assert_app_version_at_least(FIX_VERSION)


@pytest.mark.parametrize("scope", ["user", "group"])
def test_run_list_loads_without_rechecking_each_runs_sources(run_history_client, scope):
    client, sanitized = run_history_client
    response = client.get(f"/api/{scope}/workflows/workflow-1/runs")
    assert response.status_code == 200
    assert [run["id"] for run in response.json["runs"]] == ["run-0", "run-1", "run-2"]
    assert sanitized == ["run-0", "run-1", "run-2"]


@pytest.mark.parametrize("scope", ["user", "group"])
def test_run_items_load_without_rechecking_the_runs_sources(run_history_client, scope):
    client, _ = run_history_client
    response = client.get(f"/api/{scope}/workflows/workflow-1/runs/run-0/items")
    assert response.status_code == 200
    assert response.json["run_id"] == "run-0"
    assert [item["task_id"] for item in response.json["items"]] == ["summarize"]


@pytest.mark.parametrize("scope", ["user", "group"])
def test_container_checks_still_hide_a_missing_workflow_or_run(run_history_client, scope):
    client, sanitized = run_history_client
    assert client.get(f"/api/{scope}/workflows/other-workflow/runs").status_code == 404
    assert client.get(f"/api/{scope}/workflows/workflow-1/runs/missing-run/items").status_code == 404
    assert sanitized == []


def test_workflow_routes_never_recheck_run_sources():
    source = ROUTES.read_text(encoding="utf-8")
    assert "authorize_workflow_run_read" not in source
    assert "Run history is unavailable because source access could not be confirmed." not in source
    assert "Task results are unavailable because source access could not be confirmed." not in source


def test_saved_task_output_is_not_withheld_after_it_is_saved():
    def dispatch(workflow, *_args, **_kwargs):
        return {"reply": "Summary of the uploaded report."}

    helpers, saved_items = load_runner_helpers(dispatch)
    # Re-reading the saved output against its sources would now fail.
    helpers["authorize_workflow_task_result_read"] = _source_cannot_be_confirmed
    result = helpers["_execute_workflow_task_sequence"](
        {
            "id": "workflow-1",
            "name": "Summarize",
            "user_id": "owner",
            "runner_type": "model",
            "document_action": {"type": "none"},
            "tasks": [{"id": "summarize", "name": "Summarize", "instructions": "Summarize the report."}],
            "error_handling": {"strategy": "halt", "retry_count": 0},
        },
        {},
        "conversation-1",
        "run-1",
        None,
        {},
    )
    assert result["task_error_count"] == 0
    assert [task["status"] for task in result["task_results"]] == ["succeeded"]
    assert result["task_results"][0]["workflow_result"]["result_ref"]
    assert not any("withheld" in str(item.get("error") or "") for item in saved_items)


@pytest.mark.parametrize("screening_enabled", [True, False])
def test_approvals_page_shows_the_screening_notice_only_when_screening_is_on(screening_enabled):
    markup = _render_approvals(screening_enabled)
    assert ('id="contentScreeningApprovalsNotice"' in markup) is screening_enabled
    assert ('href="/content-review"' in markup) is screening_enabled
    assert "revision-bound" not in markup
    # Content screening requests stay filterable, so existing holds remain reachable.
    assert 'value="content_screening_review"' in markup
