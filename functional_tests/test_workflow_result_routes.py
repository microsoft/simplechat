# test_workflow_result_routes.py
"""
Functional tests for scoped workflow task-result page endpoints.
Version: 0.261.109
Implemented in: 0.261.106

Production route bodies and the response helper run in a Flask test client.
The existing route policy suite independently covers authentication decorators.
"""

import ast
import logging
import sys
import uuid
from pathlib import Path

import pytest
from azure.core.exceptions import AzureError, ServiceRequestError
from flask import Flask, jsonify, request


ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "application" / "single_app" / "route_backend_workflows.py"
RUNNER = ROOT / "application" / "single_app" / "functions_workflow_runner.py"
sys.path.insert(0, str(RUNNER.parent))

# Import the domain error after establishing the worktree module path.
from functions_workflow_result_store import WorkflowResultStorageUnavailableError
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_results import (
    ANALYSIS_SOURCE_ACCESS_VERSION,
    WORKFLOW_RESULT_CONTRACT_VERSION,
    authorize_workflow_task_result_read,
)


@pytest.fixture
def result_client():
    reads = []
    state = {"actor": "owner", "group_allowed": True, "source_allowed": True, "source_readers": []}
    workflow = {"id": "workflow-1", "user_id": "owner"}
    run = {"id": "run-1", "workflow_id": "workflow-1"}
    reference = {"sha256": "stored-reference", "size_bytes": 20000}
    item = {
        "workflow_id": "workflow-1", "run_id": "run-1", "task_id": "extract",
        "workflow_result": {
            "result_ref": reference,
            "authoritative_output": "records",
            "outputs": {
                "records": {"kind": "records", "result_ref": {"sha256": "final-records"}},
                "diagnostics": {"kind": "diagnostics", "result_ref": {"sha256": "raw-notes"}},
            },
        },
    }

    def authorize_group(user_id):
        if not state["group_allowed"]:
            raise PermissionError("Revoked membership.")
        return "group-1", {}

    def lookup_workflow(user_id, workflow_id):
        return workflow if user_id == "owner" and workflow_id == workflow["id"] else None

    def lookup_group(group_id, workflow_id):
        if group_id == "group-1" and workflow_id == workflow["id"]:
            return {**workflow, "group_id": group_id}
        return None

    def read_page(bound_workflow, run_id, task_id, result_ref, **kwargs):
        reads.append((bound_workflow, run_id, task_id, result_ref, kwargs))
        if state.get("read_error"):
            raise state["read_error"]
        return {
            "content": '{"inventory_id":"fictional-1"}',
            "offset": kwargs["offset"],
            "next_offset": kwargs["offset"] + kwargs["limit"],
            "total_bytes": 20000,
            "complete": False,
            "sha256": result_ref["sha256"],
        }

    def authorize_result(bound_workflow, run_id, task_id, result_ref, *, reader_user_id):
        if state.get("authorization_error"):
            raise state["authorization_error"]
        manifest = {
            "contract_version": WORKFLOW_RESULT_CONTRACT_VERSION,
            "identity": {"workflow_id": bound_workflow["id"], "run_id": run_id, "task_id": task_id},
            "authoritative_output": item["workflow_result"].get("authoritative_output"),
            "outputs": item["workflow_result"].get("outputs") or {},
        }
        source = {
            "document_id": "source-1", "scope": "group", "scope_id": "source-group",
            "source_version": "1", "source_revision": "etag-1",
        }
        if state.get("analysis_result"):
            manifest["analysis_access"] = {
                "version": ANALYSIS_SOURCE_ACCESS_VERSION, "sources": [source],
            }

        def resolve_sources(document_ids, **context):
            state["source_readers"].append(context["user_id"])
            return [{
                **source,
                "authorization_status": "authorized" if state["source_allowed"] else "unresolved",
            }]

        return authorize_workflow_task_result_read(
            bound_workflow, run_id, task_id, result_ref, reader_user_id=reader_user_id,
            load_result=lambda *args: manifest, source_resolver=resolve_sources,
        )

    namespace = {
        "uuid": uuid,
        "logging": logging,
        "AzureError": AzureError,
        "WorkflowResultStorageUnavailableError": WorkflowResultStorageUnavailableError,
        "jsonify": jsonify,
        "request": request,
        "log_event": lambda *args, **kwargs: None,
        "get_current_user_id": lambda: state["actor"],
        "get_personal_workflow": lookup_workflow,
        "get_group_workflow": lookup_group,
        "get_personal_workflow_run": lambda owner_id, run_id: run if run_id == run["id"] else None,
        "get_group_workflow_run": lambda group_id, run_id: run if run_id == run["id"] else None,
        "get_personal_workflow_run_item": lambda run_id, item_id: item,
        "get_group_workflow_run_item": lambda run_id, item_id: item,
        "_resolve_group_workflow_request_group": authorize_group,
        "read_workflow_task_result_page": read_page,
        "authorize_workflow_task_result_read": authorize_result,
    }
    names = {
        "_normalize_identifier", "_workflow_task_result_page_response",
        "get_user_workflow_task_result", "get_group_workflow_task_result",
        "_workflow_task_run_item_id",
    }
    nodes = []
    for path in (ROUTES, RUNNER):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and node.name in names:
                node.decorator_list = []
                nodes.append(node)
    assert {node.name for node in nodes} == names
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROUTES), "exec"), namespace)
    app = Flask("workflow-result-routes")
    for scope in ("user", "group"):
        app.add_url_rule(
            f"/{scope}/<workflow_id>/<run_id>/<task_id>",
            endpoint=scope,
            view_func=namespace[f"get_{scope}_workflow_task_result"],
        )
    return app.test_client(), state, workflow, run, item, reads


@pytest.mark.parametrize("scope", ["user", "group"])
def test_result_pages_use_stored_reference_and_requested_bounds(result_client, scope):
    client, state, workflow, run, item, reads = result_client
    response = client.get(
        f"/{scope}/workflow-1/run-1/extract?offset=12&limit=128&blob_path=not-authorized"
    )
    assert response.status_code == 200
    assert response.json["content"] == '{"inventory_id":"fictional-1"}'
    assert reads[0][3] == item["workflow_result"]["result_ref"]
    assert reads[0][4] == {"offset": 12, "limit": 128}


def test_other_user_cannot_read_workflow_result(result_client):
    client, state, workflow, run, item, reads = result_client
    state["actor"] = "another-user"
    assert client.get("/user/workflow-1/run-1/extract").status_code == 404
    assert reads == []


@pytest.mark.parametrize("scope", ["user", "group"])
def test_revoked_contributor_blocks_the_page_before_any_content_read(result_client, scope):
    client, state, workflow, run, item, reads = result_client
    state["authorization_error"] = AnalysisResultUnavailable()
    response = client.get(f"/{scope}/workflow-1/run-1/extract?output=authoritative")
    assert response.status_code == 403
    assert "content" not in response.json
    assert reads == []


def test_authoritative_output_and_diagnostics_are_separately_addressed(result_client):
    client, state, workflow, run, item, reads = result_client
    final = client.get("/user/workflow-1/run-1/extract?output=authoritative")
    diagnostics = client.get("/user/workflow-1/run-1/extract?output=diagnostics")
    assert final.status_code == diagnostics.status_code == 200
    assert final.json["output_name"] == "records"
    assert [read[3]["sha256"] for read in reads] == ["final-records", "raw-notes"]
    assert client.get("/user/workflow-1/run-1/extract?output=not-a-section").status_code == 404
    assert len(reads) == 2


def test_revoked_group_membership_blocks_subsequent_page(result_client):
    client, state, workflow, run, item, reads = result_client
    assert client.get("/group/workflow-1/run-1/extract?limit=128").status_code == 200
    state["group_allowed"] = False
    assert client.get("/group/workflow-1/run-1/extract?offset=128").status_code == 403
    assert len(reads) == 1


@pytest.mark.parametrize("field", ["workflow_id", "run_id", "task_id"])
def test_foreign_task_identity_never_reaches_storage(result_client, field):
    client, state, workflow, run, item, reads = result_client
    item[field] = "foreign"
    assert client.get("/user/workflow-1/run-1/extract").status_code == 404
    assert reads == []


def test_foreign_run_cannot_be_attached_to_workflow(result_client):
    client, state, workflow, run, item, reads = result_client
    run["workflow_id"] = "another-workflow"
    assert client.get("/user/workflow-1/run-1/extract").status_code == 404
    assert reads == []


@pytest.mark.parametrize("scope", ["user", "group"])
def test_missing_run_returns_not_found_without_reading_storage(result_client, scope):
    client, state, workflow, run, item, reads = result_client
    assert client.get(f"/{scope}/workflow-1/nonexistent-run/extract").status_code == 404
    assert reads == []


@pytest.mark.parametrize("error,status", [
    (ServiceRequestError("PRIVATE-PROVIDER-DETAIL"), 503),
    (WorkflowResultStorageUnavailableError("PRIVATE-CONFIGURATION-DETAIL"), 503),
    (ValueError("PRIVATE-INTEGRITY-DETAIL"), 409),
])
def test_result_read_failures_are_explicit_and_do_not_expose_details(result_client, error, status):
    client, state, workflow, run, item, reads = result_client
    state["read_error"] = error
    response = client.get("/user/workflow-1/run-1/extract")
    assert response.status_code == status
    assert "PRIVATE" not in response.get_data(as_text=True)
    assert "content" not in response.json


@pytest.mark.parametrize("query", ["offset=-1", "limit=0", "limit=65537", "offset=no", "limit=1.5"])
def test_result_reader_rejects_invalid_ranges(result_client, query):
    client, state, workflow, run, item, reads = result_client
    assert client.get(f"/user/workflow-1/run-1/extract?{query}").status_code == 400
    assert reads == []


def test_legacy_preview_is_not_substituted_for_a_saved_result(result_client):
    client, state, workflow, run, item, reads = result_client
    item.pop("workflow_result")
    item["output_preview"] = "A legacy display preview."
    response = client.get("/user/workflow-1/run-1/extract")
    assert response.status_code == 409
    assert "content" not in response.json
    assert reads == []


@pytest.mark.parametrize("output", ["manifest", "authoritative", "diagnostics"])
def test_source_revocation_blocks_every_saved_representation(result_client, output):
    client, state, workflow, run, item, reads = result_client
    state["analysis_result"] = True
    state["source_allowed"] = False
    response = client.get(f"/user/workflow-1/run-1/extract?output={output}")
    assert response.status_code == 403
    assert "content" not in response.json
    assert reads == []


def test_group_result_source_access_uses_current_reader(result_client):
    client, state, workflow, run, item, reads = result_client
    state["analysis_result"] = True
    state["actor"] = "viewing-member"
    assert client.get("/group/workflow-1/run-1/extract").status_code == 200
    assert state["source_readers"] == ["viewing-member"]
